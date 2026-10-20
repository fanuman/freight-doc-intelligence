"""The translation between pipeline objects and database rows, tested without a database.

The key test is a round trip: save-shaped values are turned back into TypedDocuments, and
reconciling THOSE must give exactly the findings the generator expects. If a column were
forgotten in the mapping, this fails.
"""
import json
from types import SimpleNamespace

from freight_intel.pipeline.reconcile import match_quote, reconcile
from freight_intel.pipeline.validation import validate
from freight_intel.services import result_mapping as mapping
from freight_intel.synth.oracle import perfect_extraction
from freight_intel.synth.scenario import build_dataset

CASES = build_dataset(45, 42)


def state_for(case, kind):
    extraction = perfect_extraction(case, kind)
    result = validate(kind, extraction)
    return {"doc_type": kind, "extraction": extraction, "typed": result.typed, "issues": result.issues,
            "status": "ok" if result.ok else "needs_review"}


def as_rows(values):
    """What the database would hand back: one extraction row and its charge rows."""
    extraction = SimpleNamespace(**{k: v for k, v in values.items() if k not in ("charges", "data", "issues")})
    charges = [SimpleNamespace(**c) for c in values["charges"]]
    charges = [SimpleNamespace(raw_label=c.raw_label, amount_minor=c.amount_minor, canonical_code=c.canonical_code, known=c.known)
               for c in charges]
    return extraction, charges


def test_values_are_json_serialisable_for_the_jsonb_columns():
    for case in CASES[:10]:
        values = mapping.extraction_values(state_for(case, "invoice"))
        json.dumps(values["data"]), json.dumps(values["issues"])  # raises if a date or object slipped in


def test_round_trip_through_rows_gives_the_generators_findings_for_all_45_cases():
    for case in CASES:
        q_row, q_charges = as_rows(mapping.extraction_values(state_for(case, "quote")))
        i_row, i_charges = as_rows(mapping.extraction_values(state_for(case, "invoice")))
        quote, invoice = mapping.typed_from_rows(q_row, q_charges), mapping.typed_from_rows(i_row, i_charges)
        got = sorted((d.type, d.charge_code, d.variance_minor) for d in reconcile(quote, invoice).discrepancies)
        want = sorted((e.type, e.charge_code, e.variance_minor) for e in case.expected)
        assert got == want, case.case_id


def test_discrepancy_dictionaries_have_exactly_the_keys_the_repository_reads():
    case = next(c for c in CASES if c.error_kind == "OVERCHARGE")
    q_row, q_charges = as_rows(mapping.extraction_values(state_for(case, "quote")))
    i_row, i_charges = as_rows(mapping.extraction_values(state_for(case, "invoice")))
    found = reconcile(mapping.typed_from_rows(q_row, q_charges), mapping.typed_from_rows(i_row, i_charges)).discrepancies
    (d,) = mapping.discrepancy_values(found)
    assert set(d) == {"type", "charge_code", "label", "quoted_minor", "invoiced_minor", "variance_minor", "note"}


def test_matching_works_on_header_only_rows():
    quotes = [mapping.typed_from_rows(as_rows(mapping.extraction_values(state_for(c, "quote")))[0]) for c in CASES]
    cited = next(c for c in CASES if c.invoice.quote_ref)
    invoice = mapping.typed_from_rows(as_rows(mapping.extraction_values(state_for(cited, "invoice")))[0])
    assert match_quote(invoice, quotes).quote.reference == cited.quote.quote_ref


def test_document_outcome_and_failed_runs_save_no_extraction():
    assert mapping.document_outcome({"doc_type": "quote", "status": "ok"}) == ("quote", "processed")
    assert mapping.document_outcome({"doc_type": "invoice", "status": "needs_review"}) == ("invoice", "needs_review")
    assert mapping.document_outcome({"doc_type": "rate_sheet", "status": "unsupported"}) == ("rate_sheet", "failed")
    assert mapping.document_outcome({"status": "failed"}) == ("unknown", "failed")
    half_finished = state_for(CASES[0], "quote") | {"status": "failed", "error": "model refused"}
    assert mapping.extraction_values(half_finished) is None  # a half-finished reading is not saved


def test_reviewed_and_rejected_runs():
    assert mapping.document_outcome({"doc_type": "invoice", "status": "reviewed"}) == ("invoice", "processed")
    assert mapping.document_outcome({"doc_type": "invoice", "status": "rejected"}) == ("invoice", "rejected")
    reviewed = state_for(CASES[0], "invoice") | {"status": "reviewed"}
    assert mapping.extraction_values(reviewed)["status"] == "reviewed"
    rejected = state_for(CASES[0], "invoice") | {"status": "rejected"}
    assert mapping.extraction_values(rejected) is None  # nothing new to save; the earlier reading stays
