"""The processing service against the real Postgres and the real LangGraph (start the database with
`docker compose up -d`). Checkpoints live in memory here; test_checkpoint.py proves the Postgres ones survive a restart.

The invoice used for reviews is a generated one whose PRINTED total really is wrong, so the pipeline
cannot settle it and a person has to.
"""
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from freight_intel.config import get_settings  # noqa: E402
from freight_intel.db import tenant_session  # noqa: E402
from freight_intel.pipeline.money import format_minor, parse_money  # noqa: E402
from freight_intel.repositories import documents  # noqa: E402
from freight_intel.services import processing  # noqa: E402
from freight_intel.storage import LocalStorage  # noqa: E402
from freight_intel.synth.oracle import OracleLLM, perfect_extraction  # noqa: E402
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402

CASES = build_dataset(45, 42)
WRONG_TOTAL = next(c for c in CASES if c.error_kind == ARITHMETIC_ERROR)
CLEAN = next(c for c in CASES if c.error_kind == "CLEAN")

PERFECT = perfect_extraction(WRONG_TOTAL, "invoice")  # what the model reads: the lines do not add up to the total
LINE_SUM = sum(parse_money(c.amount_text) for c in PERFECT.charges)
FIXED = PERFECT.model_copy(update={"total_text": format_minor(LINE_SUM)})  # a reviewer fixes the printed total
STILL_WRONG = PERFECT.model_copy(  # a reviewer changes a line, but the lines still do not add up
    update={"charges": [PERFECT.charges[0].model_copy(update={"amount_text": "2.00"}), *PERFECT.charges[1:]]}
)
NOTE = "the printed total is wrong on the paper"


def approve(**extra):
    return {"action": "approve", "note": NOTE, **extra}


def correct(extraction):
    return {"action": "correct", "extraction": extraction.model_dump(mode="json")}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return out


@pytest.fixture(scope="module")
def owner():
    engine = create_engine(get_settings().owner_url)  # bypasses RLS: seeding and checking only
    yield engine
    engine.dispose()


@pytest.fixture
def world(owner, dataset, tmp_path):
    """Two tenants, a reviewer in tenant A, a storage folder and an in-memory checkpoint store."""
    a, b, reviewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with owner.begin() as conn:
        for tenant_id, name in ((a, "Tenant A"), (b, "Tenant B")):
            conn.execute(text("INSERT INTO tenants (id, name) VALUES (:id, :name)"), {"id": tenant_id, "name": name})
        conn.execute(
            text("INSERT INTO users (id, tenant_id, email, password_hash) VALUES (:id, :t, :email, 'x')"),
            {"id": reviewer, "t": a, "email": f"{reviewer}@example.com"},
        )
    yield SimpleNamespace(a=a, b=b, reviewer=reviewer, files=dataset, storage=LocalStorage(tmp_path / "storage"), saver=MemorySaver())
    with owner.begin() as conn:  # documents first: extractions, charges and reviews cascade from them
        params = {"a": a, "b": b}
        conn.execute(text("DELETE FROM documents WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM users WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), params)


def upload(world, case, *, tenant=None):
    """What the upload route will do: put the file in storage and add the document row."""
    tenant = tenant or world.a
    source = world.files / "cases" / case.case_id / f"invoice.{case.invoice_format}"
    key = LocalStorage.key_for(tenant, uuid.uuid4(), source.suffix)
    world.storage.save(key, source.read_bytes())
    with tenant_session(tenant) as session:
        return documents.create(session, tenant_id=tenant, filename=source.name, storage_key=key).id


def process(world, document_id, *, tenant=None, llm=None):
    return processing.process_document(
        tenant_id=tenant or world.a, document_id=document_id, llm=llm or OracleLLM(CASES),
        checkpointer=world.saver, storage=world.storage,
    )


def review(world, document_id, decision, *, tenant=None):
    return processing.submit_review(
        tenant_id=tenant or world.a, user_id=world.reviewer, document_id=document_id,
        decision=decision, checkpointer=world.saver,
    )


def one(owner, sql, **params):
    with owner.connect() as conn:
        return conn.execute(text(sql), params).mappings().one_or_none()


def doc_status(owner, document_id):
    return one(owner, "SELECT status FROM documents WHERE id = :id", id=document_id)["status"]


def extraction_row(owner, document_id):
    return one(owner, "SELECT status, total_minor FROM extractions WHERE document_id = :id", id=document_id)


def first_charge(owner, document_id):
    return one(
        owner,
        "SELECT c.amount_minor FROM charges c JOIN extractions e ON e.id = c.extraction_id "
        "WHERE e.document_id = :id AND c.position = 0", id=document_id,
    )["amount_minor"]


def review_rows(owner, document_id):
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT action, reviewer_id, corrected_data FROM reviews WHERE document_id = :id ORDER BY created_at"),
            {"id": document_id},
        ).mappings().all()


# --- processing ---------------------------------------------------------------------------------

def test_a_clean_document_is_processed_without_a_person(world, owner):
    doc = upload(world, CLEAN)
    outcome = process(world, doc)
    assert outcome.document_status == "processed" and outcome.awaiting_review is False
    assert doc_status(owner, doc) == "processed" and extraction_row(owner, doc)["status"] == "ok"
    assert processing.pending_question(tenant_id=world.a, document_id=doc, checkpointer=world.saver) is None


def test_a_document_the_pipeline_cannot_settle_waits_for_a_person(world, owner):
    doc = upload(world, WRONG_TOTAL)
    outcome = process(world, doc)
    assert outcome.document_status == "needs_review" and outcome.awaiting_review is True
    assert extraction_row(owner, doc)["status"] == "needs_review"  # the reading is stored while it waits
    question = processing.pending_question(tenant_id=world.a, document_id=doc, checkpointer=world.saver)
    assert any(issue["code"] == "TOTAL_MISMATCH" for issue in question["issues"])


def test_processing_the_same_document_twice_does_nothing_the_second_time(world, owner):
    doc = upload(world, CLEAN)
    assert process(world, doc) is not None
    assert process(world, doc) is None  # already claimed
    assert doc_status(owner, doc) == "processed"


def test_a_crash_inside_the_pipeline_marks_the_document_failed(world, owner):
    class BrokenLLM:
        def extract(self, schema, system, user):
            raise RuntimeError("the model is down")

    doc = upload(world, CLEAN)
    outcome = process(world, doc, llm=BrokenLLM())
    assert outcome.document_status == "failed"
    assert doc_status(owner, doc) == "failed" and extraction_row(owner, doc) is None


# --- reviewing ----------------------------------------------------------------------------------

def test_approving_finishes_the_review_and_keeps_the_record(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    outcome = review(world, doc, approve())
    assert outcome.accepted and outcome.document_status == "processed" and outcome.question is None
    assert doc_status(owner, doc) == "processed" and extraction_row(owner, doc)["status"] == "reviewed"
    (row,) = review_rows(owner, doc)
    assert row["action"] == "approve" and row["reviewer_id"] == world.reviewer and row["corrected_data"] is None


def test_the_reviewer_is_the_logged_in_user_whatever_the_request_claims(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    review(world, doc, approve(reviewer="someone.else@example.com"))
    assert review_rows(owner, doc)[0]["reviewer_id"] == world.reviewer


def test_an_approval_over_errors_without_a_note_is_refused_and_saves_nothing(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    outcome = review(world, doc, {"action": "approve"})
    assert outcome.accepted is False and "needs a note" in outcome.question["error"]
    assert doc_status(owner, doc) == "needs_review" and review_rows(owner, doc) == []
    assert review(world, doc, approve()).accepted  # the person tries again with a note


def test_a_correction_that_passes_the_checks_finishes_the_review(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    outcome = review(world, doc, correct(FIXED))
    assert outcome.accepted and outcome.document_status == "processed"
    assert extraction_row(owner, doc)["status"] == "reviewed" and extraction_row(owner, doc)["total_minor"] == LINE_SUM
    (row,) = review_rows(owner, doc)
    assert row["action"] == "correct" and row["corrected_data"]["total_text"] == format_minor(LINE_SUM)


def test_a_correction_in_an_earlier_round_is_what_gets_approved(world, owner):
    """Round 1 changes a line but the document still has an error; round 2 approves. The corrected line is saved."""
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    original = first_charge(owner, doc)

    first = review(world, doc, correct(STILL_WRONG))
    assert first.accepted and first.document_status == "needs_review"
    assert first.question["extraction"]["charges"][0]["amount_text"] == "2.00"  # the person is shown their correction
    assert first_charge(owner, doc) == original  # the tables keep the last settled reading until the review ends

    second = review(world, doc, approve())
    assert second.accepted and second.document_status == "processed"
    assert first_charge(owner, doc) == 200  # not the model's original
    assert [r["action"] for r in review_rows(owner, doc)] == ["correct", "approve"]


def test_rejecting_marks_the_document_rejected(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    outcome = review(world, doc, {"action": "reject", "note": "not our shipment"})
    assert outcome.accepted and outcome.document_status == "rejected"
    assert doc_status(owner, doc) == "rejected"
    assert extraction_row(owner, doc)["status"] == "needs_review"  # the rejected reading stays on record
    assert review_rows(owner, doc)[0]["action"] == "reject"


def test_after_three_corrections_that_still_fail_the_review_ends_unfinished(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    outcomes = [review(world, doc, correct(STILL_WRONG)) for _ in range(3)]
    assert outcomes[-1].question is None and outcomes[-1].document_status == "needs_review"
    with pytest.raises(processing.NotAwaitingReview):  # nobody is being asked any more
        review(world, doc, approve())


def test_a_finished_document_cannot_be_reviewed_again(world):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    review(world, doc, approve())
    with pytest.raises(processing.NotAwaitingReview):
        review(world, doc, approve())


def test_a_document_that_never_needed_review_cannot_be_reviewed(world):
    doc = upload(world, CLEAN)
    process(world, doc)
    with pytest.raises(processing.NotAwaitingReview):
        review(world, doc, approve())


def test_a_malformed_decision_is_reported_before_anything_runs(world):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    with pytest.raises(processing.InvalidDecision, match="action must be one of"):
        review(world, doc, {"action": "maybe"})


def test_another_tenant_cannot_process_read_or_review_the_document(world, owner):
    doc = upload(world, WRONG_TOTAL)
    process(world, doc)
    with pytest.raises(processing.DocumentNotFound):
        review(world, doc, approve(), tenant=world.b)
    with pytest.raises(processing.DocumentNotFound):
        processing.pending_question(tenant_id=world.b, document_id=doc, checkpointer=world.saver)
    with pytest.raises(processing.DocumentNotFound):
        process(world, doc, tenant=world.b)
    assert doc_status(owner, doc) == "needs_review" and review_rows(owner, doc) == []
