import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from freight_intel.api.main import app
from freight_intel.config import get_settings

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def owner_engine():
    engine = create_engine(get_settings().owner_url)
    yield engine
    engine.dispose()


@pytest.fixture
def created(owner_engine):
    """Collects what a test creates, then deletes it as the owner afterwards."""
    emails: list[str] = []
    company_names: list[str] = []
    yield emails, company_names
    with owner_engine.begin() as conn:
        tenant_ids = [
            r.tenant_id
            for r in conn.execute(
                text("SELECT tenant_id FROM users WHERE email = ANY(:e)"), {"e": emails}
            )
        ]
        tenant_ids += [
            r.id
            for r in conn.execute(
                text("SELECT id FROM tenants WHERE name = ANY(:n)"), {"n": company_names}
            )
        ]
        conn.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": emails})
        conn.execute(text("DELETE FROM tenants WHERE id = ANY(:t)"), {"t": tenant_ids})


def new_email(created) -> str:
    email = f"pytest-{uuid.uuid4().hex[:12]}@example.com"
    created[0].append(email)
    return email


def register(client, created, *, email=None, password=PASSWORD, company=None):
    company = company or f"pytest-co-{uuid.uuid4().hex[:8]}"
    created[1].append(company)
    email = email or new_email(created)
    response = client.post(
        "/auth/register",
        json={"company_name": company, "email": email, "password": password},
    )
    return email, response


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def forged_token(**overrides) -> str:
    settings = get_settings()
    claims = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


# --- register ---------------------------------------------------------------

def test_register_returns_a_token(client, created):
    _, response = register(client, created)
    assert response.status_code == 201
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_register_makes_first_user_an_admin_of_a_new_tenant(client, created):
    company = f"pytest-co-{uuid.uuid4().hex[:8]}"
    email, response = register(client, created, company=company)
    me = client.get("/me", headers=auth_header(response.json()["access_token"])).json()
    assert me["role"] == "admin"
    assert me["tenant_name"] == company
    assert me["email"] == email.lower()


def test_duplicate_email_is_rejected(client, created):
    email, first = register(client, created)
    _, second = register(client, created, email=email)
    assert first.status_code == 201
    assert second.status_code == 409


def test_duplicate_email_ignores_case(client, created):
    email, _ = register(client, created)
    _, second = register(client, created, email=email.upper())
    assert second.status_code == 409


def test_short_password_is_rejected(client, created):
    _, response = register(client, created, password="short")
    assert response.status_code == 422


def test_blank_company_name_is_rejected(client, created):
    _, response = register(client, created, company="   ")
    assert response.status_code == 422


def test_invalid_email_is_rejected(client, created):
    _, response = register(client, created, email="not-an-email")
    assert response.status_code == 422


def test_failed_registration_leaves_no_orphan_tenant(client, created, owner_engine):
    """Tenant and user are created in one transaction: if the user insert
    fails, the tenant insert must roll back with it."""
    email, _ = register(client, created)
    orphan_company = f"pytest-orphan-{uuid.uuid4().hex[:8]}"
    _, response = register(client, created, email=email, company=orphan_company)
    assert response.status_code == 409
    with owner_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM tenants WHERE name = :n"), {"n": orphan_company}
        ).scalar_one()
    assert count == 0


# --- login ------------------------------------------------------------------

def test_login_with_correct_password(client, created):
    email, _ = register(client, created)
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_is_case_insensitive_on_email(client, created):
    email, _ = register(client, created)
    response = client.post(
        "/auth/login", json={"email": email.upper(), "password": PASSWORD}
    )
    assert response.status_code == 200


def test_login_with_wrong_password_and_unknown_email_look_identical(client, created):
    email, _ = register(client, created)
    wrong_password = client.post(
        "/auth/login", json={"email": email, "password": "wrong-password-123"}
    )
    unknown_email = client.post(
        "/auth/login",
        json={"email": "nobody-here@example.com", "password": "wrong-password-123"},
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


# --- /me and token checks ---------------------------------------------------

def test_me_requires_a_token(client):
    assert client.get("/me").status_code == 401


def test_me_rejects_garbage_token(client):
    assert client.get("/me", headers=auth_header("not.a.jwt")).status_code == 401


def test_me_rejects_token_signed_with_wrong_secret(client):
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "tid": str(uuid.uuid4()),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "some-other-secret-that-is-long-enough-123456",
        algorithm="HS256",
    )
    assert client.get("/me", headers=auth_header(token)).status_code == 401


def test_me_rejects_expired_token(client):
    token = forged_token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.get("/me", headers=auth_header(token)).status_code == 401


def test_me_rejects_alg_none_token(client):
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "tid": str(uuid.uuid4()),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    assert client.get("/me", headers=auth_header(token)).status_code == 401


def test_valid_token_for_deleted_user_is_rejected(client):
    """A correctly signed token for a user that doesn't exist must not work."""
    assert client.get("/me", headers=auth_header(forged_token())).status_code == 401


def test_each_user_sees_only_their_own_tenant(client, created):
    _, a = register(client, created)
    _, b = register(client, created)
    me_a = client.get("/me", headers=auth_header(a.json()["access_token"])).json()
    me_b = client.get("/me", headers=auth_header(b.json()["access_token"])).json()
    assert me_a["tenant_id"] != me_b["tenant_id"]
    assert me_a["tenant_name"] != me_b["tenant_name"]


def test_healthz_needs_no_token(client):
    assert client.get("/healthz").json() == {"status": "ok"}
