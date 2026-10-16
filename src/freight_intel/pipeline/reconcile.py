"""Step 5: compare a quote with an invoice. Plain code: no LLM, no database.

Two jobs:
  match_quote  which quote does this invoice belong to?
  reconcile    what is different between them?

Both work on TypedDocument objects (the output of validate()), so charges are
already integer minor units with canonical codes. Money maths stays in integers.
The LLM's only role comes later: putting the findings below into words.
"""
from dataclasses import dataclass, field

from freight_intel.pipeline.normalize import clean
from freight_intel.pipeline.validation import ROUNDING_TOLERANCE_MINOR, TypedCharge, TypedDocument

TOLERANCE_BPS = 50  # 0.5%, in basis points (1 bp = 0.01%) so the maths stays in integers


@dataclass(frozen=True)
class Discrepancy:
    type: str  # OVERCHARGE | UNDERCHARGE | UNQUOTED_CHARGE | MISSING_CHARGE | CURRENCY_MISMATCH | EXPIRED_QUOTE | ARITHMETIC_ERROR
    charge_code: str | None = None
    label: str | None = None  # the raw label; it is what identifies a charge whose code is OTHER
    quoted_minor: int | None = None  # for ARITHMETIC_ERROR: the sum of the lines
    invoiced_minor: int | None = None  # for ARITHMETIC_ERROR: the printed total
    variance_minor: int | None = None  # invoiced minus quoted: positive means the payer owes more
    note: str = ""


@dataclass
class Reconciliation:
    discrepancies: list[Discrepancy] = field(default_factory=list)
    total_variance_minor: int | None = None  # sum of invoice lines minus sum of quote lines (None if currencies differ)


@dataclass(frozen=True)
class QuoteMatch:
    quote: TypedDocument | None
    how: str  # reference | route | reference_not_found | ambiguous | no_candidate | route_unknown


# --- step 1: which quote? ----------------------------------------------------------------------

def _ref(value: str | None) -> str:
    return (value or "").strip().upper()


def match_quote(invoice: TypedDocument, quotes: list[TypedDocument]) -> QuoteMatch:
    if _ref(invoice.quote_reference):
        found = [q for q in quotes if _ref(q.reference) == _ref(invoice.quote_reference)]
        # A cited quote we do not have is a finding in itself. Falling back to "a similar quote"
        # could attach the invoice to the wrong one, so we do not.
        return QuoteMatch(found[0], "reference") if len(found) == 1 else QuoteMatch(None, "reference_not_found")
    route = (invoice.origin, invoice.destination, invoice.equipment)
    if None in route or invoice.date is None:
        return QuoteMatch(None, "route_unknown")
    # No reference: same route and container type, issued on or before the invoice date.
    # Validity is NOT required here: an invoice that arrives after the quote expired still
    # belongs to it, and reconcile() reports EXPIRED_QUOTE.
    candidates = [q for q in quotes
                  if (q.origin, q.destination, q.equipment) == route and q.date and q.date <= invoice.date]
    if len(candidates) == 1:
        return QuoteMatch(candidates[0], "route")
    return QuoteMatch(None, "ambiguous" if candidates else "no_candidate")


# --- step 2: what differs? ---------------------------------------------------------------------

def _key(charge: TypedCharge) -> str:
    """Charges are compared by canonical code. OTHER is a bucket for unrelated unknown labels,
    so for OTHER the cleaned label is the identity (otherwise two different surcharges would merge)."""
    return clean(charge.label) if charge.code == "OTHER" else charge.code


def _totals(charges: list[TypedCharge]) -> dict[str, tuple[int, TypedCharge]]:
    out: dict[str, tuple[int, TypedCharge]] = {}
    for c in charges:
        if c.amount_minor is None:
            raise ValueError(f"cannot reconcile: no readable amount for {c.label!r}")  # validation should have caught it
        out[_key(c)] = (out.get(_key(c), (0, c))[0] + c.amount_minor, c)
    return out


def within_tolerance(quoted: int, invoiced: int) -> bool:
    """Forgive one cent of rounding, or 0.5% of the quoted amount, whichever is larger."""
    return abs(invoiced - quoted) <= max(ROUNDING_TOLERANCE_MINOR, quoted * TOLERANCE_BPS // 10_000)


def reconcile(quote: TypedDocument, invoice: TypedDocument) -> Reconciliation:
    found: list[Discrepancy] = []

    if quote.valid_until and invoice.date and invoice.date > quote.valid_until:
        found.append(Discrepancy("EXPIRED_QUOTE", note=f"invoice dated {invoice.date}, quote valid until {quote.valid_until}"))

    total_variance = None
    if quote.currency != invoice.currency:
        # 100 EUR is not 100 USD. One finding, and no line-by-line comparison of unlike amounts.
        found.append(Discrepancy("CURRENCY_MISMATCH", note=f"quoted in {quote.currency}, invoiced in {invoice.currency}"))
    else:
        q, i = _totals(quote.charges), _totals(invoice.charges)
        for key in sorted(q.keys() | i.keys()):
            if key not in i:
                amount, c = q[key]
                found.append(Discrepancy("MISSING_CHARGE", c.code, c.label, quoted_minor=amount, variance_minor=-amount))
            elif key not in q:
                amount, c = i[key]
                found.append(Discrepancy("UNQUOTED_CHARGE", c.code, c.label, invoiced_minor=amount, variance_minor=amount))
            elif not within_tolerance(q[key][0], i[key][0]):
                (quoted, _), (invoiced, c) = q[key], i[key]
                found.append(Discrepancy("OVERCHARGE" if invoiced > quoted else "UNDERCHARGE", c.code, c.label,
                                         quoted, invoiced, invoiced - quoted))
        total_variance = sum(a for a, _ in i.values()) - sum(a for a, _ in q.values())

    line_sum = sum(c.amount_minor for c in invoice.charges if c.amount_minor is not None)
    if invoice.total_minor is not None and abs(invoice.total_minor - line_sum) > ROUNDING_TOLERANCE_MINOR:
        found.append(Discrepancy("ARITHMETIC_ERROR", quoted_minor=line_sum, invoiced_minor=invoice.total_minor,
                                 variance_minor=invoice.total_minor - line_sum,
                                 note="the printed total does not equal the sum of the lines"))
    return Reconciliation(found, total_variance)
