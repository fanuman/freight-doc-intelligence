"""One-time setup of an empty database. Safe to run again.

  1. create the APP role (the one the API uses; row-level security applies to it) and give it its rights
  2. create or update the tables (the same as `alembic upgrade head`)
  3. create LangGraph's checkpoint tables

On your laptop, Docker Compose does step 1 by itself when the database is first created
(docker/postgres/init-app-role.sh). On AWS nothing runs that script, because RDS starts out empty, so this
module does it. It runs once as a one-off container task, as the OWNER, before the API starts:

    python -m freight_intel.bootstrap

Order matters: the rights are granted BEFORE the tables are created, because "default privileges" only
cover tables that are created afterwards.
"""
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import make_conninfo

from freight_intel.config import get_settings
from freight_intel.pipeline.checkpoint import setup_checkpoint_tables

# <project root>/alembic.ini: /app/alembic.ini in the image, the repo root on your laptop.
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def ensure_app_role() -> None:
    """Create the app role if it is missing (or set its password again), then give it its rights."""
    settings = get_settings()
    conninfo = make_conninfo(
        host=settings.db_host, port=settings.db_port, dbname=settings.postgres_db,
        user=settings.postgres_user, password=settings.postgres_password,
    )
    role = sql.Identifier(settings.app_db_user)
    owner = sql.Identifier(settings.postgres_user)
    database = sql.Identifier(settings.postgres_db)
    password = sql.Literal(settings.app_db_password)

    with psycopg.connect(conninfo, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (settings.app_db_user,)).fetchone()
        if exists:
            conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(role, password))
        else:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(role, password))
        # The same rights docker/postgres/init-app-role.sh gives on your laptop: read and write rows, nothing more.
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        conn.execute(sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(owner, role))
        conn.execute(sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}"
        ).format(owner, role))


def run_migrations() -> None:
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


def bootstrap() -> None:
    print("1/3 app role and its rights")
    ensure_app_role()
    print("2/3 tables")
    run_migrations()
    print("3/3 checkpoint tables")
    setup_checkpoint_tables()
    print("the database is ready")


if __name__ == "__main__":
    bootstrap()
