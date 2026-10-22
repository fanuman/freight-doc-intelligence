// The shapes the FastAPI backend returns (src/freight_intel/schemas/documents.py and schemas/auth.py, user.py).
// They are written out by hand, so when a backend schema changes, change it here too.
// Money is always an integer in minor units (cents), with the currency next to it.

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface MeResponse {
  user_id: string;
  email: string;
  role: string;
  tenant_id: string;
  tenant_name: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  doc_type: string; // unknown until it has been read, then quote | invoice | rate_sheet
  status: string; // uploaded | processing | needs_review | processed | rejected | failed
  created_at: string; // ISO date-time
}

export interface Issue {
  code: string;
  message: string;
  severity: string; // "error" | "warning"
  field: string | null;
}

export interface Charge {
  position: number;
  code: string; // canonical charge name, "OTHER" when the label was not recognised
  label: string; // exactly as printed
  amount_minor: number | null; // null = the amount could not be read
  known: boolean;
}

export interface Extraction {
  id: string;
  status: string; // ok | needs_review | reviewed
  doc_type: string;
  reference: string | null;
  quote_reference: string | null;
  doc_date: string | null;
  valid_until: string | null;
  currency: string | null;
  origin: string | null;
  destination: string | null;
  equipment: string | null;
  total_minor: number | null; // the total as PRINTED on the document
  issues: Issue[];
  charges: Charge[];
}

export interface Discrepancy {
  position: number;
  type: string;
  charge_code: string | null;
  label: string | null;
  quoted_minor: number | null;
  invoiced_minor: number | null;
  variance_minor: number | null;
  note: string;
  explanation: string | null;
}

export interface Reconciliation {
  id: string;
  quote_document_id: string;
  match_method: string;
  currency: string | null;
  total_variance_minor: number | null;
  status: string; // clean | has_discrepancies
  discrepancies: Discrepancy[];
}

export interface ReviewRecord {
  action: string; // approve | correct | reject
  note: string;
  reviewer_id: string;
  created_at: string;
  corrected: boolean; // true when this decision replaced the extracted values
}

// What a person must answer while a document is paused (pipeline/review.py: build_review_request).
// `extraction` is in the model's text shape: the same shape a correction must be sent back in.
export interface PendingReview {
  doc_type: string;
  extraction: Record<string, unknown>;
  issues: Issue[];
  attempts: number;
  error?: string; // set when the last answer could not be used
}

export interface DocumentDetail extends DocumentSummary {
  extraction: Extraction | null;
  reconciliation: Reconciliation | null;
  reviews: ReviewRecord[];
  pending_review: PendingReview | null;
}

export interface UploadResponse {
  id: string;
  status: string;
}

export interface ReviewDecision {
  action: "approve" | "correct" | "reject";
  note: string;
  extraction?: Record<string, unknown>; // "correct" only: the whole corrected extraction
}

export interface ReviewResponse {
  document_status: string;
  question: PendingReview | null; // set while the person is asked again; null when the review is over
}

export interface ReconcileResponse {
  // reconciled | reference_not_found | ambiguous | no_candidate | route_unknown | unreadable_amount
  status: string;
  reconciliation_id: string | null;
  discrepancy_count: number;
}
