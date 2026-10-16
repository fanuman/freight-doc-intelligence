"""All database access for extractions and their charges. Only ORM calls, no business rules."""
import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from freight_intel.models import Charge, Extraction


def replace_for_document(
    session: Session, *, tenant_id: uuid.UUID, document_id: uuid.UUID, doc_type: str, status: str,
    reference: str | None, quote_reference: str | None, doc_date: date | None, valid_until: date | None,
    currency: str | None, origin: str | None, destination: str | None, equipment: str | None,
    total_minor: int | None, data: dict, issues: list, charges: list[dict],
) -> Extraction:
    """Save what the pipeline read from a document, replacing any earlier reading of it.

    A document has at most one extraction (a database rule). Re-processing deletes the old
    one first; the database then removes its charges, and any reconciliation built on it,
    automatically (ON DELETE CASCADE). Run this inside one transaction (db.tenant_session):
    either the extraction and ALL its charges are saved, or nothing is.
    """
    session.execute(delete(Extraction).where(Extraction.document_id == document_id))
    extraction = Extraction(
        tenant_id=tenant_id, document_id=document_id, doc_type=doc_type, status=status,
        reference=reference, quote_reference=quote_reference, doc_date=doc_date, valid_until=valid_until,
        currency=currency, origin=origin, destination=destination, equipment=equipment,
        total_minor=total_minor, data=data, issues=issues,
    )
    session.add(extraction)
    session.flush()  # INSERT now, so extraction.id is known for the charges
    session.add_all(
        Charge(
            tenant_id=tenant_id, extraction_id=extraction.id, position=position,
            canonical_code=c["canonical_code"], raw_label=c["raw_label"],
            amount_minor=c["amount_minor"], known=c["known"],
        )
        for position, c in enumerate(charges)
    )
    session.flush()
    return extraction


def get(session: Session, extraction_id: uuid.UUID) -> Extraction | None:
    return session.get(Extraction, extraction_id)


def get_for_document(session: Session, document_id: uuid.UUID) -> Extraction | None:
    return session.scalars(select(Extraction).where(Extraction.document_id == document_id)).first()


def list_by_type(session: Session, doc_type: str) -> list[Extraction]:
    """Every extraction of one kind, oldest first. Row-level security limits it to this tenant."""
    return list(session.scalars(
        select(Extraction).where(Extraction.doc_type == doc_type).order_by(Extraction.created_at)
    ))


def get_charges(session: Session, extraction_id: uuid.UUID) -> list[Charge]:
    return list(session.scalars(
        select(Charge).where(Charge.extraction_id == extraction_id).order_by(Charge.position)
    ))
