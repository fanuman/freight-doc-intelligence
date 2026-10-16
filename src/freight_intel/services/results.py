"""Business rules for saving pipeline results and reconciling invoices.

Like services/auth.py: each public function owns ONE transaction (tenant_session), calls
repositories to touch the database, and returns plain values, never ORM objects (their
attributes expire when the transaction commits). The translation between pipeline objects
and rows lives in result_mapping.py.
"""
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from freight_intel.db import tenant_session
from freight_intel.pipeline.reconcile import match_quote, reconcile
from freight_intel.repositories import documents, extractions, reconciliations
from freight_intel.services import result_mapping as mapping


class InvoiceNotFound(Exception):
    """No invoice extraction with that id in this tenant (or the id belongs to a quote)."""


@dataclass(frozen=True)
class SavedResult:
    document_status: str  # processed | needs_review | failed
    extraction_id: uuid.UUID | None  # None when nothing was extracted (failed or unsupported)


@dataclass(frozen=True)
class ReconcileOutcome:
    # reconciled | reference_not_found | ambiguous | no_candidate | route_unknown | unreadable_amount
    status: str
    reconciliation_id: uuid.UUID | None = None
    discrepancy_count: int = 0


def save_pipeline_result(*, tenant_id: uuid.UUID, document_id: uuid.UUID, state: Mapping) -> SavedResult:
    """Store what the pipeline produced for one document, and record how the run ended.

    One transaction: the extraction, all its charges and the document's new status are saved
    together, or none of them are. Running it again for the same document replaces the
    earlier extraction (and any reconciliation built on it).

    If the run failed, no extraction is written and an earlier successful one is kept: the
    document's status describes the latest run, the extraction the latest successful reading.
    """
    doc_type, doc_status = mapping.document_outcome(state)
    values = mapping.extraction_values(state)
    with tenant_session(tenant_id) as session:
        extraction_id = None
        if values is not None:
            extraction = extractions.replace_for_document(
                session, tenant_id=tenant_id, document_id=document_id, **values
            )
            extraction_id = extraction.id  # read it while the session is open
        documents.record_outcome(session, document_id, doc_type=doc_type, status=doc_status)
    return SavedResult(doc_status, extraction_id)


def reconcile_invoice(*, tenant_id: uuid.UUID, invoice_extraction_id: uuid.UUID) -> ReconcileOutcome:
    """Find the invoice's quote among this tenant's stored quotes, compare them, and store the findings.

    The matching and the comparison are the plain functions in pipeline/reconcile.py. This
    function only loads rows, calls them, and saves the result. If the quote cannot be found
    safely (not found, ambiguous), nothing is stored and the status says why.
    """
    with tenant_session(tenant_id) as session:
        invoice_row = extractions.get(session, invoice_extraction_id)
        if invoice_row is None or invoice_row.doc_type != "invoice":
            raise InvoiceNotFound
        invoice = mapping.typed_from_rows(invoice_row, extractions.get_charges(session, invoice_row.id))

        # Matching only needs header fields, so quotes are loaded without their charges (no N+1 queries).
        candidates = [(row, mapping.typed_from_rows(row)) for row in extractions.list_by_type(session, "quote")]
        match = match_quote(invoice, [typed for _, typed in candidates])
        if match.quote is None:
            return ReconcileOutcome(match.how)

        quote_row = next(row for row, typed in candidates if typed is match.quote)
        quote = mapping.typed_from_rows(quote_row, extractions.get_charges(session, quote_row.id))
        if any(c.amount_minor is None for c in (*quote.charges, *invoice.charges)):
            return ReconcileOutcome("unreadable_amount")  # cannot compare a charge we could not read

        result = reconcile(quote, invoice)
        row = reconciliations.replace_for_invoice(
            session, tenant_id=tenant_id, quote_extraction_id=quote_row.id,
            invoice_extraction_id=invoice_row.id, match_method=match.how, currency=invoice.currency,
            total_variance_minor=result.total_variance_minor,
            discrepancies=mapping.discrepancy_values(result.discrepancies),
        )
        return ReconcileOutcome("reconciled", row.id, len(result.discrepancies))
