"""Running documents through the pipeline, and handling the people who review them.

Like services/results.py: this layer decides what happens and owns the transactions; it knows nothing
about HTTP. The routes call it, and turn its exceptions into status codes.

  process_document   the background job after an upload: claim, run the graph, save the result or the pause
  submit_review      a person answers a paused document: resume the graph, save the result and the review
  pending_question   what a paused document is waiting to be asked

Two separate stores are involved: the database tables (documents, extractions, reviews) and LangGraph's
checkpoints (where a paused run waits). They cannot be updated in one transaction. The order below keeps the
damage small: the database is written only after the graph has moved, in ONE transaction.
"""
import logging
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from freight_intel.db import tenant_session
from freight_intel.pipeline import review as review_rules
from freight_intel.pipeline.checkpoint import get_checkpointer
from freight_intel.pipeline.graph import (
    NoPendingReview, build_graph, pending_review, resume_document, review_thread_id, run_document,
)
from freight_intel.repositories import documents, reviews
from freight_intel.services import results
from freight_intel.storage import get_storage

log = logging.getLogger(__name__)


class DocumentNotFound(Exception):
    """No document with that id in this tenant (another tenant's document looks exactly the same)."""


class NotAwaitingReview(Exception):
    """The document is not waiting for a person: it is finished, still processing, or the review ended."""


class InvalidDecision(Exception):
    """The decision is malformed. The message is written for the person who sent it."""


@dataclass(frozen=True)
class ProcessOutcome:
    document_status: str  # processed | needs_review | failed
    awaiting_review: bool


@dataclass(frozen=True)
class ReviewOutcome:
    accepted: bool  # False: the decision could not be used and NOTHING was saved; see `question["error"]`
    document_status: str
    question: dict | None  # what the person must answer next; None when the review is over


class _NoLLM:
    """For graphs that only read or resume a review. If any model step ever ran, fail loudly instead of paying."""

    def extract(self, schema, system, user):
        raise RuntimeError("this graph is only for reading or resuming a review; it must not call the model")


def _review_graph(checkpointer):
    saver = get_checkpointer() if checkpointer is None else checkpointer
    return build_graph(_NoLLM(), checkpointer=saver, human_review=True)


def process_document(*, tenant_id: uuid.UUID, document_id: uuid.UUID, llm, checkpointer=None, storage=None) -> ProcessOutcome | None:
    """Read one uploaded document and store the outcome. Meant to run in the background.

    Returns None when someone else already claimed the document (nothing is done twice). Errors inside the
    pipeline never escape: the document is marked failed and logged, because no request is waiting to hear.
    """
    saver = get_checkpointer() if checkpointer is None else checkpointer
    files = get_storage() if storage is None else storage
    with tenant_session(tenant_id) as session:
        document = documents.get(session, document_id)
        if document is None:
            raise DocumentNotFound
        storage_key = document.storage_key
        if not documents.claim_for_processing(session, document_id):
            return None

    thread = review_thread_id(tenant_id, document_id)
    graph = build_graph(llm, checkpointer=saver, human_review=True)
    try:
        state = run_document(
            graph, str(files.path(storage_key)), thread_id=thread, tags=["api"],
            metadata={"tenant_id": str(tenant_id), "document_id": str(document_id)},
        )
        waiting = pending_review(graph, thread) is not None
        saved = results.save_pipeline_result(tenant_id=tenant_id, document_id=document_id, state=state)
    except Exception:
        log.exception("processing document %s failed", document_id)
        _mark_failed(tenant_id, document_id)
        return ProcessOutcome("failed", False)
    return ProcessOutcome(saved.document_status, waiting)


def _mark_failed(tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
    try:
        with tenant_session(tenant_id) as session:
            documents.set_status(session, document_id, "failed")
    except Exception:
        log.exception("could not mark document %s as failed", document_id)


def pending_question(*, tenant_id: uuid.UUID, document_id: uuid.UUID, checkpointer=None) -> dict | None:
    """The request a person has to answer for this document, or None if it is not waiting for anyone."""
    with tenant_session(tenant_id) as session:
        document = documents.get(session, document_id)
        if document is None:
            raise DocumentNotFound
        waiting = document.status == "needs_review"
    if not waiting:
        return None
    return pending_review(_review_graph(checkpointer), review_thread_id(tenant_id, document_id))


def submit_review(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID, document_id: uuid.UUID, decision: Mapping, checkpointer=None
) -> ReviewOutcome:
    """Give a paused document the answer of a logged-in person.

    Who decided is taken from the login (`user_id`), never from the request: a `reviewer` field sent by the
    client is overwritten. The document row is locked while this runs, so two people answering at the same
    time are handled one after the other, and the second is told the document is no longer waiting.
    """
    try:
        parsed = review_rules.parse_decision({**decision, "reviewer": str(user_id)})
    except ValueError as exc:
        raise InvalidDecision(str(exc)) from exc

    graph = _review_graph(checkpointer)
    thread = review_thread_id(tenant_id, document_id)
    with tenant_session(tenant_id) as session:
        document = documents.get_for_update(session, document_id)
        if document is None:
            raise DocumentNotFound
        if document.status != "needs_review":
            raise NotAwaitingReview
        try:
            state = resume_document(graph, thread, asdict(parsed))
        except NoPendingReview as exc:
            raise NotAwaitingReview from exc

        question = pending_review(graph, thread)
        if question is not None and "error" in question:
            return ReviewOutcome(False, "needs_review", question)  # unusable answer: it is asked again, nothing saved

        reviews.add(
            session, tenant_id=tenant_id, document_id=document_id, reviewer_id=user_id, action=parsed.action,
            note=parsed.note, corrected_data=parsed.extraction if parsed.action == "correct" else None,
        )
        if question is None:  # the review is over: store the final reading and status with the review itself
            document_status = results.apply_pipeline_result(
                session, tenant_id=tenant_id, document_id=document_id, state=state
            ).document_status
        else:  # a correction that still has errors: the person is asked again; the tables keep the last settled reading
            document_status = "needs_review"
    return ReviewOutcome(True, document_status, question)
