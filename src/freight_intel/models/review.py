"""One row per human decision about a document: who decided what, and why.

Append-only: a decision is never updated or replaced, so the table is the audit trail of
every approval, correction and rejection. Foreign keys are COMPOSITE (tenant_id, id), like
the result tables, so a review can never point at another tenant's document or user.
"""
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from freight_intel.models.base import Base
from freight_intel.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class Review(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("action IN ('approve', 'correct', 'reject')", name="reviews_action_check"),
        # Corrected values are stored with a 'correct' decision, and only with that one.
        CheckConstraint("(action = 'correct') = (corrected_data IS NOT NULL)", name="reviews_corrected_data_check"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="reviews_document_fk",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"],
            ["users.tenant_id", "users.id"],
            name="reviews_reviewer_fk",
        ),
        Index("reviews_document_idx", "document_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    document_id: Mapped[uuid.UUID] = mapped_column()
    reviewer_id: Mapped[uuid.UUID] = mapped_column()  # the logged-in user, set by our code, never by the client
    action: Mapped[str] = mapped_column(Text)  # approve | correct | reject
    note: Mapped[str] = mapped_column(Text, server_default="")
    # The whole corrected extraction ('correct' only). none_as_null makes Python None a real SQL NULL; without
    # it SQLAlchemy stores the JSON value null, which the reviews_corrected_data_check would count as data.
    corrected_data: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
