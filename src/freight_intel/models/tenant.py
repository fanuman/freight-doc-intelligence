from typing import TYPE_CHECKING

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # only for type hints; avoids a circular import at runtime
    from freight_intel.models.user import User


class Tenant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One customer company. Every other row in the system belongs to a tenant."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(Text)

    # Python-side navigation only (no column): tenant.users -> list of User.
    # Django equivalent: the reverse accessor `tenant.user_set`.
    users: Mapped[list["User"]] = relationship(back_populates="tenant")
