"""Email renderer (stdlib only). Quotes often arrive as plain-text emails."""
from datetime import datetime, time, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from freight_intel.synth.records import Case
from freight_intel.synth.view import DocumentView


def render_eml(view: DocumentView, case: Case, path: Path) -> None:
    carrier = view.carrier
    d = case.quote.issued_on if view.kind == "quote" else case.invoice.invoice_date
    ref = view.meta[0][1]

    msg = EmailMessage()
    msg["From"] = f"{carrier.name} <pricing@{carrier.domain}>"
    msg["To"] = "Sales Desk <sales@customer-forwarder.example>"
    msg["Subject"] = f"{view.title} {ref}"
    msg["Date"] = format_datetime(datetime.combine(d, time(9, 30), tzinfo=timezone.utc))
    msg["Message-ID"] = f"<{case.case_id}-{view.kind}@{carrier.domain}>"  # fixed => reproducible

    lines = ["Dear Sir/Madam,", "", "Please find our offer below." if view.kind == "quote"
             else "Please find your invoice details below.", ""]
    lines += [f"{key}: {value}" for key, value in view.meta]
    lines.append("")
    for row in view.rows:
        lines.append("  " + "   ".join(cell for cell in row if cell))
    lines.append("  ---")
    lines.append("  " + "   ".join(cell for cell in view.total if cell))
    lines.append("")
    lines += view.remarks
    lines += ["", "Best regards,", f"Pricing Desk, {carrier.name}"]
    msg.set_content("\n".join(lines))
    path.write_bytes(msg.as_bytes())
