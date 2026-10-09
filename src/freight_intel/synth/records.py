"""Ground-truth records: what each synthetic document *really* says.

The renderers turn these into messy PDFs/spreadsheets/emails; the extractor's
job (Day 38) is to recover these records from the mess. The evaluation compares
the two, so every field here is a field the extractor is graded on.
"""
from dataclasses import asdict, dataclass, field
from datetime import date
import json


@dataclass(frozen=True)
class Charge:
    code: str  # canonical, e.g. "THC_ORIGIN"
    raw_label: str  # exactly as printed on the document
    amount_minor: int  # integer cents


@dataclass
class QuoteTruth:
    quote_ref: str
    carrier_id: str
    issued_on: date
    valid_until: date
    origin: str  # UN/LOCODE
    destination: str
    container_type: str
    incoterm: str
    currency: str
    charges: list[Charge]

    @property
    def total_minor(self) -> int:
        return sum(c.amount_minor for c in self.charges)


@dataclass
class InvoiceTruth:
    invoice_no: str
    quote_ref: str | None  # None = the invoice doesn't cite its quote
    carrier_id: str
    invoice_date: date
    origin: str
    destination: str
    container_type: str
    currency: str
    charges: list[Charge]
    stated_total_minor: int  # what the invoice PRINTS as its total (may be wrong)

    @property
    def computed_total_minor(self) -> int:
        return sum(c.amount_minor for c in self.charges)


@dataclass
class ExpectedDiscrepancy:
    """What a correct reconciliation must report for this case."""

    type: str  # OVERCHARGE | UNQUOTED_CHARGE | MISSING_CHARGE | ...
    charge_code: str | None
    quoted_minor: int | None  # None = not present on the quote
    invoiced_minor: int | None  # None = not present on the invoice
    variance_minor: int | None
    note: str = ""


@dataclass
class Case:
    case_id: str
    seed: int
    error_kind: str  # CLEAN | ROUNDING_NOISE | OVERCHARGE | ...
    quote: QuoteTruth
    invoice: InvoiceTruth
    expected: list[ExpectedDiscrepancy]
    quote_format: str  # "pdf" | "xlsx" | "eml"
    invoice_format: str  # "pdf" | "xlsx"
    prompt_injection: bool  # remarks contain a hostile instruction (see design doc section 10)
    injection_text: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        # default=str turns dates into ISO "2026-09-14", which is what we want.
        return json.dumps(asdict(self), indent=2, default=str)
