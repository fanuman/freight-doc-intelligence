"""What the documents API needs, assembled from the repositories and the processing service.

Like the other services: each function owns its transaction and returns plain values (dictionaries and
dataclasses), never ORM objects, because their attributes expire when the transaction ends. The dictionaries
are shaped to match the response schemas in schemas/documents.py.
"""
import uuid

from freight_intel.db import tenant_session
from freight_intel.repositories import documents, extractions, reconciliations, reviews
from freight_intel.services import processing, results
from freight_intel.services.processing import DocumentNotFound
from freight_intel.services.uploads import CheckedUpload
from freight_intel.storage import LocalStorage, get_storage

__all__ = ["DocumentNotFound", "NotReconcilable", "register_upload", "list_documents", "get_document", "reconcile_document"]


class NotReconcilable(Exception):
    """This document cannot be reconciled (yet). The message says why, for the person who asked."""


def register_upload(*, tenant_id: uuid.UUID, user_id: uuid.UUID, upload: CheckedUpload, storage=None) -> uuid.UUID:
    """Store a checked file and add its document row (status uploaded). Returns the new document id.

    The id is chosen first because the storage key is built from it. If the row cannot be saved the file
    is removed again, so a failed upload leaves nothing behind.
    """
    files = get_storage() if storage is None else storage
    document_id = uuid.uuid4()
    key = LocalStorage.key_for(tenant_id, document_id, upload.extension)
    files.save(key, upload.data)
    try:
        with tenant_session(tenant_id) as session:
            documents.create(
                session, tenant_id=tenant_id, filename=upload.display_name, storage_key=key,
                uploaded_by=user_id, document_id=document_id,
            )
    except Exception:
        files.delete(key)
        raise
    return document_id


def list_documents(*, tenant_id: uuid.UUID, limit: int, offset: int = 0) -> list[dict]:
    with tenant_session(tenant_id) as session:
        return [_summary(document) for document in documents.list_recent(session, limit=limit, offset=offset)]


def get_document(*, tenant_id: uuid.UUID, document_id: uuid.UUID, checkpointer=None) -> dict:
    """Everything known about one document: status, what was read, findings, review history, open question."""
    with tenant_session(tenant_id) as session:
        document = documents.get(session, document_id)
        if document is None:
            raise DocumentNotFound
        view = _summary(document)
        extraction = extractions.get_for_document(session, document_id)
        view["extraction"] = _extraction(session, extraction) if extraction else None
        view["reconciliation"] = _reconciliation(session, extraction) if extraction else None
        view["reviews"] = [
            {"action": r.action, "note": r.note, "reviewer_id": r.reviewer_id, "created_at": r.created_at,
             "corrected": r.corrected_data is not None}
            for r in reviews.list_for_document(session, document_id)
        ]
    view["pending_review"] = (
        processing.pending_question(tenant_id=tenant_id, document_id=document_id, checkpointer=checkpointer)
        if view["status"] == "needs_review" else None
    )
    return view


def reconcile_document(*, tenant_id: uuid.UUID, document_id: uuid.UUID) -> results.ReconcileOutcome:
    """Compare an invoice document with its quote and store the findings (replacing any earlier ones)."""
    with tenant_session(tenant_id) as session:
        if documents.get(session, document_id) is None:
            raise DocumentNotFound
        extraction = extractions.get_for_document(session, document_id)
        if extraction is None or extraction.doc_type != "invoice":
            raise NotReconcilable("only an invoice that has been read can be reconciled")
        extraction_id = extraction.id
    try:
        return results.reconcile_invoice(tenant_id=tenant_id, invoice_extraction_id=extraction_id)
    except results.NotSettled as exc:
        raise NotReconcilable("this invoice is still waiting for a review, or was rejected") from exc
    except results.InvoiceNotFound as exc:  # it was replaced between the two steps
        raise NotReconcilable("the invoice changed while it was being reconciled; try again") from exc


# --- plain-value builders: call them inside the session ------------------------------------------------

def _summary(document) -> dict:
    return {
        "id": document.id, "filename": document.filename, "doc_type": document.doc_type,
        "status": document.status, "created_at": document.created_at,
    }


def _extraction(session, row) -> dict:
    return {
        "id": row.id, "status": row.status, "doc_type": row.doc_type, "reference": row.reference,
        "quote_reference": row.quote_reference, "doc_date": row.doc_date, "valid_until": row.valid_until,
        "currency": row.currency, "origin": row.origin, "destination": row.destination,
        "equipment": row.equipment, "total_minor": row.total_minor, "issues": row.issues,
        "charges": [
            {"position": c.position, "code": c.canonical_code, "label": c.raw_label,
             "amount_minor": c.amount_minor, "known": c.known}
            for c in extractions.get_charges(session, row.id)
        ],
    }


def _reconciliation(session, extraction_row) -> dict | None:
    row = reconciliations.get_for_invoice(session, extraction_row.id)
    if row is None:
        return None
    quote = extractions.get(session, row.quote_extraction_id)
    return {
        "id": row.id, "quote_document_id": quote.document_id, "match_method": row.match_method,
        "currency": row.currency, "total_variance_minor": row.total_variance_minor, "status": row.status,
        "discrepancies": [
            {"position": d.position, "type": d.type, "charge_code": d.charge_code, "label": d.label,
             "quoted_minor": d.quoted_minor, "invoiced_minor": d.invoiced_minor,
             "variance_minor": d.variance_minor, "note": d.note, "explanation": d.explanation}
            for d in reconciliations.get_discrepancies(session, row.id)
        ],
    }
