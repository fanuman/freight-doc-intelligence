import { statusTone } from "@/lib/format";

const LABELS: Record<string, string> = {
  uploaded: "Received",
  processing: "Reading",
  needs_review: "Needs review",
  processed: "Processed",
  rejected: "Rejected",
  failed: "Failed",
};

/**
 * The document's status as an ink stamp, like the ones clerks press on paperwork.
 * The stamp lands with a small thud whenever the status changes: the page gives it `key={status}`, so React
 * builds a new element (and replays the animation) exactly when the status is different.
 */
export function StatusStamp({ status }: { status: string }) {
  return <span className={`stamp stamp-${statusTone(status)}`}>{LABELS[status] ?? status.replace(/_/g, " ")}</span>;
}
