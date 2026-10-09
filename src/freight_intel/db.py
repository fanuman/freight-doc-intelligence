"""Database connection and the tenant-scoped session.

This is the one place that knows how a request becomes "a database session
that can only see one tenant's rows".
"""
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from freight_intel.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """One engine (= one connection pool) for the whole process.

    It connects as the *app* role, which is subject to row-level security.
    The owner role is only for migrations. pool_pre_ping tests a pooled
    connection before using it, so a restarted database doesn't surface as a
    random 500.
    """
    return create_engine(get_settings().app_url, pool_pre_ping=True)


@contextmanager
def tenant_session(tenant_id: uuid.UUID | None) -> Iterator[Session]:
    """Open a transaction in which Postgres only shows `tenant_id`'s rows.

    - `session.begin()` starts a transaction, commits when the block ends
      normally, and rolls back if an exception escapes. (Django:
      `transaction.atomic()`.)
    - set_config(..., true) makes the setting local to this transaction, so it
      cannot leak to the next request that reuses the pooled connection.
    - tenant_id=None sets nothing. The RLS policies then match no rows
      ("fail closed"). Used only for the login lookup, before we know the tenant.
    """
    with Session(get_engine()) as session, session.begin():
        if tenant_id is not None:
            session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(tenant_id)},
            )
        yield session
