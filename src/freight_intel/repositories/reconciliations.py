"""All database access for reconciliations and their discrepancies. Only ORM calls, no business rules."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from freight_intel.models import Discrepancy, Reconciliation


def replace_for_invoice(
    session: Session, *, tenant_id: uuid.UUID, quote_extraction_id: uuid.UUID,
    invoice_extraction_id: uuid.UUID, match_method: str, currency: str | None,
    total_variance_minor: int | None, discrepancies: list[dict],
) -> Reconciliation:
    """Store the comparison of an invoice with its quote, replacing any earlier one for that invoice."""
    session.execute(delete(Reconciliation).where(Reconciliation.invoice_extraction_id == invoice_extraction_id))
    reconciliation = Reconciliation(
        tenant_id=tenant_id, quote_extraction_id=quote_extraction_id,
        invoice_extraction_id=invoice_extraction_id, match_method=match_method, currency=currency,
        total_variance_minor=total_variance_minor,
        status="has_discrepancies" if discrepancies else "clean",
    )
    session.add(reconciliation)
    session.flush()
    session.add_all(
        Discrepancy(
            tenant_id=tenant_id, reconciliation_id=reconciliation.id, position=position,
            type=d["type"], charge_code=d["charge_code"], label=d["label"],
            quoted_minor=d["quoted_minor"], invoiced_minor=d["invoiced_minor"],
            variance_minor=d["variance_minor"], note=d["note"],
        )
        for position, d in enumerate(discrepancies)
    )
    session.flush()
    return reconciliation


def get_for_invoice(session: Session, invoice_extraction_id: uuid.UUID) -> Reconciliation | None:
    return session.scalars(
        select(Reconciliation).where(Reconciliation.invoice_extraction_id == invoice_extraction_id)
    ).first()


def get_discrepancies(session: Session, reconciliation_id: uuid.UUID) -> list[Discrepancy]:
    return list(session.scalars(
        select(Discrepancy).where(Discrepancy.reconciliation_id == reconciliation_id)
        .order_by(Discrepancy.position)
    ))
