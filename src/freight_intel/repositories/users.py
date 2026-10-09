"""All database access for users.

A repository is the layer that talks to the database. Services call it and
never write queries themselves. (Django: custom manager methods.)
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from freight_intel.models import User


@dataclass(frozen=True)
class Credentials:
    """Just what login needs. Not a User, because we have no tenant context yet."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    password_hash: str
    role: str


def create(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    email: str,
    password_hash: str,
    role: str,
) -> User:
    user = User(
        tenant_id=tenant_id,
        email=email.strip().lower(),  # emails are case-insensitive in practice
        password_hash=password_hash,
        role=role,
    )
    session.add(user)
    session.flush()  # INSERT now; also fills user.id and user.created_at
    return user


def get_with_tenant(session: Session, user_id: uuid.UUID) -> User | None:
    """Fetch a user and their tenant in ONE query.

    session.get() looks up by primary key. joinedload() adds a JOIN so
    `user.tenant` is already loaded. Without it, touching `user.tenant` later
    would fire a second query (the N+1 problem; Django: select_related).
    Row-level security still applies: a user from another tenant is invisible.
    """
    return session.get(User, user_id, options=[joinedload(User.tenant)])


def find_credentials_by_email(session: Session, email: str) -> Credentials | None:
    """Login lookup. The one place that is not a plain ORM query.

    At login we don't know the tenant yet, and row-level security hides every
    user until a tenant is set. So we call a SECURITY DEFINER function
    (migration 0002) that returns exactly one user's credentials by email and
    nothing else. func.<name>() calls a database function from SQLAlchemy;
    .table_valued() says "it returns rows with these columns".
    """
    lookup = func.auth_get_user_by_email(email.strip().lower()).table_valued(
        "id", "tenant_id", "password_hash", "role"
    )
    row = session.execute(select(lookup)).first()
    if row is None:
        return None
    return Credentials(
        user_id=row.id,
        tenant_id=row.tenant_id,
        password_hash=row.password_hash,
        role=row.role,
    )
