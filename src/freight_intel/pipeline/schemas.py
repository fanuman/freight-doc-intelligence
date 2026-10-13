"""What the LLM must return. Every field is TEXT copied off the page.

Note the names: `amount_text`, `issued_text`. The model is never asked to turn
"2.190,00" into a number or "10.08.2026" into a date. It copies; money.py
converts. That keeps arithmetic and date logic out of the model's hands.

No default values on purpose: OpenAI's strict structured-output mode wants every
field present, and `str | None` lets the model say "this isn't on the page".
"""
from typing import Literal

from pydantic import BaseModel, Field


class DocTypeResult(BaseModel):
    doc_type: Literal["quote", "invoice", "rate_sheet", "unknown"] = Field(
        description="quote = a price offer before shipping; invoice = a bill for a shipment; "
                    "rate_sheet = a table of many routes/prices; unknown = anything else"
    )


class RawCharge(BaseModel):
    label: str = Field(description="Only the charge name as printed, e.g. 'O/F' or 'Terminal Handling - Origin'. "
                                                  "Do not append a basis/unit column such as 'per container' or 'per B/L'.")
    amount_text: str = Field(description="The amount exactly as printed for this charge, e.g. '2.190,00' or '$195.01'")


class QuoteExtraction(BaseModel):
    reference: str | None = Field(description="The quote number / offer reference")
    issued_text: str | None = Field(description="The date the quote was issued, exactly as printed")
    valid_until_text: str | None = Field(description="The date until which the quote is valid, exactly as printed")
    origin_text: str | None = Field(description="Port of loading / origin, exactly as printed")
    destination_text: str | None = Field(description="Port of discharge / destination, exactly as printed")
    equipment_text: str | None = Field(description="Container type, exactly as printed")
    incoterm: str | None = Field(description="Incoterm such as FOB or CIF, if printed")
    currency_text: str | None = Field(description="The currency of the document as printed (code or symbol)")
    charges: list[RawCharge] = Field(description="One entry per charge line. Do NOT include the total row.")
    total_text: str | None = Field(description="The total amount exactly as printed, if there is a total row")


class InvoiceExtraction(BaseModel):
    invoice_number: str | None = Field(description="The invoice number")
    invoice_date_text: str | None = Field(description="The invoice date, exactly as printed")
    quote_reference: str | None = Field(description="The quote / offer reference the invoice cites, if any")
    origin_text: str | None = Field(description="Port of loading / origin, exactly as printed")
    destination_text: str | None = Field(description="Port of discharge / destination, exactly as printed")
    equipment_text: str | None = Field(description="Container type, exactly as printed")
    currency_text: str | None = Field(description="The currency of the document as printed (code or symbol)")
    charges: list[RawCharge] = Field(description="One entry per charge line. Do NOT include the total row.")
    total_text: str | None = Field(description="The total amount exactly as printed, if there is a total row")
