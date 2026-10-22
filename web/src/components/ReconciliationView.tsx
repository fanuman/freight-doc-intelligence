"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { formatMoney, formatVariance, sentence } from "@/lib/format";
import type { Reconciliation } from "@/lib/types";
import { CheckIcon, InfoIcon } from "./Icons";

// The two ways the server pairs an invoice with its quote (pipeline/reconcile.py). A comparison is only saved when
// one of them worked; when no quote can be found the server answers with a message and saves nothing.
const MATCH: Record<string, { label: string; short: string; why: string }> = {
  reference: {
    label: "Matched by quote number",
    short: "The invoice names its quote",
    why: "The invoice names the quote it belongs to, so FreightLens looked for the quote with exactly that number. If no quote with that number had been uploaded, nothing would be guessed: the comparison would stop and say so.",
  },
  route: {
    label: "Matched by route",
    short: "Same route and container type",
    why: "The invoice does not name a quote number, so FreightLens looked for a quote with the same origin, destination and container type, dated on or before the invoice. Exactly one quote fit. If none or several had fit, it would have stopped instead of guessing.",
  },
};

/** The invoice compared with its quote. Every number here was computed by code; the wording is only an explanation. */
export function ReconciliationView({ reconciliation }: { reconciliation: Reconciliation }) {
  const { currency, discrepancies } = reconciliation;
  const difference = reconciliation.total_variance_minor ?? 0;
  const tone = difference === 0 ? "even" : difference > 0 ? "over" : "under";
  const [explaining, setExplaining] = useState(false);
  const noteId = useId();
  const match = MATCH[reconciliation.match_method] ?? {
    label: sentence(reconciliation.match_method),
    short: "How the quote was found",
    why: "",
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Invoice versus quote</h2>
        <Link href={`/documents/${reconciliation.quote_document_id}`} className="text-link">
          Open the quote
        </Link>
      </div>

      <div className="verdict">
        <div className={`verdict-figure verdict-${tone}`}>
          <span className="verdict-label">Total difference</span>
          <span className="verdict-number">{formatVariance(reconciliation.total_variance_minor, currency)}</span>
          <span className="verdict-hint">
            {tone === "even" ? "Invoice and quote agree" : tone === "over" ? "Invoiced above the quote" : "Invoiced below the quote"}
          </span>
        </div>
        <div className="verdict-side">
          <span className="verdict-count">{discrepancies.length}</span>
          <span className="muted">{discrepancies.length === 1 ? "finding" : "findings"}</span>
        </div>
        <div className="verdict-side">
          <span className="verdict-method">
            {match.label}
            {match.why && (
              <button
                type="button"
                className="info-button"
                aria-expanded={explaining}
                aria-controls={noteId}
                aria-label="Why was the quote matched this way?"
                onClick={() => setExplaining((open) => !open)}
              >
                <InfoIcon size={18} />
              </button>
            )}
          </span>
          <span className="muted">{match.short}</span>
        </div>
      </div>

      {match.why && (
        <div className={explaining ? "reveal reveal-open" : "reveal"}>
          <div className="reveal-inner">
            <p className="callout match-note" id={noteId}>
              <strong>{match.label}.</strong> {match.why}{" "}
              <span className="muted">This match is made by fixed rules in code, not by the AI model.</span>
            </p>
          </div>
        </div>
      )}

      {discrepancies.length === 0 ? (
        <p className="empty-line">
          <CheckIcon size={18} /> No differences found.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Finding</th>
                <th>Charge</th>
                <th className="num">Quoted</th>
                <th className="num">Invoiced</th>
                <th className="num">Difference</th>
              </tr>
            </thead>
            <tbody>
              {discrepancies.map((item) => (
                <tr key={item.position}>
                  <td>
                    <strong className="finding">{sentence(item.type.toLowerCase())}</strong>
                    <div className="muted">{item.explanation ?? item.note}</div>
                  </td>
                  <td>{item.label ?? item.charge_code ?? "Whole invoice"}</td>
                  <td className="num">{formatMoney(item.quoted_minor, currency)}</td>
                  <td className="num">{formatMoney(item.invoiced_minor, currency)}</td>
                  <td className={`num ${(item.variance_minor ?? 0) > 0 ? "amount-over" : "amount-under"}`}>
                    {formatVariance(item.variance_minor, currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
