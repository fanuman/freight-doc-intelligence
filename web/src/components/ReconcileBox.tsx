"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorMessage, isUnauthorized, reconcileDocument } from "@/lib/api";
import { SigmaIcon } from "./Icons";

// Not finding exactly one safe quote is an outcome, not an error (the server answers 200), so each one
// gets a plain sentence.
const OUTCOMES: Record<string, string> = {
  reconciled: "Compared with the quote. The findings are below.",
  reference_not_found: "The invoice cites a quote that has not been uploaded (or is not unique). Upload that quote first.",
  route_unknown: "The invoice names no quote and its ports, container or date could not be read, so no quote can be matched safely.",
  ambiguous: "More than one quote fits this invoice's route, so none was chosen. The invoice would need to cite its quote.",
  no_candidate: "No quote for this route has been uploaded yet.",
  unreadable_amount: "A charge amount could not be read, so the comparison was not made.",
};

/** The button that compares an invoice with its quote, and the sentence that says what came of it. */
export function ReconcileBox({
  documentId,
  hasResult,
  onDone,
}: {
  documentId: string;
  hasResult: boolean;
  onDone: () => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; good: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const outcome = await reconcileDocument(documentId);
      setMessage({ text: OUTCOMES[outcome.status] ?? `Result: ${outcome.status}`, good: outcome.status === "reconciled" });
      onDone();
    } catch (err) {
      if (isUnauthorized(err)) router.replace("/login");
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-action">
      <div className="panel-action-text">
        <h2>Compare with the quote</h2>
        <p className="muted">
          Finds the quote this invoice belongs to and lists every difference. Only readings that passed the checks, or
          that a person reviewed, are used.
        </p>
      </div>
      <button type="button" className="btn btn-primary" onClick={handleClick} disabled={busy}>
        <SigmaIcon size={18} />
        {busy ? "Comparing…" : hasResult ? "Compare again" : "Compare with quote"}
      </button>
      {message && <p className={message.good ? "callout callout-good panel-action-note" : "callout panel-action-note"}>{message.text}</p>}
      {error && (
        <p className="callout callout-bad panel-action-note" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
