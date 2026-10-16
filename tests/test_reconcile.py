"""Reconciliation against the generator's ground truth, plus the rules one by one.

The big test needs no LLM and no files: it feeds the perfect extraction of each of the 45 cases
through validate() and reconcile(), and compares the findings with the `expected` list the
generator wrote down when it damaged the invoice.
"""
from dataclasses import replace
from datetime import date

from freight_intel.pipeline.reconcile import match_quote, reconcile, within_tolerance
from freight_intel.pipeline.validation import TypedCharge, TypedDocument, validate
from freight_intel.synth.oracle import perfect_extraction
from freight_intel.synth.scenario import build_dataset

CASES = build_dataset(45, 42)


def typed(case, kind):
    return validate(kind, perfect_extraction(case, kind)).typed


def test_findings_match_the_generators_ground_truth_for_all_45_cases():
    for case in CASES:
        got = sorted((d.type, d.charge_code, d.variance_minor)
                     for d in reconcile(typed(case, "quote"), typed(case, "invoice")).discrepancies)
        want = sorted((e.type, e.charge_code, e.variance_minor) for e in case.expected)
        assert got == want, f"{case.case_id} ({case.error_kind}): {got} != {want}"


def test_clean_and_rounding_cases_report_nothing():
    for case in CASES:
        if case.error_kind in ("CLEAN", "ROUNDING_NOISE"):
            assert reconcile(typed(case, "quote"), typed(case, "invoice")).discrepancies == [], case.case_id


def test_matching_by_reference_and_by_route():
    quotes = [typed(c, "quote") for c in CASES]
    how = {"reference": 0, "route": 0, "ambiguous": 0}
    for case in CASES:
        inv = typed(case, "invoice")
        m = match_quote(inv, quotes)
        how[m.how] += 1
        if m.quote is not None:
            assert m.quote.reference == case.quote.quote_ref, case.case_id  # never matched to the wrong quote
    assert how == {"reference": 32, "route": 11, "ambiguous": 2}  # the 2 are sent to a human, not guessed


def test_a_cited_quote_that_is_missing_is_not_replaced_by_a_similar_one():
    quotes = [typed(c, "quote") for c in CASES]
    inv = replace(typed(CASES[0], "invoice"), quote_reference="Q-DOES-NOT-EXIST")
    assert match_quote(inv, quotes).how == "reference_not_found"


def test_tolerance_is_one_cent_or_half_a_percent():
    assert within_tolerance(27_000, 27_001) and within_tolerance(27_000, 27_135)  # 0.5% of 27,000 is 135
    assert not within_tolerance(27_000, 27_136)
    assert within_tolerance(100, 101) and not within_tolerance(100, 102)  # small amounts: the 1 cent floor


def _doc(charges, **kw):
    base = dict(doc_type="quote", reference="Q", quote_reference=None, date=date(2026, 8, 3), valid_until=date(2026, 8, 17),
                currency="USD", charges=charges, total_minor=sum(c.amount_minor for c in charges))
    return TypedDocument(**{**base, **kw})


def test_two_different_unknown_surcharges_stay_two_findings():
    quote = _doc([TypedCharge("Ocean Freight", 1000, "OCEAN_FREIGHT", True)])
    invoice = _doc([TypedCharge("O/F", 1000, "OCEAN_FREIGHT", True), TypedCharge("Peak Season Surcharge", 150, "OTHER", False),
                    TypedCharge("Low Sulphur Surcharge", 90, "OTHER", False)], doc_type="invoice")
    found = reconcile(quote, invoice).discrepancies
    assert [(d.type, d.label) for d in found] == [("UNQUOTED_CHARGE", "Low Sulphur Surcharge"), ("UNQUOTED_CHARGE", "Peak Season Surcharge")]


def test_currency_mismatch_is_one_finding_and_skips_the_line_comparison():
    quote = _doc([TypedCharge("Ocean Freight", 1000, "OCEAN_FREIGHT", True)])
    invoice = _doc([TypedCharge("Ocean Freight", 920, "OCEAN_FREIGHT", True)], doc_type="invoice", currency="EUR")
    result = reconcile(quote, invoice)
    assert [d.type for d in result.discrepancies] == ["CURRENCY_MISMATCH"] and result.total_variance_minor is None


def test_an_expired_quote_is_reported_and_the_charges_are_still_compared():
    quote = _doc([TypedCharge("Ocean Freight", 1000, "OCEAN_FREIGHT", True)])
    invoice = _doc([TypedCharge("Ocean Freight", 1300, "OCEAN_FREIGHT", True)], doc_type="invoice", date=date(2026, 9, 1))
    assert sorted(d.type for d in reconcile(quote, invoice).discrepancies) == ["EXPIRED_QUOTE", "OVERCHARGE"]


def test_a_lower_invoice_is_reported_as_undercharge_not_overcharge():
    quote = _doc([TypedCharge("Ocean Freight", 1000, "OCEAN_FREIGHT", True)])
    invoice = _doc([TypedCharge("Ocean Freight", 700, "OCEAN_FREIGHT", True)], doc_type="invoice")
    assert [(d.type, d.variance_minor) for d in reconcile(quote, invoice).discrepancies] == [("UNDERCHARGE", -300)]
