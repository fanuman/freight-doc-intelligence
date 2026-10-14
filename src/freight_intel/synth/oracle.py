"""A pretend LLM that always reads the document perfectly.

Why it exists: to test the pipeline and the evaluation harness WITHOUT calling
OpenAI. If the harness scores the oracle at 100%, the harness is sound; if a
deliberately damaged oracle scores lower, the metrics really measure something.
It is test tooling, like the rest of synth/.
"""
from collections.abc import Callable

from freight_intel.pipeline.schemas import (
    DocTypeResult,
    InvoiceExtraction,
    QuoteExtraction,
    RawCharge,
)
from freight_intel.synth import domain
from freight_intel.synth.records import Case
from freight_intel.synth.view import EQUIPMENT_DISPLAY, _port, build_view


def perfect_extraction(case: Case, kind: str):
    """What a flawless reader would copy off the page, as raw text."""
    view = build_view(case, kind)
    carrier, pack = view.carrier, view.carrier.label_pack
    charges = [RawCharge(label=row[0], amount_text=row[view.amount_col]) for row in view.rows]
    total_text = view.total[view.amount_col]
    fmt = lambda d: domain.format_date(d, carrier.date_format)  # noqa: E731

    if kind == "quote":
        q = case.quote
        return QuoteExtraction(
            reference=q.quote_ref, issued_text=fmt(q.issued_on), valid_until_text=fmt(q.valid_until),
            origin_text=_port(q.origin, pack), destination_text=_port(q.destination, pack),
            equipment_text=EQUIPMENT_DISPLAY[q.container_type][pack], incoterm=q.incoterm,
            currency_text=q.currency, charges=charges, total_text=total_text)
    i = case.invoice
    return InvoiceExtraction(
        invoice_number=i.invoice_no, invoice_date_text=fmt(i.invoice_date), quote_reference=i.quote_ref,
        origin_text=_port(i.origin, pack), destination_text=_port(i.destination, pack),
        equipment_text=EQUIPMENT_DISPLAY[i.container_type][pack], currency_text=i.currency,
        charges=charges, total_text=total_text)


class OracleLLM:
    """Implements the same `extract` method as OpenAILLM, but cheats by looking
    the document up in the known dataset (it finds which case's number is in the text)."""

    def __init__(self, cases: list[Case], corrupt: Callable | None = None, fix_when_hinted: bool = False):
        self.cases = cases
        self.corrupt = corrupt  # optional: damage the answer to simulate a bad model
        # simulate a model that misreads once but reads correctly when told a check failed
        self.fix_when_hinted = fix_when_hinted
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.approx_cost_usd = 0.0

    def _find(self, text: str) -> tuple[Case, str]:
        for case in self.cases:
            if case.invoice.invoice_no in text:
                return case, "invoice"
        for case in self.cases:
            if case.quote.quote_ref in text:
                return case, "quote"
        raise LookupError("document not found in the oracle's dataset")

    def extract(self, schema, system: str, user: str):
        self.calls += 1
        case, kind = self._find(user)
        if schema is DocTypeResult:
            return DocTypeResult(doc_type=kind)
        result = perfect_extraction(case, kind)
        hinted = "failed an automatic check" in user
        if self.corrupt and not (self.fix_when_hinted and hinted):
            return self.corrupt(result, case, kind)
        return result
