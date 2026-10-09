"""Business rules for sign-up and login.

Services decide *what should happen* and own the transaction. They call
repositories to touch the database, and raise domain exceptions that the API
layer turns into HTTP status codes. They know nothing about HTTP.
"""
import uuid

from sqlalchemy.exc import IntegrityError

from freight_intel.db import tenant_session
from freight_intel.models import Role
from freight_intel.repositories import tenants, users
from freight_intel.security import create_access_token, hash_password, verify_password


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


def register(*, company_name: str, email: str, password: str) -> str:
    """Create a company and its first admin user, and return an access token."""
    # Hash first: argon2 is slow on purpose, so keep it out of the transaction
    # (a transaction holds a database connection while it is open).
    password_hash = hash_password(password)

    # We pick the tenant id ourselves instead of letting Postgres do it. We
    # need it *before* the insert to set the tenant context, and the policy
    # "tenant_self_register" only allows inserting a tenant whose id equals
    # that context. So a caller can only ever create the tenant they act as.
    tenant_id = uuid.uuid4()

    try:
        with tenant_session(tenant_id) as session:
            tenants.create(session, tenant_id=tenant_id, name=company_name)
            user = users.create(
                session,
                tenant_id=tenant_id,
                email=email,
                password_hash=password_hash,
                role=Role.ADMIN.value,
            )
            # Read the id while the session is open. After commit, SQLAlchemy
            # expires loaded attributes ("expire_on_commit"), so touching
            # user.id after the with-block would try to reload it.
            user_id = user.id
    except IntegrityError as exc:
        # Both inserts ran in one transaction, so on failure the tenant is
        # rolled back too: no orphan company without a user.
        if _is_duplicate_email(exc):
            raise EmailAlreadyRegistered from exc
        raise

    return create_access_token(
        user_id=user_id, tenant_id=tenant_id, role=Role.ADMIN.value
    )


def login(*, email: str, password: str) -> str:
    """Check credentials and return an access token."""
    with tenant_session(None) as session:  # no tenant known yet
        creds = users.find_credentials_by_email(session, email)

    # Verify outside the transaction. With an unknown email we still run a
    # full hash check (see security.verify_password) to keep timing equal.
    password_ok = verify_password(password, creds.password_hash if creds else None)
    if creds is None or not password_ok:
        # One error for both cases, so the API can't be used to discover
        # which emails have accounts.
        raise InvalidCredentials

    return create_access_token(
        user_id=creds.user_id, tenant_id=creds.tenant_id, role=creds.role
    )


def _is_duplicate_email(exc: IntegrityError) -> bool:
    # exc.orig is the raw psycopg error; its diag object names the violated
    # constraint. Matching on the name is exact, unlike searching message text.
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == "users_email_key"
