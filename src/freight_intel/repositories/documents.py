"""All database access for documents. Only ORM calls, no business rules."""
import uuid

from sqlalchemy import select, update
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


def get(session: Session, document_id: uuid.UUID) -> Document | None:
    """One document, or None. Row-level security hides other tenants' documents, so they are None too."""
    return session.get(Document, document_id)


def get_for_update(session: Session, document_id: uuid.UUID) -> Document | None:
    """Like get(), and locks the row until the transaction ends: a second caller waits here, then sees the new status."""
    return session.get(Document, document_id, with_for_update=True)


def list_recent(session: Session, *, limit: int, offset: int = 0) -> list[Document]:
    """This tenant's documents, newest first."""
    return list(session.scalars(
        select(Document).order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)
    ))


def claim_for_processing(session: Session, document_id: uuid.UUID) -> bool:
    """Move a document from uploaded to processing, in ONE statement. True only for the caller that won.

    The WHERE clause is the lock: if two workers try at the same moment, Postgres lets one UPDATE
    match the row and the other finds it already changed, so exactly one of them gets True.
    """
    result = session.execute(
        update(Document).where(Document.id == document_id, Document.status == "uploaded").values(status="processing")
    )
    return result.rowcount == 1


def set_status(session: Session, document_id: uuid.UUID, status: str) -> None:
    session.execute(update(Document).where(Document.id == document_id).values(status=status))
