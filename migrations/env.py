from alembic import context
from sqlalchemy import create_engine

from freight_intel.config import get_settings
from freight_intel.models import Base

config = context.config


def run_migrations_online() -> None:
    engine = create_engine(get_settings().owner_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()