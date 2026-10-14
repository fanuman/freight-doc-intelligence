from datetime import date

import pytest

from freight_intel.pipeline.money import format_minor, normalize_currency, parse_date, parse_money
from freight_intel.pipeline.parsing import parse_document


@pytest.mark.parametrize("text, expected", [
    ("1,234.56", 123456),
    ("1.234,56", 123456),
    ("1 234.56", 123456),
    ("USD 1,234.56", 123456),
    ("1.234,56 EUR", 123456),
    ("$2,685.00", 268500),
    ("€1,234.56", 123456),
    ("2.025,00", 202500),
    ("2960", 296000),
    ("2,960.00", 296000),
    ("0,05", 5),
    ("5,00", 500),
    ("1,234,567.89", 123456789),
    ("1.234.567,89", 123456789),
    ("-25.00", -2500),
    ("(25.00)", -2500),
    ("1.234", 123400),   # three digits after one separator => thousands
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", [None, "", "n/a", "EUR", "--"])
def test_parse_money_returns_none_rather_than_guessing(text):
    assert parse_money(text) is None


@pytest.mark.parametrize("text, expected", [
    ("2026-08-10", date(2026, 8, 10)),
    ("10 Aug 2026", date(2026, 8, 10)),
    ("10 August 2026", date(2026, 8, 10)),
    ("10.08.2026", date(2026, 8, 10)),
    ("August 10, 2026", date(2026, 8, 10)),
    ("August 05, 2026", date(2026, 8, 5)),
    ("  10   Aug  2026 ", date(2026, 8, 10)),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", [None, "", "10/08/2026", "next Tuesday", "2026-13-40"])
def test_ambiguous_or_garbage_dates_are_not_guessed(text):
    assert parse_date(text) is None


def test_normalize_currency():
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("XYZ") is None
    assert normalize_currency(None) is None


# --- parsing real generated files ---------------------------------------------

@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("openpyxl")
    pytest.importorskip("pdfplumber")
    from freight_intel.synth.scenario import build_dataset
    from freight_intel.synth.writer import write_dataset

    out = tmp_path_factory.mktemp("data")
    write_dataset(45, 42, out)
    return out, build_dataset(45, 42)


def _kind_and_file(case, kind):
    fmt = case.quote_format if kind == "quote" else case.invoice_format
    return f"{kind}.{fmt}"


def test_every_document_parses_to_nonempty_text_containing_its_reference(dataset):
    out, cases = dataset
    for case in cases:
        for kind, ref in (("quote", case.quote.quote_ref), ("invoice", case.invoice.invoice_no)):
            parsed = parse_document(out / "cases" / case.case_id / _kind_and_file(case, kind))
            assert parsed.text, (case.case_id, kind)
            assert ref in parsed.text, (case.case_id, kind)
            assert parsed.warnings == []


def test_pdf_text_keeps_charge_rows_together(dataset):
    out, cases = dataset
    from freight_intel.synth import domain

    for case in cases:
        if case.invoice_format != "pdf":
            continue
        parsed = parse_document(out / "cases" / case.case_id / "invoice.pdf")
        carrier = next(c for c in domain.CARRIERS if c.carrier_id == case.quote.carrier_id)
        first = case.invoice.charges[0]
        # label and amount must sit on the same line, or the LLM can't pair them
        line = next(l for l in parsed.text.splitlines() if first.raw_label in l)
        assert domain.format_amount(first.amount_minor, carrier.number_style) in line


def test_xlsx_numeric_cells_show_as_excel_displays_them(dataset):
    out, cases = dataset
    from freight_intel.synth import domain

    seen = 0
    for case in cases:
        if case.quote_format != "xlsx":
            continue
        carrier = next(c for c in domain.CARRIERS if c.carrier_id == case.quote.carrier_id)
        if carrier.number_style != "us":
            continue
        parsed = parse_document(out / "cases" / case.case_id / "quote.xlsx")
        ocean = case.quote.charges[0]
        assert f"{ocean.amount_minor / 100:,.2f}" in parsed.text
        seen += 1
    assert seen > 0


def test_eml_has_headers_and_body(dataset):
    out, cases = dataset
    case = next(c for c in cases if c.quote_format == "eml")
    parsed = parse_document(out / "cases" / case.case_id / "quote.eml")
    assert parsed.text.startswith("From:")
    assert "Subject:" in parsed.text and case.quote.quote_ref in parsed.text


def test_unsupported_type_raises(tmp_path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        parse_document(f)


def test_pdf_without_text_warns(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    p = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(p))
    c.showPage()
    c.save()
    parsed = parse_document(p)
    assert parsed.text == "" and parsed.warnings


@pytest.mark.parametrize("minor", [0, 5, 100, 19501, 419500, 504000, 123456789])
def test_format_minor_round_trips_through_parse_money(minor):
    assert parse_money(format_minor(minor)) == minor
