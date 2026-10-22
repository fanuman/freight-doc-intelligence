"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { errorMessage, isUnauthorized, submitReview } from "@/lib/api";
import type { PendingReview, ReviewDecision, ReviewResponse } from "@/lib/types";
import { CheckIcon, PencilIcon, XIcon } from "./Icons";
import { IssueList } from "./IssueList";

type Mode = "approve" | "correct" | "reject";

const MODES: { value: Mode; title: string; help: string; icon: ReactNode; button: string }[] = [
  {
    value: "approve",
    title: "Approve",
    help: "The reading is a faithful copy of the document, even if the document itself has a problem.",
    icon: <CheckIcon size={22} />,
    button: "Approve document",
  },
  {
    value: "correct",
    title: "Correct",
    help: "Fix the values below. The same checks run again on what you send.",
    icon: <PencilIcon size={22} />,
    button: "Save correction",
  },
  {
    value: "reject",
    title: "Reject",
    help: "Do not use this document.",
    icon: <XIcon size={22} />,
    button: "Reject document",
  },
];

/**
 * The question a paused document is waiting on, and the three ways to answer it.
 *
 * The page gives this component a `key` built from the question, so when the server asks again after a
 * correction that still has errors, the panel starts over with the new values instead of showing old text.
 */
export function ReviewPanel({
  documentId,
  pending,
  onDone,
}: {
  documentId: string;
  pending: PendingReview;
  onDone: (result: ReviewResponse, action: Mode) => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("approve");
  const [note, setNote] = useState("");
  const [json, setJson] = useState(() => JSON.stringify(pending.extraction, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasErrors = pending.issues.some((issue) => issue.severity === "error");
  // The server enforces this too; the form just saves a round trip.
  const needsNote = mode === "approve" && hasErrors && note.trim() === "";
  const current = MODES.find((item) => item.value === mode) ?? MODES[0];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const decision: ReviewDecision = { action: mode, note: note.trim() };
    if (mode === "correct") {
      try {
        const parsed: unknown = JSON.parse(json);
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
          setError("The corrected values must be a JSON object, like the one shown.");
          return;
        }
        decision.extraction = parsed as Record<string, unknown>;
      } catch {
        setError("That is not valid JSON. Check for a missing quote, comma or bracket.");
        return;
      }
    }

    setBusy(true);
    try {
      onDone(await submitReview(documentId, decision), mode);
    } catch (err) {
      if (isUnauthorized(err)) router.replace("/login");
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel review">
      <div className="hazard" aria-hidden="true" />
      <div className="review-body">
        <h2>This document needs a person</h2>
        <p>
          The checks still found problems after {pending.attempts} {pending.attempts === 1 ? "try" : "tries"}. Decide what
          should happen. Your name is saved with the decision.
        </p>
        {pending.error && (
          <p className="callout callout-bad" role="alert">
            The last answer could not be used: {pending.error}
          </p>
        )}
        <IssueList issues={pending.issues} />

        <form onSubmit={handleSubmit}>
          <fieldset className="choices">
            <legend>Your decision</legend>
            {MODES.map((item) => (
              <label key={item.value} className={`choice choice-${item.value}${mode === item.value ? " choice-selected" : ""}`}>
                <input
                  type="radio"
                  name="mode"
                  value={item.value}
                  checked={mode === item.value}
                  onChange={() => setMode(item.value)}
                  className="sr-only"
                />
                <span className="choice-icon">{item.icon}</span>
                <span className="choice-title">{item.title}</span>
                <span className="choice-help">{item.help}</span>
              </label>
            ))}
          </fieldset>

          <div className={mode === "correct" ? "reveal reveal-open" : "reveal"} aria-hidden={mode !== "correct"}>
            <div className="reveal-inner">
              <label htmlFor="corrected">Corrected values (JSON, every field present)</label>
              <textarea
                id="corrected"
                className="code"
                rows={14}
                spellCheck={false}
                tabIndex={mode === "correct" ? 0 : -1}
                value={json}
                onChange={(event) => setJson(event.target.value)}
              />
            </div>
          </div>

          <label htmlFor="note">
            Note {mode === "approve" && hasErrors ? "(required: say why you approve despite the errors)" : "(optional)"}
          </label>
          <textarea id="note" rows={3} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} />

          {error && (
            <p className="callout callout-bad" role="alert">
              {error}
            </p>
          )}
          <div className="review-actions">
            <button type="submit" className={mode === "reject" ? "btn btn-danger" : "btn btn-primary"} disabled={busy || needsNote}>
              {busy ? "Saving…" : current.button}
            </button>
            {needsNote && <span className="muted">Add a note to approve.</span>}
          </div>
        </form>
      </div>
    </section>
  );
}
