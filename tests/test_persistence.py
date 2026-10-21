"""The service layer against the real Postgres (start it with `docker compose up -d`).

These tests save pipeline results through freight_intel.services.results, exactly as the API
will, then look at what ended up in the database. They check the rules the migration
promised: one extraction per document, one reconciliation per invoice, all-or-nothing saves,
no cross-tenant links, and tenants that cannot see each other's rows.
"""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from freight_intel.config import get_settings
from freight_intel.db import tenant_session
from freight_intel.models import Charge, Document
from freight_intel.pipeline.reconcile import reconcile
from freight_intel.pipeline.validation import validate
from freight_intel.repositories import documents, extractions, reconciliations, reviews
from freight_intel.services import results
from freight_intel.synth.oracle import perfect_extraction
from freight_intel.synth.scenario import build_dataset

CASES = build_dataset(45, 42)
OVERCHARGE = next(c for c in CASES if c.error_kind == "OVERCHARGE" and c.invoice.quote_ref)
CLEAN = next(c for c in CASES if c.error_kind == "CLEAN")


def state_for(case, kind):
    """What the pipeline would hand over after reading `case`'s document (perfect extraction)."""
    extraction = perfect_extraction(case, kind)
    result = validate(kind, extraction)
    return {"doc_type": kind, "extraction": extraction, "typed": result.typed, "issues": result.issues,
            "status": "ok" if result.ok else "needs_review"}


@pytest.fixture(scope="module")
def owner():
    engine = create_engine(get_settings().owner_url)  # bypasses RLS: seeding and checking only
    yield engine
    engine.dispose()


@pytest.fixture
def world(owner):
    """Two tenants. Tenant A has two documents (a quote and an invoice), tenant B has one."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with owner.begin() as conn:
        for tenant_id, name in ((a, "Tenant A"), (b, "Tenant B")):
            conn.execute(text("INSERT INTO tenants (id, name) VALUES (:id, :name)"), {"id": tenant_id, "name": name})
    ids = {}
    for key, tenant_id in (("a_quote", a), ("a_invoice", a), ("b_doc", b)):
        with tenant_session(tenant_id) as session:
            ids[key] = documents.create(
                session, tenant_id=tenant_id, filename=f"{key}.pdf", storage_key=f"test/{uuid.uuid4()}"
            ).id
    yield SimpleNamespace(a=a, b=b, **ids)
    with owner.begin() as conn:  # documents first: extractions, charges and reconciliations cascade from them
        params = {"a": a, "b": b}
        conn.execute(text("DELETE FROM documents WHERE tenant_id IN (:a, :b)"), params)  # reviews cascade with them
        conn.execute(text("DELETE FROM users WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), params)


def count(owner, table, **where):
    clause = " AND ".join(f"{column} = :{column}" for column in where) or "true"
    with owner.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {clause}"), where).scalar_one()


def save(world, document, case, kind, *, tenant=None):
    return results.save_pipeline_result(
        tenant_id=tenant or world.a, document_id=getattr(world, document), state=state_for(case, kind)
    )


def save_pair(world, case):
    quote = save(world, "a_quote", case, "quote")
    invoice = save(world, "a_invoice", case, "invoice")
    return quote, invoice


def test_saved_extraction_reads_back_field_for_field(world):
    state = state_for(OVERCHARGE, "quote")
    saved = results.save_pipeline_result(tenant_id=world.a, document_id=world.a_quote, state=state)
    typed = state["typed"]
    with tenant_session(world.a) as session:
        row = extractions.get(session, saved.extraction_id)
        charges = extractions.get_charges(session, row.id)
        document = session.get(Document, world.a_quote)
        assert (row.doc_type, row.reference, row.currency) == ("quote", typed.reference, typed.currency)
        assert (row.doc_date, row.valid_until, row.total_minor) == (typed.date, typed.valid_until, typed.total_minor)
        assert (row.origin, row.destination, row.equipment) == (typed.origin, typed.destination, typed.equipment)
        assert row.data == state["extraction"].model_dump(mode="json")  # the raw reading, kept for audit
        assert [(c.raw_label, c.amount_minor, c.canonical_code, c.known) for c in charges] == [
            (c.label, c.amount_minor, c.code, c.known) for c in typed.charges
        ]
        assert document.doc_type == "quote"
        assert document.status == ("processed" if state["status"] == "ok" else "needs_review")


def test_saving_the_same_document_twice_replaces_instead_of_duplicating(world, owner):
    first = save(world, "a_quote", OVERCHARGE, "quote")
    second = save(world, "a_quote", OVERCHARGE, "quote")
    assert second.extraction_id != first.extraction_id
    assert count(owner, "extractions", document_id=world.a_quote) == 1
    assert count(owner, "charges", extraction_id=first.extraction_id) == 0  # the old charges went with it
    assert count(owner, "charges", extraction_id=second.extraction_id) == len(
        state_for(OVERCHARGE, "quote")["typed"].charges
    )


def test_a_failed_rerun_changes_the_status_but_keeps_the_earlier_extraction(world, owner):
    first = save(world, "a_quote", OVERCHARGE, "quote")
    failed = results.save_pipeline_result(
        tenant_id=world.a, document_id=world.a_quote, state={"doc_type": "quote", "status": "failed", "error": "boom"}
    )
    assert failed.document_status == "failed" and failed.extraction_id is None
    with tenant_session(world.a) as session:
        assert session.get(Document, world.a_quote).status == "failed"
        assert extractions.get_for_document(session, world.a_quote).id == first.extraction_id


def test_reconcile_finds_the_overcharge_and_stores_it(world):
    quote, invoice = save_pair(world, OVERCHARGE)
    outcome = results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert outcome.status == "reconciled"
    assert outcome.discrepancy_count == len(OVERCHARGE.expected)
    expected_total = reconcile(state_for(OVERCHARGE, "quote")["typed"], state_for(OVERCHARGE, "invoice")["typed"])
    with tenant_session(world.a) as session:
        rec = reconciliations.get_for_invoice(session, invoice.extraction_id)
        stored = reconciliations.get_discrepancies(session, rec.id)
        assert (rec.quote_extraction_id, rec.status) == (quote.extraction_id, "has_discrepancies")
        assert rec.total_variance_minor == expected_total.total_variance_minor
        assert sorted((d.type, d.charge_code, d.variance_minor) for d in stored) == sorted(
            (e.type, e.charge_code, e.variance_minor) for e in OVERCHARGE.expected
        )


def test_a_clean_invoice_is_stored_as_clean_with_no_discrepancies(world, owner):
    _, invoice = save_pair(world, CLEAN)
    outcome = results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert (outcome.status, outcome.discrepancy_count) == ("reconciled", 0)
    with tenant_session(world.a) as session:
        assert reconciliations.get_for_invoice(session, invoice.extraction_id).status == "clean"
    assert count(owner, "discrepancies", tenant_id=world.a) == 0


def test_reconciling_twice_replaces_the_earlier_result(world, owner):
    _, invoice = save_pair(world, OVERCHARGE)
    for _ in range(2):
        results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert count(owner, "reconciliations", invoice_extraction_id=invoice.extraction_id) == 1
    assert count(owner, "discrepancies", tenant_id=world.a) == len(OVERCHARGE.expected)  # not doubled


def test_an_invoice_with_no_stored_quote_stores_no_reconciliation(world, owner):
    invoice = save(world, "a_invoice", OVERCHARGE, "invoice")
    outcome = results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert outcome.status in ("reference_not_found", "no_candidate") and outcome.reconciliation_id is None
    assert count(owner, "reconciliations", tenant_id=world.a) == 0


def test_reconcile_refuses_unknown_ids_and_quotes(world):
    quote, _ = save_pair(world, OVERCHARGE)
    with pytest.raises(results.InvoiceNotFound):
        results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=uuid.uuid4())
    with pytest.raises(results.InvoiceNotFound):  # a real id, but of a quote
        results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=quote.extraction_id)


def test_another_tenant_cannot_see_or_reconcile_these_rows(world):
    quote, invoice = save_pair(world, OVERCHARGE)
    results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    with tenant_session(world.b) as session:
        assert extractions.get(session, invoice.extraction_id) is None
        assert extractions.list_by_type(session, "quote") == []
        assert reconciliations.get_for_invoice(session, invoice.extraction_id) is None
    with pytest.raises(results.InvoiceNotFound):
        results.reconcile_invoice(tenant_id=world.b, invoice_extraction_id=invoice.extraction_id)


def test_cannot_save_a_result_onto_another_tenants_document(world):
    """Row-level security alone would allow this insert (tenant B inserting as tenant B).
    The composite foreign key (tenant_id, document_id) is what refuses it."""
    with pytest.raises(IntegrityError, match="extractions_document_fk"):
        results.save_pipeline_result(tenant_id=world.b, document_id=world.a_quote, state=state_for(OVERCHARGE, "quote"))
    with tenant_session(world.a) as session:
        assert extractions.get_for_document(session, world.a_quote) is None


def test_cannot_attach_a_charge_to_another_tenants_extraction(world):
    quote = save(world, "a_quote", OVERCHARGE, "quote")
    with pytest.raises(IntegrityError, match="charges_extraction_fk"):
        with tenant_session(world.b) as session:
            session.add(Charge(tenant_id=world.b, extraction_id=quote.extraction_id, position=99,
                               canonical_code="OTHER", raw_label="planted", amount_minor=1, known=False))
            session.flush()


def test_a_failure_part_way_through_a_save_leaves_nothing_behind(world, owner, monkeypatch):
    """The extraction is inserted before the document status is updated. If the second step
    fails, the first must be rolled back with it."""
    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash after the extraction was inserted")

    monkeypatch.setattr(results.documents, "record_outcome", boom)
    with pytest.raises(RuntimeError):
        save(world, "a_quote", OVERCHARGE, "quote")
    assert count(owner, "extractions", document_id=world.a_quote) == 0
    assert count(owner, "charges", tenant_id=world.a) == 0


def test_deleting_an_extraction_removes_its_charges_and_reconciliation(world, owner):
    quote, invoice = save_pair(world, OVERCHARGE)
    results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM extractions WHERE id = :id"), {"id": quote.extraction_id})
    assert count(owner, "charges", extraction_id=quote.extraction_id) == 0
    assert count(owner, "reconciliations", tenant_id=world.a) == 0  # it pointed at the deleted quote
    assert count(owner, "discrepancies", tenant_id=world.a) == 0
    assert count(owner, "extractions", id=invoice.extraction_id) == 1  # the invoice itself stays


def make_user(owner, tenant_id):
    user_id = uuid.uuid4()
    with owner.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, tenant_id, email, password_hash) VALUES (:id, :tenant, :email, 'x')"),
            {"id": user_id, "tenant": tenant_id, "email": f"{user_id}@example.com"},
        )
    return user_id


def test_a_document_can_be_claimed_for_processing_only_once(world):
    with tenant_session(world.a) as session:
        assert documents.claim_for_processing(session, world.a_quote) is True
    with tenant_session(world.a) as session:
        assert documents.claim_for_processing(session, world.a_quote) is False  # already taken
        assert documents.get(session, world.a_quote).status == "processing"


def test_another_tenant_cannot_read_or_claim_a_document(world):
    with tenant_session(world.b) as session:
        assert documents.get(session, world.a_quote) is None
        assert documents.claim_for_processing(session, world.a_quote) is False
    with tenant_session(world.a) as session:
        assert documents.get(session, world.a_quote).status == "uploaded"  # untouched


def test_listing_shows_only_the_callers_documents(world):
    with tenant_session(world.a) as session:
        ids = {d.id for d in documents.list_recent(session, limit=10)}  # read inside: rows detach at commit
        assert len(documents.list_recent(session, limit=1)) == 1
    assert ids == {world.a_quote, world.a_invoice}


def test_a_review_and_the_result_it_caused_are_saved_together_or_not_at_all(world, owner):
    reviewer = make_user(owner, world.a)
    state = state_for(CLEAN, "invoice") | {"status": "reviewed"}
    with tenant_session(world.a) as session:
        results.apply_pipeline_result(session, tenant_id=world.a, document_id=world.a_invoice, state=state)
        reviews.add(session, tenant_id=world.a, document_id=world.a_invoice, reviewer_id=reviewer,
                    action="approve", note="checked against the paper copy")
    with tenant_session(world.a) as session:
        assert documents.get(session, world.a_invoice).status == "processed"
        assert extractions.get_for_document(session, world.a_invoice).status == "reviewed"
        (review,) = reviews.list_for_document(session, world.a_invoice)
        assert review.action == "approve" and review.reviewer_id == reviewer

    with pytest.raises(RuntimeError):  # something fails after the review was added: it must not stay
        with tenant_session(world.a) as session:
            reviews.add(session, tenant_id=world.a, document_id=world.a_invoice, reviewer_id=reviewer, action="reject")
            raise RuntimeError("boom")
    assert count(owner, "reviews", document_id=world.a_invoice) == 1


def test_a_review_cannot_name_another_tenants_user_as_the_reviewer(world, owner):
    outsider = make_user(owner, world.b)
    with pytest.raises(IntegrityError):
        with tenant_session(world.a) as session:
            reviews.add(session, tenant_id=world.a, document_id=world.a_invoice, reviewer_id=outsider, action="approve")


def test_a_correction_must_carry_its_corrected_data(world, owner):
    reviewer = make_user(owner, world.a)
    with pytest.raises(IntegrityError):
        with tenant_session(world.a) as session:
            reviews.add(session, tenant_id=world.a, document_id=world.a_invoice, reviewer_id=reviewer, action="correct")


def test_reconcile_refuses_an_invoice_nobody_has_settled(world):
    save(world, "a_quote", OVERCHARGE, "quote")
    waiting = results.save_pipeline_result(
        tenant_id=world.a, document_id=world.a_invoice, state=state_for(OVERCHARGE, "invoice") | {"status": "needs_review"}
    )
    with pytest.raises(results.NotSettled):
        results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=waiting.extraction_id)


def test_a_quote_nobody_has_settled_is_not_used_until_a_person_settles_it(world):
    invoice = save(world, "a_invoice", OVERCHARGE, "invoice")
    quote_state = state_for(OVERCHARGE, "quote")
    results.save_pipeline_result(tenant_id=world.a, document_id=world.a_quote, state=quote_state | {"status": "needs_review"})
    outcome = results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert outcome.status in ("reference_not_found", "no_candidate") and outcome.reconciliation_id is None

    results.save_pipeline_result(tenant_id=world.a, document_id=world.a_quote, state=quote_state | {"status": "reviewed"})
    outcome = results.reconcile_invoice(tenant_id=world.a, invoice_extraction_id=invoice.extraction_id)
    assert outcome.status == "reconciled"
