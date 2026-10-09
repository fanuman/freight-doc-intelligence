"""PDF renderer (reportlab). Three visual layouts, chosen by the carrier."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from freight_intel.synth.view import DocumentView


def render_pdf(view: DocumentView, path: Path) -> None:
    layout = view.carrier.layout
    base = getSampleStyleSheet()["Normal"]
    size = 8.5 if layout == "compact" else 10
    body = ParagraphStyle("body", parent=base, fontName="Helvetica", fontSize=size, leading=size + 3)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, textColor=colors.grey)
    head = ParagraphStyle("head", parent=body, fontName="Helvetica-Bold", fontSize=15, leading=19)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=16)

    # pageCompression=0 keeps text readable in the raw file (handy for debugging
    # and for tests); invariant=1 removes timestamps so output is reproducible.
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            pageCompression=0, invariant=1, title=view.title)
    story = [Paragraph(view.carrier.name, head), Paragraph(view.title, title), Spacer(1, 6 * mm)]

    meta = Table([[Paragraph(f"<b>{k}</b>", body), Paragraph(v, body)] for k, v in view.meta],
                 colWidths=[45 * mm, 80 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    story += [meta, Spacer(1, 6 * mm)]

    data = [view.columns] + view.rows + [view.total]
    last = len(data) - 1
    amount = view.amount_col
    widths = {2: [110 * mm, 55 * mm], 4: [70 * mm, 30 * mm, 25 * mm, 40 * mm]}[len(view.columns)]
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), size),
        ("ALIGN", (amount, 0), (amount, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if layout == "simple":
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                  ("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]
    elif layout == "detailed":
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                  ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1F3A5F")),
                  ("LINEABOVE", (0, last), (-1, last), 1.2, colors.black)]
    else:  # compact: no vertical lines, thin rules only
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                  ("LINEABOVE", (0, last), (-1, last), 0.8, colors.black)]
    table.setStyle(TableStyle(style))
    story += [table, Spacer(1, 8 * mm)]

    story += [Paragraph(line, body) for line in view.remarks]
    story += [Spacer(1, 10 * mm), Paragraph(view.footer, small)]
    doc.build(story)
