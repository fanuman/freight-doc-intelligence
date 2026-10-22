import { CheckIcon, XIcon } from "./Icons";

type StopState = "done" | "current" | "attention" | "bad" | "todo";

interface Stop {
  label: string;
  state: StopState;
  note?: string; // a short line under the stop, only where something needs saying
}

const LABELS = ["Received", "Read", "Checked", "Settled"] as const;

/** Where a document is on its journey, from its status. Only the server's status is used; nothing is guessed. */
function stopsFor(status: string): Stop[] {
  const states: Record<string, [StopState, StopState, StopState, StopState]> = {
    uploaded: ["current", "todo", "todo", "todo"],
    processing: ["done", "current", "todo", "todo"],
    needs_review: ["done", "done", "done", "attention"],
    processed: ["done", "done", "done", "done"],
    rejected: ["done", "done", "done", "bad"],
    failed: ["done", "bad", "todo", "todo"],
  };
  const row = states[status] ?? ["todo", "todo", "todo", "todo"];
  const notes: Record<string, [number, string]> = {
    needs_review: [3, "Waiting for a person"],
    rejected: [3, "Rejected"],
    failed: [1, "Reading failed"],
  };
  return LABELS.map((label, index) => {
    const note = notes[status];
    return { label, state: row[index], note: note && note[0] === index ? note[1] : undefined };
  });
}

const STATE_TEXT: Record<StopState, string> = {
  done: "done",
  current: "in progress",
  attention: "needs attention",
  bad: "stopped",
  todo: "not reached",
};

/** The route line: four ports, filled in as the document travels. The line between ports fills smoothly when the status moves on. */
export function RouteProgress({ status }: { status: string }) {
  const stops = stopsFor(status);
  return (
    <ol className="route" aria-label="Progress of this document">
      {stops.map((stop) => (
        <li key={stop.label} className={`route-stop route-${stop.state}`} aria-current={stop.state === "current" ? "step" : undefined}>
          <span className="route-node">
            {stop.state === "done" && <CheckIcon size={12} />}
            {stop.state === "bad" && <XIcon size={12} />}
          </span>
          <span className="route-label">
            {stop.label}
            <span className="sr-only"> ({STATE_TEXT[stop.state]})</span>
          </span>
          {stop.note && <span className="route-note">{stop.note}</span>}
        </li>
      ))}
    </ol>
  );
}
