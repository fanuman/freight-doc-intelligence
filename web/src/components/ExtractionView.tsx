import { formatMoney } from "@/lib/format";
import type { Extraction } from "@/lib/types";
import { IssueList } from "./IssueList";
import { StatusBadge } from "./StatusBadge";

function Field({ label, value, wide = false }: { label: string; value: string | null; wide?: boolean }) {
  return (
    <div className={wide ? "spec spec-wide" : "spec"}>
      <dt>{label}</dt>
      <dd>{value || "Not on the document"}</dd>
    </div>
  );
}

/** What was read from the document: the header fields, the charge lines and the checking findings. */
export function ExtractionView({ extraction }: { extraction: Extraction }) {
  const isInvoice = extraction.doc_type === "invoice";
  const route = extraction.origin && extraction.destination ? `${extraction.origin} to ${extraction.destination}` : null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>What was read</h2>
        <StatusBadge status={extraction.status} />
      </div>

      <dl className="specs">
        <Field label={isInvoice ? "Invoice number" : "Quote number"} value={extraction.reference} />
        {isInvoice && <Field label="Quote it cites" value={extraction.quote_reference} />}
        <Field label="Date" value={extraction.doc_date} />
        {!isInvoice && <Field label="Valid until" value={extraction.valid_until} />}
        <Field label="Route" value={route} />
        <Field label="Container" value={extraction.equipment} />
        <Field label="Currency" value={extraction.currency} />
        <Field label="Total printed on the document" value={formatMoney(extraction.total_minor, extraction.currency)} />
      </dl>

      <h3>Charges</h3>
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th className="col-pos">#</th>
              <th>As printed</th>
              <th>Recognised as</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {extraction.charges.map((charge) => (
              <tr key={charge.position}>
                <td className="col-pos">{charge.position}</td>
                <td>{charge.label}</td>
                <td>{charge.known ? charge.code : <span className="tag tag-warn">not recognised</span>}</td>
                <td className="num">
                  {charge.amount_minor === null ? (
                    <span className="tag tag-bad">unreadable</span>
                  ) : (
                    formatMoney(charge.amount_minor, extraction.currency)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Checks</h3>
      <IssueList issues={extraction.issues} />
    </section>
  );
}
