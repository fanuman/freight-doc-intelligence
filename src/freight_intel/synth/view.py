"""Turns a ground-truth Case into a 'document view': the exact strings a human
would see on the page, before any file format is involved.

Keeping this separate from the renderers means PDF, Excel and email all show the
SAME content, and the messiness (labels, number styles, date styles) lives in
one place. The renderers only decide how to draw it.
"""
from dataclasses import dataclass

from freight_intel.synth import domain
from freight_intel.synth.records import Case

# Field captions differ per carrier (indexed by carrier.label_pack).
META_LABELS = (
    {"quote_no": "Quote No.", "invoice_no": "Invoice No.", "quote_date": "Date", "invoice_date": "Date",
     "valid": "Valid until", "origin": "Port of Loading", "destination": "Port of Discharge",
     "equipment": "Equipment", "incoterm": "Incoterm", "currency": "Currency", "quote_ref": "Quote Ref."},
    {"quote_no": "Offer Reference", "invoice_no": "Rechnungsnr.", "quote_date": "Datum", "invoice_date": "Datum",
     "valid": "Valid to", "origin": "Origin", "destination": "Destination",
     "equipment": "Container", "incoterm": "Incoterms", "currency": "Currency", "quote_ref": "Your offer"},
    {"quote_no": "Quote #", "invoice_no": "Invoice #", "quote_date": "Issued", "invoice_date": "Issued",
     "valid": "Expires", "origin": "From", "destination": "To",
     "equipment": "Cntr Type", "incoterm": "Terms", "currency": "Curr.", "quote_ref": "Ref Quote"},
    {"quote_no": "Reference", "invoice_no": "Invoice Number", "quote_date": "Quote Date", "invoice_date": "Invoice Date",
     "valid": "Valid Through", "origin": "POL", "destination": "POD",
     "equipment": "Size/Type", "incoterm": "Inco", "currency": "Ccy", "quote_ref": "Quote Reference"},
)

TOTAL_LABELS = ("Total", "Total / Gesamt", "Grand Total", "Total Payable")

EQUIPMENT_DISPLAY = {
    "20GP": ("20GP", "20' Dry", "20DC", "1 x 20GP"),
    "40GP": ("40GP", "40' Dry", "40DC", "1 x 40GP"),
    "40HC": ("40HC", "40' High Cube", "40HQ", "1 x 40HC"),
}

ADDRESS = "1 Example Quay, Testville - fictional company, synthetic test data"


@dataclass
class DocumentView:
    kind: str  # "quote" | "invoice"
    carrier: domain.CarrierProfile
    title: str
    meta: list[tuple[str, str]]
    columns: list[str]
    rows: list[list[str]]
    total: list[str]  # same width as columns
    remarks: list[str]
    footer: str
    amount_col: int  # index of the amount column (right-aligned)


def _port(code: str, pack: int) -> str:
    name = domain.PORTS[code]
    if pack == 0:
        return f"{name} ({code})"
    if pack == 3:
        return code
    return name


def _table(carrier, charges, currency, total_minor):
    """Rows differ by layout: 'detailed' puts the currency in its own column."""
    pack = carrier.label_pack
    total_label = TOTAL_LABELS[pack]
    if carrier.layout == "detailed":
        columns = ["Charge", "Basis", "Currency", "Amount"]
        rows = [
            [c.raw_label, domain.CHARGE_BASIS.get(c.code, "per container"), currency,
             domain.format_amount(c.amount_minor, carrier.number_style)]
            for c in charges
        ]
        total = [total_label, "", currency, domain.format_amount(total_minor, carrier.number_style)]
        return columns, rows, total, 3
    columns = ["Description", "Amount"] if carrier.layout == "simple" else ["Item", "Amount"]
    rows = [
        [c.raw_label,
         domain.format_money(c.amount_minor, currency, carrier.number_style, carrier.currency_style)]
        for c in charges
    ]
    total = [total_label,
             domain.format_money(total_minor, currency, carrier.number_style, carrier.currency_style)]
    return columns, rows, total, 1


def build_view(case: Case, kind: str) -> DocumentView:
    carrier = next(c for c in domain.CARRIERS if c.carrier_id == case.quote.carrier_id)
    pack = carrier.label_pack
    labels = META_LABELS[pack]
    fmt = lambda d: domain.format_date(d, carrier.date_format)  # noqa: E731

    if kind == "quote":
        q = case.quote
        meta = [
            (labels["quote_no"], q.quote_ref),
            (labels["quote_date"], fmt(q.issued_on)),
            (labels["valid"], fmt(q.valid_until)),
            (labels["origin"], _port(q.origin, pack)),
            (labels["destination"], _port(q.destination, pack)),
            (labels["equipment"], EQUIPMENT_DISPLAY[q.container_type][pack]),
            (labels["incoterm"], q.incoterm),
            (labels["currency"], q.currency),
        ]
        columns, rows, total, amount_col = _table(carrier, q.charges, q.currency, q.total_minor)
        remarks = [
            f"Rates are valid until {fmt(q.valid_until)} and subject to space and equipment availability.",
            "Rates exclude local charges at destination unless stated above.",
        ]
        title = carrier.quote_title
    else:
        i = case.invoice
        meta = [(labels["invoice_no"], i.invoice_no), (labels["invoice_date"], fmt(i.invoice_date))]
        if i.quote_ref:
            meta.append((labels["quote_ref"], i.quote_ref))
        meta += [
            (labels["origin"], _port(i.origin, pack)),
            (labels["destination"], _port(i.destination, pack)),
            (labels["equipment"], EQUIPMENT_DISPLAY[i.container_type][pack]),
            (labels["currency"], i.currency),
        ]
        columns, rows, total, amount_col = _table(
            carrier, i.charges, i.currency, i.stated_total_minor)
        remarks = [
            "Payment due within 30 days of invoice date.",
            "Bank: Example Bank, IBAN XX00 0000 0000 0000 0000 (fictional).",
        ]
        if case.prompt_injection:
            remarks.append(case.injection_text)  # hostile text hidden among normal remarks
        title = carrier.invoice_title

    return DocumentView(kind, carrier, title, meta, columns, rows, total, remarks, ADDRESS, amount_col)
