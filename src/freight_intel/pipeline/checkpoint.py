"""Where LangGraph keeps its checkpoints: in Postgres, so a paused review survives a restart.

Two roles, two jobs. Creating the checkpoint tables needs rights the app role deliberately lacks,
so setup_checkpoint_tables() connects as the OWNER and is run once (like a migration). At runtime
the API uses the APP role, which can only read and write rows. These tables have no tenant column
and no row-level security (LangGraph decides their shape), so tenant safety comes from the thread
id (tenant id + document id) and from the service checking ownership first.
"""
from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from freight_intel.config import get_settings

# The same connection settings PostgresSaver.from_conn_string uses internally.
CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


def _conninfo(user: str, password: str) -> str:
    settings = get_settings()
    return make_conninfo(
        host=settings.db_host, port=settings.db_port, dbname=settings.postgres_db,
        user=user, password=password,
    )


def open_pool(*, max_size: int = 5) -> ConnectionPool:
    """A pool of database connections as the APP role. The caller closes it."""
    settings = get_settings()
    return ConnectionPool(
        _conninfo(settings.app_db_user, settings.app_db_password),
        min_size=1, max_size=max_size, kwargs=CONNECTION_KWARGS, open=True,
    )


@lru_cache
def _shared_pool() -> ConnectionPool:
    return open_pool()


@lru_cache
def get_checkpointer() -> PostgresSaver:
    """The saver the API uses: one pool, created on first use, shared by the whole process."""
    return PostgresSaver(_shared_pool())


def close_checkpointer() -> None:
    """Close the shared pool at shutdown (a no-op if it was never opened)."""
    if _shared_pool.cache_info().currsize:
        _shared_pool().close()
    get_checkpointer.cache_clear()
    _shared_pool.cache_clear()


def setup_checkpoint_tables() -> None:
    """Create LangGraph's tables as the OWNER role. Safe to run again: it only adds what is missing."""
    settings = get_settings()
    with PostgresSaver.from_conn_string(_conninfo(settings.postgres_user, settings.postgres_password)) as saver:
        saver.setup()


if __name__ == "__main__":
    setup_checkpoint_tables()
    print("checkpoint tables are ready")
