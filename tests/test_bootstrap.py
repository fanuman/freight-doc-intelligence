"""bootstrap: the one-time setup of an empty database must also be safe on a database that is already set up."""
import psycopg
from psycopg.conninfo import make_conninfo

from freight_intel.bootstrap import bootstrap, ensure_app_role
from freight_intel.config import get_settings


def _owner_query(statement, params=()):
    settings = get_settings()
    conninfo = make_conninfo(
        host=settings.db_host, port=settings.db_port, dbname=settings.postgres_db,
        user=settings.postgres_user, password=settings.postgres_password,
    )
    with psycopg.connect(conninfo) as conn:
        return conn.execute(statement, params).fetchall()


def test_the_app_role_can_log_in_but_has_no_special_powers():
    ensure_app_role()
    ensure_app_role()  # a second run changes nothing and does not fail
    ((can_login, superuser, bypasses_rls),) = _owner_query(
        "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (get_settings().app_db_user,)
    )
    assert can_login
    assert not superuser and not bypasses_rls  # row-level security must still apply to it


def test_the_whole_bootstrap_can_run_twice_on_a_database_that_is_already_set_up():
    bootstrap()
    bootstrap()
    tables = {row[0] for row in _owner_query("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"tenants", "documents", "reviews", "checkpoints"} <= tables
