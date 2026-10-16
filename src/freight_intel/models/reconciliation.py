"""A comparison of one invoice against its quote, and the findings it produced.

Same pattern as extraction.py: tenant_id on every row and composite foreign keys.
ON DELETE CASCADE means replacing an extraction also removes the reconciliation built
on it, which is right because that comparison is now stale and gets recomputed.
"""
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

DISCREPANCY_TYPES = (
    "OVERCHARGE", "UNDERCHARGE", "UNQUOTED_CHARGE", "MISSING_CHARGE",
    "CURRENCY_MISMATCH", "EXPIRED_QUOTE", "ARITHMETIC_ERROR",
)


class Reconciliation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliations"
    __table_args__ = (
        CheckConstraint("status IN ('clean', 'has_discrepancies')", name="reconciliations_status_check"),
        UniqueConstraint("invoice_extraction_id", name="reconciliations_invoice_key"),  # one per invoice
        UniqueConstraint("tenant_id", "id", name="reconciliations_tenant_id_id_key"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_extraction_id"],
            ["extractions.tenant_id", "extractions.id"],
            name="reconciliations_quote_fk",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_extraction_id"],
            ["extractions.tenant_id", "extractions.id"],
            name="reconciliations_invoice_fk",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    quote_extraction_id: Mapped[uuid.UUID] = mapped_column()
    invoice_extraction_id: Mapped[uuid.UUID] = mapped_column()
    match_method: Mapped[str] = mapped_column(Text)  # reference | route
    currency: Mapped[str | None] = mapped_column(Text)
    total_variance_minor: Mapped[int | None] = mapped_column(BigInteger)  # invoice lines minus quote lines
    status: Mapped[str] = mapped_column(Text)  # clean | has_discrepancies


class Discrepancy(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discrepancies"
    __table_args__ = (
        CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in DISCREPANCY_TYPES) + ")",
            name="discrepancies_type_check",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reconciliation_id"],
            ["reconciliations.tenant_id", "reconciliations.id"],
            name="discrepancies_reconciliation_fk",
            ondelete="CASCADE",
        ),
        Index("discrepancies_reconciliation_idx", "reconciliation_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    reconciliation_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(Text)
    charge_code: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)  # identifies a charge whose code is OTHER
    quoted_minor: Mapped[int | None] = mapped_column(BigInteger)
    invoiced_minor: Mapped[int | None] = mapped_column(BigInteger)
    variance_minor: Mapped[int | None] = mapped_column(BigInteger)  # invoiced minus quoted
    note: Mapped[str] = mapped_column(Text, server_default="")
    explanation: Mapped[str | None] = mapped_column(Text)  # written later by the LLM, from the fields above only
