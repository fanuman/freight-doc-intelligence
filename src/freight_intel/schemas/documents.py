"""Request/response shapes for the documents endpoints.

The services hand back plain dictionaries; FastAPI checks them against these schemas on the way out, so the
shape of every response is written down in one place (and shows up in the /docs page). Money is always an
integer in minor units (cents), with the currency alongside.
"""
import json
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CORRECTION_CHARS = 100_000  # a corrected extraction is a few KB; this only stops abuse


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    doc_type: str  # unknown until it has been read, then quote | invoice | rate_sheet
    status: str  # uploaded | processing | needs_review | processed | rejected | failed
    created_at: datetime


class UploadResponse(BaseModel):
    id: uuid.UUID
    status: str


class ChargeOut(BaseModel):
    position: int
    code: str  # the canonical charge name, "OTHER" when the label was not recognised
    label: str  # exactly as printed
    amount_minor: int | None  # None = the amount could not be read
    known: bool


class ExtractionOut(BaseModel):
    id: uuid.UUID
    status: str  # ok | needs_review | reviewed
    doc_type: str
    reference: str | None
    quote_reference: str | None
    doc_date: date | None
    valid_until: date | None
    currency: str | None
    origin: str | None
    destination: str | None
    equipment: str | None
    total_minor: int | None  # the total as PRINTED on the document
    issues: list[dict]
    charges: list[ChargeOut]


class DiscrepancyOut(BaseModel):
    position: int
    type: str
    charge_code: str | None
    label: str | None
    quoted_minor: int | None
    invoiced_minor: int | None
    variance_minor: int | None
    note: str
    explanation: str | None


class ReconciliationOut(BaseModel):
    id: uuid.UUID
    quote_document_id: uuid.UUID
    match_method: str
    currency: str | None
    total_variance_minor: int | None
    status: str  # clean | has_discrepancies
    discrepancies: list[DiscrepancyOut]


class ReviewOut(BaseModel):
    action: str
    note: str
    reviewer_id: uuid.UUID
    created_at: datetime
    corrected: bool  # True when this decision replaced the extracted values


class DocumentDetail(DocumentSummary):
    extraction: ExtractionOut | None
    reconciliation: ReconciliationOut | None
    reviews: list[ReviewOut]
    pending_review: dict | None  # what a person must answer; only while the status is needs_review


class ReviewRequest(BaseModel):
    # extra="forbid": a client that sends its own "reviewer" is told no, instead of being quietly ignored.
    # Who reviewed is always the logged-in user.
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "correct", "reject"]
    note: str = Field(default="", max_length=1000)
    extraction: dict | None = None  # "correct" only: the whole corrected extraction

    @field_validator("extraction")
    @classmethod
    def not_huge(cls, value: dict | None) -> dict | None:
        if value is not None and len(json.dumps(value)) > MAX_CORRECTION_CHARS:
            raise ValueError("the corrected extraction is too large")
        return value


class ReviewResponse(BaseModel):
    document_status: str
    question: dict | None  # set while the person is asked again; None when the review is over


class ReconcileResponse(BaseModel):
    # reconciled | reference_not_found | ambiguous | no_candidate | route_unknown | unreadable_amount
    status: str
    reconciliation_id: uuid.UUID | None
    discrepancy_count: int
