import { sentence, statusTone } from "@/lib/format";

// Plainer words for statuses whose raw names read oddly on their own (an extraction that is "ok").
const LABELS: Record<string, string> = {
  ok: "Checks passed",
  reviewed: "Reviewed by a person",
  clean: "No differences",
  has_discrepancies: "Differences found",
};

/** A small pill with a dot. A dot that pulses means the server is still working. The words carry the meaning, the colour only helps. */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`pill pill-${statusTone(status)}`}>
      <span className="pill-dot" aria-hidden="true" />
      {LABELS[status] ?? sentence(status)}
    </span>
  );
}
