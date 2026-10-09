import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from freight_intel.config import get_settings


@pytest.fixture(scope="module")
def engines():
    settings = get_settings()
    owner = create_engine(settings.owner_url)  # bypasses RLS: seeding and checks only
    app = create_engine(settings.app_url)  # what the API uses: subject to RLS
    yield owner, app
    owner.dispose()
    app.dispose()


@pytest.fixture
def two_tenants(engines):
    owner, _ = engines
    ids = {key: uuid.uuid4() for key in ("tenant_a", "tenant_b", "doc_a", "doc_b")}
    with owner.begin() as conn:
        for key, name in (("tenant_a", "Tenant A"), ("tenant_b", "Tenant B")):
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
                {"id": ids[key], "name": name},
            )
        for doc_key, tenant_key in (("doc_a", "tenant_a"), ("doc_b", "tenant_b")):
            conn.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, filename, storage_key) "
                    "VALUES (:id, :tenant_id, 'test.pdf', :key)"
                ),
                {
                    "id": ids[doc_key],
                    "tenant_id": ids[tenant_key],
                    "key": f"test/{ids[doc_key]}",
                },
            )
    yield ids
    with owner.begin() as conn:
        params = {"a": ids["tenant_a"], "b": ids["tenant_b"]}
        conn.execute(text("DELETE FROM documents WHERE tenant_id IN (:a, :b)"), params)
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), params)


@contextmanager
def tenant_conn(app_engine, tenant_id):
    """A transaction as the app role, scoped to one tenant (or none)."""
    with app_engine.begin() as conn:
        if tenant_id is not None:
            # third argument true = local to this transaction only
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
        yield conn


def test_app_role_is_not_privileged(engines):
    """If this fails, every other test in this file proves nothing."""
    _, app = engines
    with app.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


@pytest.mark.parametrize(
    "me, my_doc, other_doc",
    [("tenant_a", "doc_a", "doc_b"), ("tenant_b", "doc_b", "doc_a")],
)
def test_tenant_sees_only_own_documents(engines, two_tenants, me, my_doc, other_doc):
    _, app = engines
    with tenant_conn(app, two_tenants[me]) as conn:
        seen = {r.id for r in conn.execute(text("SELECT id FROM documents"))}
    assert two_tenants[my_doc] in seen
    assert two_tenants[other_doc] not in seen


def test_tenant_sees_only_own_tenant_row(engines, two_tenants):
    _, app = engines
    with tenant_conn(app, two_tenants["tenant_a"]) as conn:
        seen = {r.id for r in conn.execute(text("SELECT id FROM tenants"))}
    assert seen == {two_tenants["tenant_a"]}


def test_no_tenant_context_sees_nothing(engines, two_tenants):
    """Fail closed: forgetting to set the tenant returns zero rows, not all rows."""
    _, app = engines
    with tenant_conn(app, None) as conn:
        docs = conn.execute(text("SELECT id FROM documents")).all()
        tenants = conn.execute(text("SELECT id FROM tenants")).all()
    assert docs == []
    assert tenants == []


def test_guessing_another_tenants_document_id_finds_nothing(engines, two_tenants):
    _, app = engines
    with tenant_conn(app, two_tenants["tenant_a"]) as conn:
        rows = conn.execute(
            text("SELECT id FROM documents WHERE id = :id"),
            {"id": two_tenants["doc_b"]},
        ).all()
    assert rows == []


def test_cannot_insert_a_document_into_another_tenant(engines, two_tenants):
    _, app = engines
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_conn(app, two_tenants["tenant_a"]) as conn:
            conn.execute(
                text(
                    "INSERT INTO documents (tenant_id, filename, storage_key) "
                    "VALUES (:tid, 'evil.pdf', 'evil')"
                ),
                {"tid": two_tenants["tenant_b"]},
            )


def test_cannot_create_tenants_as_app_role(engines, two_tenants):
    _, app = engines
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_conn(app, two_tenants["tenant_a"]) as conn:
            conn.execute(text("INSERT INTO tenants (name) VALUES ('rogue')"))


def test_cannot_update_another_tenants_document(engines, two_tenants):
    owner, app = engines
    with tenant_conn(app, two_tenants["tenant_a"]) as conn:
        result = conn.execute(
            text("UPDATE documents SET filename = 'hacked.pdf' WHERE id = :id"),
            {"id": two_tenants["doc_b"]},
        )
    assert result.rowcount == 0
    with owner.connect() as conn:
        name = conn.execute(
            text("SELECT filename FROM documents WHERE id = :id"),
            {"id": two_tenants["doc_b"]},
        ).scalar_one()
    assert name == "test.pdf"


def test_cannot_delete_another_tenants_document(engines, two_tenants):
    owner, app = engines
    with tenant_conn(app, two_tenants["tenant_a"]) as conn:
        result = conn.execute(
            text("DELETE FROM documents WHERE id = :id"),
            {"id": two_tenants["doc_b"]},
        )
    assert result.rowcount == 0
    with owner.connect() as conn:
        still_there = conn.execute(
            text("SELECT count(*) FROM documents WHERE id = :id"),
            {"id": two_tenants["doc_b"]},
        ).scalar_one()
    assert still_there == 1


def test_tenant_can_only_be_created_with_its_own_id(engines):
    """Registration inserts a tenant as the app role. The policy must allow
    only the tenant whose id matches the transaction's tenant context."""
    owner, app = engines
    own_id, other_id = uuid.uuid4(), uuid.uuid4()
    try:
        with tenant_conn(app, own_id) as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, 'self-registered')"),
                {"id": own_id},
            )
        with pytest.raises(DBAPIError, match="row-level security"):
            with tenant_conn(app, own_id) as conn:
                conn.execute(
                    text("INSERT INTO tenants (id, name) VALUES (:id, 'spoofed')"),
                    {"id": other_id},
                )
    finally:
        with owner.begin() as conn:
            conn.execute(
                text("DELETE FROM tenants WHERE id IN (:a, :b)"),
                {"a": own_id, "b": other_id},
            )
