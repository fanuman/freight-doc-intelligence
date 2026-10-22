import { sentence } from "@/lib/format";
import type { Issue } from "@/lib/types";
import { AlertIcon } from "./Icons";

// The server names the field an issue is about after the extraction field (pipeline/validation.py).
// A person should see what it is called on the document instead.
const FIELD_LABELS: Record<string, string> = {
  reference: "Document number",
  issued_text: "Issue date",
  invoice_date_text: "Invoice date",
  valid_until_text: "Valid-until date",
  currency_text: "Currency",
  origin_text: "Origin port",
  destination_text: "Destination port",
  equipment_text: "Container type",
  charges: "Charge lines",
  total_text: "Total",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? sentence(field.replace(/_text$/, "")); // a field we have no name for still reads plainly
}

/** The findings of the checking code. Errors must be fixed or explained; warnings are for information. */
export function IssueList({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return <p className="muted">All checks passed.</p>;
  return (
    <ul className="issues">
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${index}`} className={issue.severity === "error" ? "issue issue-error" : "issue issue-warning"}>
          <AlertIcon size={18} className="issue-icon" />
          <span>
            <strong>{issue.severity === "error" ? "Error" : "Warning"}:</strong> {issue.message}
            {issue.field && (
              <>
                {" "}
                <span className="tag">{fieldLabel(issue.field)}</span>
              </>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
