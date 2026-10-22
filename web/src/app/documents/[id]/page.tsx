"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ExtractionView } from "@/components/ExtractionView";
import { ArrowLeftIcon, ClockIcon } from "@/components/Icons";
import { ReconcileBox } from "@/components/ReconcileBox";
import { ReconciliationView } from "@/components/ReconciliationView";
import { ReviewPanel } from "@/components/ReviewPanel";
import { RouteProgress } from "@/components/RouteProgress";
import { StatusStamp } from "@/components/StatusStamp";
import { Toast } from "@/components/Toast";
import { getDocument } from "@/lib/api";
import { fileKind, formatDateTime, formatRelative, humanize, isBusy, sentence } from "@/lib/format";
import type { DocumentDetail, ReviewResponse } from "@/lib/types";
import { usePolled } from "@/lib/usePolled";

const stillWorking = (doc: DocumentDetail) => isBusy(doc.status);

const VERBS = { approve: "Approved", correct: "Correction saved", reject: "Rejected" } as const;

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const fetchDocument = useCallback(() => getDocument(id), [id]);
  const { data: doc, error, reload } = usePolled(fetchDocument, stillWorking);
  const [notice, setNotice] = useState<{ id: number; text: string } | null>(null);
  const closeNotice = useCallback(() => setNotice(null), []);

  function handleReviewed(result: ReviewResponse, action: keyof typeof VERBS) {
    const text = result.question
      ? "Correction saved, but the checks still found problems. The corrected values are shown again."
      : `${VERBS[action]}. The document is now ${humanize(result.document_status)}.`;
    setNotice({ id: Date.now(), text });
    reload();
  }

  // An invoice can be compared with its quote once its reading is settled (it passed the checks, or a person reviewed it).
  const canReconcile =
    doc?.extraction?.doc_type === "invoice" && ["ok", "reviewed"].includes(doc.extraction.status);

  return (
    // One wrapper element, so the header and the page are always created and placed together, in this order.
    <div>
      <AppHeader />
      <main className="page">
        <Link href="/" className="back">
          <ArrowLeftIcon size={18} /> All documents
        </Link>

        {error && (
          <p className="callout callout-bad" role="alert">
            {error}{" "}
            <button type="button" className="text-button" onClick={reload}>
              Try again
            </button>
          </p>
        )}

        {doc === null && !error && (
          <div aria-busy="true" aria-label="Loading document">
            <div className="skeleton skeleton-title" />
            <div className="skeleton skeleton-block" />
          </div>
        )}

        {doc && (
          <>
            <div className="doc-head">
              <span className={`file-tile file-tile-large file-${fileKind(doc.filename).toLowerCase()}`}>{fileKind(doc.filename)}</span>
              <div className="doc-title">
                <h1>{doc.filename}</h1>
                <p className="doc-meta">
                  <span>{sentence(doc.doc_type)}</span>
                  <span title={formatDateTime(doc.created_at)}>
                    <ClockIcon size={16} /> Uploaded {formatRelative(doc.created_at)}
                  </span>
                </p>
              </div>
              <StatusStamp key={doc.status} status={doc.status} />
            </div>

            <RouteProgress status={doc.status} />

            {isBusy(doc.status) && <p className="callout">Reading the document. This page refreshes by itself.</p>}
            {doc.status === "failed" && (
              <p className="callout callout-bad">Reading this document failed. Uploading the file again is the way to retry.</p>
            )}
            {doc.status === "rejected" && <p className="callout callout-bad">A reviewer rejected this document.</p>}

            {doc.status === "needs_review" && doc.pending_review && (
              <ReviewPanel
                // A new question (after a correction that still had errors) gives a new key: the panel starts fresh.
                key={JSON.stringify(doc.pending_review)}
                documentId={doc.id}
                pending={doc.pending_review}
                onDone={handleReviewed}
              />
            )}
            {doc.status === "needs_review" && !doc.pending_review && (
              <p className="callout callout-bad">
                This document is waiting, but it has no open question: the review ended without a decision. Upload the file
                again to start over.
              </p>
            )}

            {doc.extraction && <ExtractionView extraction={doc.extraction} />}

            {canReconcile && <ReconcileBox documentId={doc.id} hasResult={doc.reconciliation !== null} onDone={reload} />}
            {doc.reconciliation && <ReconciliationView reconciliation={doc.reconciliation} />}

            {doc.reviews.length > 0 && (
              <section className="panel">
                <div className="panel-head">
                  <h2>Review history</h2>
                </div>
                <ol className="timeline">
                  {doc.reviews.map((review) => (
                    <li key={`${review.created_at}-${review.action}`} className={`timeline-item timeline-${review.action}`}>
                      <div className="timeline-head">
                        <strong>{VERBS[review.action as keyof typeof VERBS] ?? review.action}</strong>
                        {review.corrected && <span className="tag">values replaced</span>}
                        <span className="muted" title={formatDateTime(review.created_at)}>
                          {formatRelative(review.created_at)}
                        </span>
                      </div>
                      {review.note && <p className="timeline-note">{review.note}</p>}
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </>
        )}
      </main>
      {notice && <Toast key={notice.id} message={notice.text} onClose={closeNotice} />}
    </div>
  );
}
