"""Translate between pipeline objects and database rows. Pure functions: no database, no I/O.

Kept apart from results.py so they can be tested without Postgres, the same way nodes.py
keeps the pipeline steps apart from LangGraph.
"""
from collections.abc import Iterable, Mapping
from dataclasses import asdict

from freight_intel.pipeline.reconcile import Discrepancy
from freight_intel.pipeline.validation import TypedCharge, TypedDocument

# How a pipeline run ended -> how the document is described in the database.
# "unsupported" (for example a rate sheet) is recorded as failed: we could not process it.
DOCUMENT_STATUS = {
    "ok": "processed", "needs_review": "needs_review",
    "reviewed": "processed",  # a person approved or corrected it: as settled as an `ok` run
    "rejected": "rejected",  # a person said it is not usable
    "failed": "failed", "unsupported": "failed",
}


def document_outcome(state: Mapping) -> tuple[str, str]:
    """(doc_type, status) to record on the document row."""
    return state.get("doc_type") or "unknown", DOCUMENT_STATUS.get(state.get("status"), "failed")


def extraction_values(state: Mapping) -> dict | None:
    """The arguments for extractions.replace_for_document, or None when nothing usable was extracted.

    Only a run that ended `ok`, `needs_review` or `reviewed` has an extraction worth saving. A failed
    run may still carry a half-finished `typed` from an earlier attempt, so the status decides. A
    `rejected` document saves nothing new: the earlier reading stays as the record of what was rejected.
    """
    typed = state.get("typed")
    if typed is None or state.get("status") not in ("ok", "needs_review", "reviewed"):
        return None
    return {
        "doc_type": typed.doc_type,
        "status": state["status"],
        "reference": typed.reference,
        "quote_reference": typed.quote_reference,
        "doc_date": typed.date,
        "valid_until": typed.valid_until,
        "currency": typed.currency,
        "origin": typed.origin,
        "destination": typed.destination,
        "equipment": typed.equipment,
        "total_minor": typed.total_minor,
        "data": state["extraction"].model_dump(mode="json"),  # exactly what the model returned
        "issues": [asdict(issue) for issue in state.get("issues", [])],
        "charges": [
            {"canonical_code": c.code, "raw_label": c.label, "amount_minor": c.amount_minor, "known": c.known}
            for c in typed.charges
        ],
    }


def typed_from_rows(extraction, charges: Iterable = ()) -> TypedDocument:
    """Rebuild the TypedDocument that reconcile() and match_quote() work on, from stored rows.

    `charges` can be left empty when only the header fields are needed (matching a quote).
    """
    return TypedDocument(
        doc_type=extraction.doc_type,
        reference=extraction.reference,
        quote_reference=extraction.quote_reference,
        date=extraction.doc_date,
        valid_until=extraction.valid_until,
        currency=extraction.currency,
        charges=[TypedCharge(c.raw_label, c.amount_minor, c.canonical_code, c.known) for c in charges],
        total_minor=extraction.total_minor,
        origin=extraction.origin,
        destination=extraction.destination,
        equipment=extraction.equipment,
    )


def discrepancy_values(found: Iterable[Discrepancy]) -> list[dict]:
    """The dictionaries reconciliations.replace_for_invoice expects (the field names match)."""
    return [asdict(d) for d in found]
