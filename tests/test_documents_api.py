"""The documents endpoints through the real HTTP layer, the real Postgres and the real LangGraph.

No OpenAI calls: the model client is replaced by OracleLLM (it looks answers up in the generated dataset), the
checkpoint store by an in-memory one, and the storage folder by a temporary one. TestClient runs background
tasks before it returns, so the result of an upload can be read straight afterwards.
"""
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph")

from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from freight_intel.api.deps import get_llm, get_saver  # noqa: E402
from freight_intel.api.main import app  # noqa: E402
from freight_intel.config import get_settings  # noqa: E402
from freight_intel.pipeline.money import format_minor, parse_money  # noqa: E402
from freight_intel.storage import LocalStorage, get_storage  # noqa: E402
from freight_intel.synth.oracle import OracleLLM, perfect_extraction  # noqa: E402
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402

PASSWORD = "correct-horse-battery"
CASES = build_dataset(45, 42)
CLEAN = next(c for c in CASES if c.error_kind == "CLEAN")
OVERCHARGE = next(c for c in CASES if c.error_kind == "OVERCHARGE" and c.invoice.quote_ref)
WRONG_TOTAL = next(c for c in CASES if c.error_kind == ARITHMETIC_ERROR)

PERFECT = perfect_extraction(WRONG_TOTAL, "invoice")
LINE_SUM = sum(parse_money(c.amount_text) for c in PERFECT.charges)
FIXED = PERFECT.model_copy(update={"total_text": format_minor(LINE_SUM)})
NOTE = "the printed total is wrong on the paper"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def owner():
    engine = create_engine(get_settings().owner_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return out


@pytest.fixture
def api(client, dataset, tmp_path):
    """The client with the model, the checkpoint store and the storage folder replaced by test versions."""
    saver, storage = MemorySaver(), LocalStorage(tmp_path / "storage")
    app.dependency_overrides.update({
        get_llm: lambda: OracleLLM(CASES), get_saver: lambda: saver, get_storage: lambda: storage,
    })
    yield SimpleNamespace(client=client, files=dataset, storage=storage)
    app.dependency_overrides.clear()


@pytest.fixture
def signup(client, owner):
    """Creates companies through the real sign-up endpoint and deletes everything they own afterwards."""
    companies = []

    def make() -> dict:
        company = f"pytest-docs-{uuid.uuid4().hex[:8]}"
        companies.append(company)
        response = client.post("/auth/register", json={
            "company_name": company, "email": f"pytest-{uuid.uuid4().hex[:12]}@example.com", "password": PASSWORD,
        })
        assert response.status_code == 201
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    yield make
    with owner.begin() as conn:
        tenants = [r.id for r in conn.execute(text("SELECT id FROM tenants WHERE name = ANY(:n)"), {"n": companies})]
        conn.execute(text("DELETE FROM documents WHERE tenant_id = ANY(:t)"), {"t": tenants})  # results cascade
        conn.execute(text("DELETE FROM users WHERE tenant_id = ANY(:t)"), {"t": tenants})
        conn.execute(text("DELETE FROM tenants WHERE id = ANY(:t)"), {"t": tenants})


def post_file(api, headers, name, data):
    return api.client.post("/documents", files={"file": (name, data, "application/octet-stream")}, headers=headers)


def upload(api, headers, case, kind="invoice") -> str:
    source = api.files / "cases" / case.case_id / f"{kind}.{getattr(case, kind + '_format')}"
    response = post_file(api, headers, source.name, source.read_bytes())
    assert response.status_code == 202, response.text
    return response.json()["id"]


def detail(api, headers, document_id) -> dict:
    response = api.client.get(f"/documents/{document_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def review(api, headers, document_id, body):
    return api.client.post(f"/documents/{document_id}/review", json=body, headers=headers)


# --- login ---------------------------------------------------------------------------------------

def test_every_documents_endpoint_needs_a_login(api):
    some_id = uuid.uuid4()
    assert api.client.get("/documents").status_code == 401
    assert api.client.get(f"/documents/{some_id}").status_code == 401
    assert api.client.post("/documents", files={"file": ("a.pdf", b"x")}).status_code == 401
    assert api.client.post(f"/documents/{some_id}/review", json={"action": "reject"}).status_code == 401
    assert api.client.post(f"/documents/{some_id}/reconcile").status_code == 401


# --- uploading -----------------------------------------------------------------------------------

def test_an_upload_is_accepted_at_once_and_processed_in_the_background(api, signup):
    headers = signup()
    source = api.files / "cases" / CLEAN.case_id / f"invoice.{CLEAN.invoice_format}"
    response = post_file(api, headers, source.name, source.read_bytes())
    assert response.status_code == 202
    document_id = response.json()["id"]
    assert response.json()["status"] == "uploaded"
    assert response.headers["location"] == f"/documents/{document_id}"

    view = detail(api, headers, document_id)
    assert view["status"] == "processed" and view["doc_type"] == "invoice"
    assert view["extraction"]["status"] == "ok" and view["extraction"]["charges"]
    assert view["pending_review"] is None and view["reviews"] == []


@pytest.mark.parametrize("name, data, status_code", [
    ("malware.exe", b"MZ\x90\x00", 415),
    ("empty.pdf", b"", 422),
    ("fake.pdf", b"this is not a pdf", 422),
    ("", b"%PDF-1.4 something", 422),
])
def test_unusable_uploads_are_refused_and_nothing_is_stored(api, signup, name, data, status_code):
    headers = signup()
    assert post_file(api, headers, name, data).status_code == status_code
    assert api.client.get("/documents", headers=headers).json() == []
    assert [p for p in api.storage.root.rglob("*") if p.is_file()] == []


def test_a_file_over_the_size_limit_is_refused(api, signup, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 100)
    headers = signup()
    source = api.files / "cases" / CLEAN.case_id / f"invoice.{CLEAN.invoice_format}"
    assert source.stat().st_size > 100
    assert post_file(api, headers, source.name, source.read_bytes()).status_code == 413


def test_without_a_model_key_the_upload_is_refused_before_anything_is_stored(api, signup, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", None)
    app.dependency_overrides.pop(get_llm)  # use the real dependency, which checks the key
    headers = signup()
    source = api.files / "cases" / CLEAN.case_id / f"invoice.{CLEAN.invoice_format}"
    assert post_file(api, headers, source.name, source.read_bytes()).status_code == 503
    assert api.client.get("/documents", headers=headers).json() == []


# --- listing and reading -------------------------------------------------------------------------

def test_listing_is_newest_first_and_pageable(api, signup):
    headers = signup()
    first, second, third = (upload(api, headers, CLEAN) for _ in range(3))
    listed = api.client.get("/documents", headers=headers).json()
    assert [d["id"] for d in listed] == [third, second, first]
    page = api.client.get("/documents?limit=1&offset=1", headers=headers).json()
    assert [d["id"] for d in page] == [second]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_bad_paging_parameters_are_refused(api, signup, query):
    assert api.client.get(f"/documents?{query}", headers=signup()).status_code == 422


def test_unknown_and_malformed_ids(api, signup):
    headers = signup()
    assert api.client.get(f"/documents/{uuid.uuid4()}", headers=headers).status_code == 404
    assert api.client.get("/documents/not-a-uuid", headers=headers).status_code == 422


# --- reviewing -----------------------------------------------------------------------------------

def test_a_document_that_cannot_be_settled_waits_and_shows_its_question(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)
    view = detail(api, headers, document_id)
    assert view["status"] == "needs_review" and view["extraction"]["status"] == "needs_review"
    assert any(issue["code"] == "TOTAL_MISMATCH" for issue in view["pending_review"]["issues"])


def test_approving_needs_a_note_and_then_settles_the_document(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)

    refused = review(api, headers, document_id, {"action": "approve"})
    assert refused.status_code == 422 and "needs a note" in refused.json()["detail"]
    assert detail(api, headers, document_id)["status"] == "needs_review"  # nothing was saved

    accepted = review(api, headers, document_id, {"action": "approve", "note": NOTE})
    assert accepted.status_code == 200
    assert accepted.json() == {"document_status": "processed", "question": None}
    view = detail(api, headers, document_id)
    assert view["status"] == "processed" and view["extraction"]["status"] == "reviewed"
    assert view["pending_review"] is None
    assert [(r["action"], r["note"], r["corrected"]) for r in view["reviews"]] == [("approve", NOTE, False)]


def test_a_correction_fixes_the_stored_values(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)
    response = review(api, headers, document_id, {"action": "correct", "extraction": FIXED.model_dump(mode="json")})
    assert response.status_code == 200 and response.json()["document_status"] == "processed"
    view = detail(api, headers, document_id)
    assert view["extraction"]["total_minor"] == LINE_SUM and view["reviews"][0]["corrected"] is True


def test_rejecting_marks_the_document_rejected(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)
    assert review(api, headers, document_id, {"action": "reject", "note": "wrong shipment"}).status_code == 200
    assert detail(api, headers, document_id)["status"] == "rejected"


def test_the_client_cannot_name_the_reviewer(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)
    response = review(api, headers, document_id, {"action": "approve", "note": NOTE, "reviewer": "ceo@example.com"})
    assert response.status_code == 422
    assert detail(api, headers, document_id)["status"] == "needs_review"


def test_malformed_review_requests_are_refused(api, signup):
    headers = signup()
    document_id = upload(api, headers, WRONG_TOTAL)
    assert review(api, headers, document_id, {"action": "maybe"}).status_code == 422
    assert review(api, headers, document_id, {"action": "correct"}).status_code == 422  # no corrected values
    assert review(api, headers, document_id, {"action": "approve", "note": "x" * 1001}).status_code == 422
    assert detail(api, headers, document_id)["status"] == "needs_review"


def test_only_a_waiting_document_can_be_reviewed(api, signup):
    headers = signup()
    clean = upload(api, headers, CLEAN)
    assert review(api, headers, clean, {"action": "reject"}).status_code == 409
    waiting = upload(api, headers, WRONG_TOTAL)
    assert review(api, headers, waiting, {"action": "approve", "note": NOTE}).status_code == 200
    assert review(api, headers, waiting, {"action": "approve", "note": NOTE}).status_code == 409  # already settled
    assert review(api, headers, uuid.uuid4(), {"action": "reject"}).status_code == 404


# --- reconciling ---------------------------------------------------------------------------------

def test_reconciling_an_invoice_shows_the_findings_in_its_detail(api, signup):
    headers = signup()
    quote = upload(api, headers, OVERCHARGE, "quote")
    invoice = upload(api, headers, OVERCHARGE, "invoice")
    response = api.client.post(f"/documents/{invoice}/reconcile", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "reconciled"
    assert response.json()["discrepancy_count"] == len(OVERCHARGE.expected)

    reconciliation = detail(api, headers, invoice)["reconciliation"]
    assert reconciliation["quote_document_id"] == quote and reconciliation["status"] == "has_discrepancies"
    assert sorted((d["type"], d["variance_minor"]) for d in reconciliation["discrepancies"]) == sorted(
        (e.type, e.variance_minor) for e in OVERCHARGE.expected
    )


def test_reconcile_is_refused_when_it_cannot_be_trusted(api, signup):
    headers = signup()
    quote = upload(api, headers, OVERCHARGE, "quote")
    waiting = upload(api, headers, WRONG_TOTAL)
    assert api.client.post(f"/documents/{quote}/reconcile", headers=headers).status_code == 409  # not an invoice
    assert api.client.post(f"/documents/{waiting}/reconcile", headers=headers).status_code == 409  # awaiting review
    assert api.client.post(f"/documents/{uuid.uuid4()}/reconcile", headers=headers).status_code == 404


def test_an_invoice_with_no_quote_reports_it_as_an_outcome_not_an_error(api, signup):
    headers = signup()
    invoice = upload(api, headers, OVERCHARGE, "invoice")  # its quote was never uploaded
    response = api.client.post(f"/documents/{invoice}/reconcile", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] in ("reference_not_found", "no_candidate")
    assert response.json()["reconciliation_id"] is None


# --- companies are separate ----------------------------------------------------------------------

def test_another_company_cannot_see_review_or_reconcile_a_document(api, signup):
    owner_headers, other_headers = signup(), signup()
    document_id = upload(api, owner_headers, WRONG_TOTAL)

    assert api.client.get("/documents", headers=other_headers).json() == []
    assert api.client.get(f"/documents/{document_id}", headers=other_headers).status_code == 404
    assert review(api, other_headers, document_id, {"action": "approve", "note": NOTE}).status_code == 404
    assert api.client.post(f"/documents/{document_id}/reconcile", headers=other_headers).status_code == 404
    assert detail(api, owner_headers, document_id)["status"] == "needs_review"  # untouched
