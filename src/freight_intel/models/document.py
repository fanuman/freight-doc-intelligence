import uuid
from enum import Enum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class DocumentType(str, Enum):
    QUOTE = "quote"
    RATE_SHEET = "rate_sheet"
    INVOICE = "invoice"
    UNKNOWN = "unknown"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    PROCESSED = "processed"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('quote', 'rate_sheet', 'invoice', 'unknown')",
            name="documents_doc_type_check",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'needs_review', 'processed', 'failed')",
            name="documents_status_check",
        ),
        Index("documents_tenant_created_idx", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text, server_default=DocumentType.UNKNOWN.value)
    status: Mapped[str] = mapped_column(Text, server_default=DocumentStatus.UPLOADED.value)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
