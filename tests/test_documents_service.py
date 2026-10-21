"""The documents service against the real Postgres and LangGraph (start the database with `docker compose up -d`).

Documents are uploaded and processed exactly as the API will do it, then read back through get_document.
"""
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from freight_intel.config import get_settings  # noqa: E402
from freight_intel.repositories import documents  # noqa: E402
from freight_intel.services import documents as service  # noqa: E402
from freight_intel.services import processing  # noqa: E402
from freight_intel.services.uploads import check_upload  # noqa: E402
from freight_intel.storage import LocalStorage  # noqa: E402
from freight_intel.synth.oracle import OracleLLM  # noqa: E402
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402

CASES = build_dataset(45, 42)
OVERCHARGE = next(c for c in CASES if c.error_kind == "OVERCHARGE" and c.invoice.quote_ref)
WRONG_TOTAL = next(c for c in CASES if c.error_kind == ARITHMETIC_ERROR)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return out


@pytest.fixture(scope="module")
def owner():
    engine = create_engine(get_settings().owner_url)
    yield engine
    engine.dispose()


@pytest.fixture
def world(owner, dataset, tmp_path):
    a, b, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with owner.begin() as conn:
        for tenant_id, name in ((a, "Tenant A"), (b, "Tenant B")):
            conn.execute(text("INSERT INTO tenants (id, name) VALUES (:id, :name)"), {"id": tenant_id, "name": name})
        conn.execute(
            text("INSERT INTO users (id, tenant_id, email, password_hash) VALUES (:id, :t, :email, 'x')"),
            {"id": user, "t": a, "email": f"{user}@example.com"},
        )
    yield SimpleNamespace(a=a, b=b, user=user, files=dataset, storage=LocalStorage(tmp_path / "storage"), saver=MemorySaver())
    with owner.begin() as conn:
        params = {"a": a, "b": b}
        conn.execute(text("DELETE FROM documents WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM users WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), params)


def upload(world, case, kind, *, tenant=None):
    source = world.files / "cases" / case.case_id / f"{kind}.{getattr(case, kind + '_format')}"
    checked = check_upload(source.name, source.read_bytes(), max_bytes=10_000_000)
    return service.register_upload(tenant_id=tenant or world.a, user_id=world.user, upload=checked, storage=world.storage)


def process(world, document_id):
    return processing.process_document(
        tenant_id=world.a, document_id=document_id, llm=OracleLLM(CASES), checkpointer=world.saver, storage=world.storage
    )


def detail(world, document_id, *, tenant=None):
    return service.get_document(tenant_id=tenant or world.a, document_id=document_id, checkpointer=world.saver)


def test_an_upload_is_stored_and_registered(world):
    doc = upload(world, OVERCHARGE, "invoice")
    view = detail(world, doc)
    assert view["status"] == "uploaded" and view["filename"].startswith("invoice")
    assert view["extraction"] is None and view["reconciliation"] is None and view["reviews"] == []
    assert view["pending_review"] is None
    (stored,) = [p for p in world.storage.root.rglob("*") if p.is_file()]
    assert stored.parent.name == str(world.a) and stored.stem == str(doc)  # <tenant>/<document>.<ext>


def test_a_failed_registration_leaves_no_file_behind(world, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(documents, "create", broken)
    with pytest.raises(RuntimeError):
        upload(world, OVERCHARGE, "invoice")
    assert [p for p in world.storage.root.rglob("*") if p.is_file()] == []


def test_listing_is_newest_first_pageable_and_limited_to_the_tenant(world):
    first, second, third = (upload(world, OVERCHARGE, "invoice") for _ in range(3))
    upload(world, OVERCHARGE, "invoice", tenant=world.b)  # a document of another tenant
    listed = service.list_documents(tenant_id=world.a, limit=10)
    assert [d["id"] for d in listed] == [third, second, first]
    assert [d["id"] for d in service.list_documents(tenant_id=world.a, limit=1, offset=1)] == [second]


def test_the_detail_of_a_document_waiting_for_review(world):
    doc = upload(world, WRONG_TOTAL, "invoice")
    process(world, doc)
    view = detail(world, doc)
    assert view["status"] == "needs_review" and view["extraction"]["status"] == "needs_review"
    assert view["extraction"]["charges"] and any(i["code"] == "TOTAL_MISMATCH" for i in view["extraction"]["issues"])
    assert any(i["code"] == "TOTAL_MISMATCH" for i in view["pending_review"]["issues"])


def test_reconciling_an_invoice_with_its_quote_shows_the_findings(world):
    quote = upload(world, OVERCHARGE, "quote")
    invoice = upload(world, OVERCHARGE, "invoice")
    process(world, quote)
    process(world, invoice)
    outcome = service.reconcile_document(tenant_id=world.a, document_id=invoice)
    assert outcome.status == "reconciled" and outcome.discrepancy_count == len(OVERCHARGE.expected)
    rec = detail(world, invoice)["reconciliation"]
    assert rec["quote_document_id"] == quote and rec["status"] == "has_discrepancies"
    assert sorted((d["type"], d["charge_code"], d["variance_minor"]) for d in rec["discrepancies"]) == sorted(
        (e.type, e.charge_code, e.variance_minor) for e in OVERCHARGE.expected
    )
    assert detail(world, quote)["reconciliation"] is None  # a quote has no reconciliation of its own


def test_reconcile_explains_why_a_document_cannot_be_reconciled(world):
    quote = upload(world, OVERCHARGE, "quote")
    unread = upload(world, OVERCHARGE, "invoice")
    waiting = upload(world, WRONG_TOTAL, "invoice")
    process(world, quote)
    process(world, waiting)
    for document in (quote, unread):
        with pytest.raises(service.NotReconcilable, match="has been read"):
            service.reconcile_document(tenant_id=world.a, document_id=document)
    with pytest.raises(service.NotReconcilable, match="waiting for a review"):
        service.reconcile_document(tenant_id=world.a, document_id=waiting)


def test_another_tenant_cannot_read_or_reconcile_the_document(world):
    doc = upload(world, OVERCHARGE, "invoice")
    process(world, doc)
    with pytest.raises(service.DocumentNotFound):
        detail(world, doc, tenant=world.b)
    with pytest.raises(service.DocumentNotFound):
        service.reconcile_document(tenant_id=world.b, document_id=doc)
