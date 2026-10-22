// Every call to the backend goes through this file, so the token header, the error handling and the URL
// prefix exist in exactly one place. Pages and components never use fetch() themselves.

import { clearToken, getToken, setToken } from "./auth";
import type {
  DocumentDetail,
  DocumentSummary,
  MeResponse,
  ReconcileResponse,
  ReviewDecision,
  ReviewResponse,
  TokenResponse,
  UploadResponse,
} from "./types";

const BASE = "/api"; // next.config.ts forwards this to the FastAPI server

export class ApiError extends Error {
  status: number; // 0 = the server could not be reached at all

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** A sentence that is safe to show a person, whatever was thrown. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

// FastAPI sends {"detail": "text"} for errors we raise, and {"detail": [{"msg": "..."}]} when the request
// itself does not match the schema.
function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: { msg?: unknown }) => (typeof item?.msg === "string" ? item.msg : ""))
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (authenticated) {
    const token = getToken();
    if (!token) throw new ApiError(401, "Please sign in");
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is the API running?");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401 && authenticated) clearToken(); // the token expired or is invalid
    // When the API is down, the Next.js proxy answers with a plain-text 500: no JSON, so no "detail".
    const fallback =
      response.status >= 500
        ? `The server did not answer properly (${response.status}). Is the API running?`
        : `The request failed (${response.status})`;
    throw new ApiError(response.status, describe(body?.detail, fallback));
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown, authenticated = true): Promise<T> {
  return request<T>(
    path,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    authenticated,
  );
}

// --- sign in -----------------------------------------------------------------------------------------

export async function signIn(email: string, password: string): Promise<void> {
  const token = await postJson<TokenResponse>("/auth/login", { email, password }, false);
  setToken(token.access_token);
}

export async function signUp(companyName: string, email: string, password: string): Promise<void> {
  const token = await postJson<TokenResponse>(
    "/auth/register",
    { company_name: companyName, email, password },
    false,
  );
  setToken(token.access_token);
}

export function signOut(): void {
  clearToken();
}

export function getMe(): Promise<MeResponse> {
  return request<MeResponse>("/me");
}

// --- documents ---------------------------------------------------------------------------------------

export function listDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/documents?limit=50");
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${encodeURIComponent(id)}`);
}

export function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file); // the field name must match the parameter name in the FastAPI route
  // No Content-Type header here: the browser adds it, including the boundary that separates the parts.
  return request<UploadResponse>("/documents", { method: "POST", body: form });
}

export function submitReview(id: string, decision: ReviewDecision): Promise<ReviewResponse> {
  // Who is reviewing is never sent: the server takes it from the login token.
  return postJson<ReviewResponse>(`/documents/${encodeURIComponent(id)}/review`, decision);
}

export function reconcileDocument(id: string): Promise<ReconcileResponse> {
  return postJson<ReconcileResponse>(`/documents/${encodeURIComponent(id)}/reconcile`, {});
}
