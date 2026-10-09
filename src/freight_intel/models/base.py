from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Parent of every model.

    Base.metadata collects every table that inherits from it. Alembic reads
    that metadata to autogenerate migrations, which is the same job Django's
    migration autodetector does with `models.Model`.
    """
