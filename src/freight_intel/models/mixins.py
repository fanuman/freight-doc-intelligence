"""Columns that several tables share, written once.

A mixin is a plain class (not a table) that models inherit from to pick up
columns. Same idea as an abstract base model in Django.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    # server_default means *Postgres* generates the id if Python doesn't supply
    # one. We still generate it in Python for tenants (see services/auth.py).
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
