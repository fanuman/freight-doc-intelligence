"""What the pipeline read from a document: one Extraction per document, plus its Charges.

Both tables carry tenant_id, and their foreign keys are COMPOSITE: (tenant_id, parent id).
That makes it impossible for a row to point at a parent owned by another tenant, even
if application code had a bug. Row-level security (migration 0003) hides other tenants'
rows; the composite keys stop cross-tenant links from ever being created.
"""
import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class Extraction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "extractions"
    __table_args__ = (
        CheckConstraint("doc_type IN ('quote', 'invoice')", name="extractions_doc_type_check"),
        CheckConstraint("status IN ('ok', 'needs_review', 'reviewed')", name="extractions_status_check"),
        UniqueConstraint("document_id", name="extractions_document_key"),  # one extraction per document
        UniqueConstraint("tenant_id", "id", name="extractions_tenant_id_id_key"),  # target for child tables
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="extractions_document_fk",
            ondelete="CASCADE",
        ),
        Index("extractions_tenant_reference_idx", "tenant_id", "reference"),
        Index("extractions_tenant_route_idx", "tenant_id", "origin", "destination", "equipment"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    document_id: Mapped[uuid.UUID] = mapped_column()
    doc_type: Mapped[str] = mapped_column(Text)  # quote | invoice
    status: Mapped[str] = mapped_column(Text)  # ok | needs_review | reviewed

    # The converted values reconciliation needs, as real columns so they can be queried.
    reference: Mapped[str | None] = mapped_column(Text)
    quote_reference: Mapped[str | None] = mapped_column(Text)  # invoices: the quote they cite
    doc_date: Mapped[date | None] = mapped_column(Date)  # issue date (quote) or invoice date
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)  # UN/LOCODE
    destination: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[str | None] = mapped_column(Text)
    total_minor: Mapped[int | None] = mapped_column(BigInteger)  # the total as PRINTED on the document

    # Exactly what the model returned, kept for audit. Never used for comparisons.
    data: Mapped[dict] = mapped_column(JSONB)
    issues: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class Charge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "charges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["extractions.tenant_id", "extractions.id"],
            name="charges_extraction_fk",
            ondelete="CASCADE",
        ),
        Index("charges_extraction_idx", "extraction_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    extraction_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int] = mapped_column(Integer)  # order on the page
    canonical_code: Mapped[str] = mapped_column(Text)  # "OTHER" when the label was not recognised
    raw_label: Mapped[str] = mapped_column(Text)  # exactly as printed
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)  # None = unreadable amount
    known: Mapped[bool] = mapped_column(Boolean)  # False = label not in the alias table, a human should look
