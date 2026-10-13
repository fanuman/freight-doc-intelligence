from datetime import date

import pytest

from freight_intel.pipeline.validation import validate
from freight_intel.synth.oracle import perfect_extraction
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset

CASES = build_dataset(45, 42)


def codes(result):
    return [i.code for i in result.issues]


def test_perfect_extractions_have_no_errors_except_real_arithmetic_errors():
    for case in CASES:
        q = validate("quote", perfect_extraction(case, "quote"))
        assert q.ok and codes(q) == [], case.case_id

        inv = validate("invoice", perfect_extraction(case, "invoice"))
        if case.error_kind == ARITHMETIC_ERROR:
            assert codes(inv) == ["TOTAL_MISMATCH"], case.case_id  # a TRUE finding about the document
        else:
            assert inv.ok and codes(inv) == [], case.case_id


def test_typed_values_match_ground_truth():
    for case in CASES:
        q = validate("quote", perfect_extraction(case, "quote")).typed
        assert q.reference == case.quote.quote_ref
        assert q.date == case.quote.issued_on and q.valid_until == case.quote.valid_until
        assert q.currency == case.quote.currency
        assert [c.amount_minor for c in q.charges] == [c.amount_minor for c in case.quote.charges]
        assert q.total_minor == case.quote.total_minor

        i = validate("invoice", perfect_extraction(case, "invoice")).typed
        assert i.reference == case.invoice.invoice_no and i.quote_reference == case.invoice.quote_ref
        assert i.total_minor == case.invoice.stated_total_minor


@pytest.fixture
def quote():
    return perfect_extraction(CASES[0], "quote")


@pytest.fixture
def invoice():
    return perfect_extraction(CASES[0], "invoice")


def test_missing_reference(quote):
    quote.reference = None
    assert "MISSING_REFERENCE" in codes(validate("quote", quote))


def test_unparseable_and_missing_dates(quote):
    quote.issued_text = "10/08/2026"  # ambiguous: refused, not guessed
    quote.valid_until_text = None
    result = validate("quote", quote)
    assert "UNPARSEABLE_DATE" in codes(result) and "MISSING_VALIDITY" in codes(result)


def test_validity_before_issue(quote):
    quote.issued_text, quote.valid_until_text = "2026-09-10", "2026-09-01"
    assert "VALIDITY_BEFORE_ISSUE" in codes(validate("quote", quote))


def test_unknown_and_missing_currency(invoice):
    invoice.currency_text = "XYZ"
    assert "UNKNOWN_CURRENCY" in codes(validate("invoice", invoice))
    invoice.currency_text = None
    assert "MISSING_CURRENCY" in codes(validate("invoice", invoice))


def test_unparseable_amount_blocks_total_check(invoice):
    invoice.charges[0].amount_text = "call us"
    result = validate("invoice", invoice)
    assert "UNPARSEABLE_AMOUNT" in codes(result) and "TOTAL_MISMATCH" not in codes(result)
    assert result.typed.charges[0].amount_minor is None


def test_no_charges(invoice):
    invoice.charges = []
    assert "NO_CHARGES" in codes(validate("invoice", invoice))


def test_misread_line_is_caught_as_total_mismatch(invoice):
    invoice.charges[0].amount_text = "1,00"  # a misread that the total exposes
    result = validate("invoice", invoice)
    assert "TOTAL_MISMATCH" in codes(result) and not result.ok


def test_one_cent_difference_is_tolerated(quote):
    from freight_intel.pipeline.money import parse_money

    quote.total_text = f"{(parse_money(quote.total_text) + 1) / 100:.2f}"
    assert "TOTAL_MISMATCH" not in codes(validate("quote", quote))


def test_duplicate_charge_is_only_a_warning(invoice):
    invoice.charges.append(invoice.charges[0])
    result = validate("invoice", invoice)
    dup = [i for i in result.issues if i.code == "DUPLICATE_CHARGE"]
    assert dup and dup[0].severity == "warning"


def test_missing_total_is_only_a_warning(invoice):
    invoice.total_text = None
    result = validate("invoice", invoice)
    assert [i.severity for i in result.issues if i.code == "MISSING_TOTAL"] == ["warning"]
    assert result.ok
