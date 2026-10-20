"""All database access for review decisions. Only ORM calls, no business rules."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from freight_intel.models import Review


def add(
    session: Session, *, tenant_id: uuid.UUID, document_id: uuid.UUID, reviewer_id: uuid.UUID,
    action: str, note: str = "", corrected_data: dict | None = None,
) -> Review:
    """Record one decision. Reviews are only ever added, never changed."""
    review = Review(
        tenant_id=tenant_id, document_id=document_id, reviewer_id=reviewer_id,
        action=action, note=note, corrected_data=corrected_data,
    )
    session.add(review)
    session.flush()
    return review


def list_for_document(session: Session, document_id: uuid.UUID) -> list[Review]:
    """Every decision about one document, oldest first."""
    return list(session.scalars(
        select(Review).where(Review.document_id == document_id).order_by(Review.created_at, Review.id)
    ))
