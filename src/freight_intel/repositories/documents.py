"""All database access for documents. Only ORM calls, no business rules."""
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from freight_intel.models import Document


def create(
    session: Session, *, tenant_id: uuid.UUID, filename: str, storage_key: str,
    uploaded_by: uuid.UUID | None = None,
) -> Document:
    document = Document(
        tenant_id=tenant_id, filename=filename, storage_key=storage_key, uploaded_by=uploaded_by
    )
    session.add(document)
    session.flush()  # INSERT now, so document.id is filled in
    return document


def record_outcome(session: Session, document_id: uuid.UUID, *, doc_type: str, status: str) -> None:
    """After the pipeline ran: store what kind of document it turned out to be and how it ended."""
    session.execute(
        update(Document).where(Document.id == document_id).values(doc_type=doc_type, status=status)
    )
