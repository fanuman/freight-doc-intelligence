"""The graph pausing for a person and resuming. Needs the real langgraph library; skipped where it isn't installed.

Uses MemorySaver (a checkpointer that lives in this process's memory), which is right for tests. The service
will use a database-backed one so a paused review survives a restart.
"""
import uuid

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from freight_intel.pipeline.graph import (  # noqa: E402
    NoPendingReview, build_graph, pending_review, resume_document, review_thread_id, run_document,
)
from freight_intel.synth.oracle import OracleLLM  # noqa: E402
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402

CASES = build_dataset(45, 42)
WRONG_TOTAL = next(c for c in CASES if c.error_kind == ARITHMETIC_ERROR)  # the printed total really is wrong
CLEAN = next(c for c in CASES if c.error_kind == "CLEAN")
APPROVE = {"action": "approve", "reviewer": "ana@example.com", "note": "the printed total is wrong on the paper"}


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("files")
    write_dataset(45, 42, out)
    return out


def invoice_path(files, case):
    return str(files / "cases" / case.case_id / f"invoice.{case.invoice_format}")


@pytest.fixture
def graph():
    return build_graph(OracleLLM(CASES), checkpointer=MemorySaver(), human_review=True)


def start(graph, files, case):
    thread = review_thread_id(uuid.uuid4(), uuid.uuid4())
    state = run_document(graph, invoice_path(files, case), thread_id=thread)
    return thread, state


def test_review_needs_a_checkpointer():
    with pytest.raises(ValueError, match="checkpointer"):
        build_graph(OracleLLM([]), human_review=True)


def test_a_graph_without_review_behaves_as_before(files):
    """The evaluation builds graphs this way: no checkpointer, no pause, needs_review is just the final status."""
    state = run_document(build_graph(OracleLLM(CASES)), invoice_path(files, WRONG_TOTAL))
    assert state["status"] == "needs_review"


def test_a_document_with_a_wrong_total_pauses_for_a_person(graph, files):
    thread, state = start(graph, files, WRONG_TOTAL)
    request = pending_review(graph, thread)
    assert request is not None and request["doc_type"] == "invoice"
    assert any(issue["code"] == "TOTAL_MISMATCH" for issue in request["issues"])
    assert state["status"] == "needs_review"


def test_a_clean_document_does_not_pause(graph, files):
    thread, state = start(graph, files, CLEAN)
    assert pending_review(graph, thread) is None and state["status"] == "ok"


def test_approval_finishes_the_run_and_records_who_decided(graph, files):
    thread, _ = start(graph, files, WRONG_TOTAL)
    final = resume_document(graph, thread, APPROVE)
    assert final["status"] == "reviewed"
    assert final["review"]["reviewer"] == "ana@example.com"
    assert any(issue.code == "TOTAL_MISMATCH" for issue in final["issues"])  # the finding is still on record
    assert pending_review(graph, thread) is None


def test_an_unusable_answer_makes_the_graph_ask_again(graph, files):
    thread, _ = start(graph, files, WRONG_TOTAL)
    resume_document(graph, thread, {"action": "maybe"})
    assert "action must be" in pending_review(graph, thread)["error"]  # still waiting, now saying why
    final = resume_document(graph, thread, {"action": "reject", "reviewer": "ana@example.com"})
    assert final["status"] == "rejected"


def test_cannot_answer_a_document_that_is_not_waiting(graph, files):
    thread, _ = start(graph, files, CLEAN)
    with pytest.raises(NoPendingReview):
        resume_document(graph, thread, APPROVE)
    with pytest.raises(NoPendingReview):
        resume_document(graph, "no-such-thread", APPROVE)


def test_two_waiting_documents_are_independent(graph, files):
    first, _ = start(graph, files, WRONG_TOTAL)
    second, _ = start(graph, files, WRONG_TOTAL)
    resume_document(graph, first, APPROVE)
    assert pending_review(graph, first) is None
    assert pending_review(graph, second) is not None


def test_the_thread_name_includes_the_tenant():
    tenant_a, tenant_b, document = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert review_thread_id(tenant_a, document) != review_thread_id(tenant_b, document)
    assert str(tenant_a) in review_thread_id(tenant_a, document)
