"""Step 4: deterministic checks on what the LLM extracted. No AI in this file.

validate() does two things at once:
  1. converts the model's copied text into real values (ints, dates), via money.py
  2. lists everything that looks wrong, as Issue objects

An issue means "this extraction can't be trusted as is". It does NOT always mean
the model misread: for an ARITHMETIC_ERROR invoice the printed total really is
wrong, so TOTAL_MISMATCH is a true finding. Telling those two cases apart is the
job of the repair loop on Day 39 (re-read once more; if it still disagrees, the
document itself is wrong).
"""
from dataclasses import dataclass, field
from datetime import date

from freight_intel.pipeline.money import normalize_currency, parse_date, parse_money

ROUNDING_TOLERANCE_MINOR = 1  # lines may differ from the printed total by one cent


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    severity: str = "error"  # "error" | "warning"
    field: str | None = None


@dataclass(frozen=True)
class TypedCharge:
    label: str
    amount_minor: int | None  # None = we could not read the amount


@dataclass
class TypedDocument:
    """The extraction after conversion: real numbers and dates, still not normalised
    to canonical codes (that is Day 39)."""

    doc_type: str
    reference: str | None
    quote_reference: str | None  # invoices only
    date: date | None  # issue date (quote) or invoice date
    valid_until: date | None  # quotes only
    currency: str | None
    charges: list[TypedCharge]
    total_minor: int | None


@dataclass
class ValidationResult:
    typed: TypedDocument
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(doc_type: str, extraction) -> ValidationResult:
    is_quote = doc_type == "quote"
    issues: list[Issue] = []

    reference = extraction.reference if is_quote else extraction.invoice_number
    date_text = extraction.issued_text if is_quote else extraction.invoice_date_text
    date_field = "issued_text" if is_quote else "invoice_date_text"

    if not (reference or "").strip():
        issues.append(Issue("MISSING_REFERENCE", "no document number found", field="reference"))

    doc_date = parse_date(date_text)
    if date_text is None:
        issues.append(Issue("MISSING_DATE", "no document date found", field=date_field))
    elif doc_date is None:
        issues.append(Issue("UNPARSEABLE_DATE", f"cannot read date {date_text!r}", field=date_field))

    valid_until = None
    if is_quote:
        valid_until = parse_date(extraction.valid_until_text)
        if extraction.valid_until_text is None:
            issues.append(Issue("MISSING_VALIDITY", "quote has no validity date", field="valid_until_text"))
        elif valid_until is None:
            issues.append(Issue("UNPARSEABLE_DATE", f"cannot read date {extraction.valid_until_text!r}",
                                field="valid_until_text"))
        if doc_date and valid_until and valid_until < doc_date:
            issues.append(Issue("VALIDITY_BEFORE_ISSUE", "quote expires before it was issued"))

    currency = normalize_currency(extraction.currency_text)
    if extraction.currency_text is None:
        issues.append(Issue("MISSING_CURRENCY", "no currency found", field="currency_text"))
    elif currency is None:
        issues.append(Issue("UNKNOWN_CURRENCY", f"unrecognised currency {extraction.currency_text!r}",
                            field="currency_text"))

    charges = []
    for raw in extraction.charges:
        amount = parse_money(raw.amount_text)
        if amount is None:
            issues.append(Issue("UNPARSEABLE_AMOUNT",
                                f"cannot read amount {raw.amount_text!r} for {raw.label!r}", field="charges"))
        charges.append(TypedCharge(raw.label, amount))
    if not charges:
        issues.append(Issue("NO_CHARGES", "no charge lines found", field="charges"))

    seen = set()
    for c in charges:
        key = (c.label.strip().lower(), c.amount_minor)
        if key in seen:
            issues.append(Issue("DUPLICATE_CHARGE", f"{c.label!r} appears twice with the same amount",
                                severity="warning", field="charges"))
        seen.add(key)

    total = parse_money(extraction.total_text)
    if extraction.total_text is None:
        issues.append(Issue("MISSING_TOTAL", "no total found", severity="warning", field="total_text"))
    elif total is None:
        issues.append(Issue("UNPARSEABLE_AMOUNT", f"cannot read total {extraction.total_text!r}",
                            field="total_text"))
    elif charges and all(c.amount_minor is not None for c in charges):
        line_sum = sum(c.amount_minor for c in charges)
        if abs(line_sum - total) > ROUNDING_TOLERANCE_MINOR:
            issues.append(Issue(
                "TOTAL_MISMATCH",
                f"printed total {total} does not equal the sum of the lines {line_sum} "
                f"(difference {total - line_sum} minor units): the model may have misread a line, "
                f"or the document itself may be wrong",
                field="total_text"))

    typed = TypedDocument(
        doc_type=doc_type,
        reference=(reference or None),
        quote_reference=None if is_quote else extraction.quote_reference,
        date=doc_date,
        valid_until=valid_until,
        currency=currency,
        charges=charges,
        total_minor=total,
    )
    return ValidationResult(typed, issues)
