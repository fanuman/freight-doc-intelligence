import uuid
from enum import Enum

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin
from freight_intel.models.tenant import Tenant


class Role(str, Enum):
    """Allowed roles. The database also enforces them with a CHECK constraint."""

    ADMIN = "admin"
    MEMBER = "member"


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="users_role_check"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    # unique=True makes Postgres create a constraint named users_email_key.
    # services/auth.py relies on that exact name to detect duplicate sign-ups.
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default=Role.MEMBER.value)

    # user.tenant -> the Tenant object (Django: a ForeignKey attribute).
    tenant: Mapped[Tenant] = relationship(back_populates="users")
