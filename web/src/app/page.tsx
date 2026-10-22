"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ChevronRightIcon, ContainerIcon, SearchIcon } from "@/components/Icons";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadForm } from "@/components/UploadForm";
import { listDocuments } from "@/lib/api";
import { fileKind, formatDateTime, formatRelative, isBusy, sentence } from "@/lib/format";
import type { DocumentSummary } from "@/lib/types";
import { usePolled } from "@/lib/usePolled";

// Defined outside the component so it is the same function on every render (usePolled needs that).
const anyBusy = (rows: DocumentSummary[]) => rows.some((row) => isBusy(row.status));

type Filter = "all" | "working" | "review" | "done" | "stopped";

const FILTERS: { key: Filter; label: string; matches: (status: string) => boolean }[] = [
  { key: "all", label: "All documents", matches: () => true },
  { key: "working", label: "Being read", matches: isBusy },
  { key: "review", label: "Need review", matches: (status) => status === "needs_review" },
  { key: "done", label: "Processed", matches: (status) => status === "processed" },
  { key: "stopped", label: "Failed or rejected", matches: (status) => status === "failed" || status === "rejected" },
];

export default function DocumentsPage() {
  const router = useRouter();
  const fetchDocuments = useCallback(() => listDocuments(), []);
  const { data: documents, error, reload } = usePolled(fetchDocuments, anyBusy);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const active = FILTERS.find((item) => item.key === filter) ?? FILTERS[0];
  const needle = query.trim().toLowerCase();
  const visible = (documents ?? []).filter(
    (doc) => active.matches(doc.status) && (needle === "" || doc.filename.toLowerCase().includes(needle)),
  );
  const working = documents !== null && anyBusy(documents);

  return (
    // One wrapper element, so the header and the page are always created and placed together, in this order.
    <div>
      <AppHeader />
      <main className="page">
        <div className="page-head">
          <h1>Documents</h1>
          <p className="muted">Upload a quote and its invoice. FreightLens reads both, checks the numbers, and lists every difference.</p>
        </div>

        <UploadForm onUploaded={reload} />

        {error && (
          <p className="callout callout-bad" role="alert">
            {error}{" "}
            <button type="button" className="text-button" onClick={reload}>
              Try again
            </button>
          </p>
        )}

        {documents === null && !error && (
          <div className="ledger" aria-busy="true" aria-label="Loading documents">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton-row">
                <span className="skeleton skeleton-icon" />
                <span className="skeleton skeleton-line" />
              </div>
            ))}
          </div>
        )}

        {documents !== null && (
          <>
            <div className="strip" role="group" aria-label="Filter by status">
              {FILTERS.map((item) => {
                const count = documents.filter((doc) => item.matches(doc.status)).length;
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={filter === item.key ? "strip-cell strip-selected" : "strip-cell"}
                    aria-pressed={filter === item.key}
                    onClick={() => setFilter(item.key)}
                  >
                    <span className="strip-number">{count}</span>
                    <span className="strip-label">{item.label}</span>
                  </button>
                );
              })}
            </div>

            <div className="toolbar">
              <label className="search">
                <SearchIcon size={18} />
                <span className="sr-only">Search by file name</span>
                <input
                  type="search"
                  placeholder="Search by file name"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              {working && (
                <span className="live" role="status">
                  <span className="live-dot" aria-hidden="true" /> Reading documents. This list updates by itself.
                </span>
              )}
            </div>

            {visible.length === 0 ? (
              <div className="empty">
                <ContainerIcon size={44} />
                {documents.length === 0 ? (
                  <>
                    <strong>Nothing here yet</strong>
                    <span className="muted">Drop your first quote or invoice on the dock above.</span>
                  </>
                ) : (
                  <>
                    <strong>No documents match</strong>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => {
                        setFilter("all");
                        setQuery("");
                      }}
                    >
                      Clear the filter and search
                    </button>
                  </>
                )}
              </div>
            ) : (
              <div className="ledger table-wrap">
                <table className="grid grid-rows">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th className="col-type">Type</th>
                      <th>Status</th>
                      <th className="col-time">Uploaded</th>
                      <th className="col-go">
                        <span className="sr-only">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((doc) => (
                      <tr
                        key={doc.id}
                        className="row-link"
                        onClick={(event) => {
                          if ((event.target as HTMLElement).closest("a")) return; // the link does its own navigation
                          router.push(`/documents/${doc.id}`);
                        }}
                      >
                        <td>
                          <span className="file-cell">
                            <span className={`file-tile file-${fileKind(doc.filename).toLowerCase()}`}>{fileKind(doc.filename)}</span>
                            <Link href={`/documents/${doc.id}`} className="file-name">
                              {doc.filename}
                            </Link>
                          </span>
                        </td>
                        <td className="col-type">{sentence(doc.doc_type)}</td>
                        <td>
                          <StatusBadge status={doc.status} />
                        </td>
                        <td className="col-time" title={formatDateTime(doc.created_at)}>
                          {formatRelative(doc.created_at)}
                        </td>
                        <td className="col-go">
                          <ChevronRightIcon size={18} className="go" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {documents.length >= 50 && <p className="muted fine">Showing the latest 50 documents.</p>}
          </>
        )}
      </main>
    </div>
  );
}
