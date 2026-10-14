"""Draws the README diagrams as SVG files. No dependencies: run `python docs/diagrams/build_diagrams.py`.

Edit the numbers and text below, run it again, commit the changed SVGs in docs/images/.
Every picture has a white background so it reads the same on GitHub's light and dark themes.
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "images"

FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
INK, SOFT, FAINT = "#111827", "#4b5563", "#9ca3af"

KINDS = {  # fill, stroke
    "llm": ("#dbeafe", "#2563eb"),
    "code": ("#dcfce7", "#16a34a"),
    "router": ("#fef3c7", "#d97706"),
    "end": ("#f3f4f6", "#6b7280"),
    "review": ("#fee2e2", "#dc2626"),
    "plain": ("#ffffff", "#9ca3af"),
}
ARROW_COLORS = {"ink": "#374151", "retry": "#d97706", "red": "#dc2626"}
LINE_H = {"t": 21, "d": 17, "m": 15}


class Svg:
    def __init__(self, w, h, title, desc):
        self.w, self.h, self.parts = w, h, []
        self.title, self.desc = title, desc

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=13, weight="normal", fill=INK, anchor="start", family=FONT, italic=False, halo=False):
        extra = ' stroke="#ffffff" stroke-width="5" stroke-linejoin="round" paint-order="stroke"' if halo else ""
        style = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
                 f'fill="{fill}" text-anchor="{anchor}"{style}{extra}>{escape(s)}</text>')

    def rect(self, x, y, w, h, kind="plain", r=10, dashed=False, sw=1.6, fill=None):
        f, s = KINDS[kind]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or f}" stroke="{s}" stroke-width="{sw}"{dash}/>')

    def lines_block(self, cx, cy, lines, anchor="middle", x=None):
        """lines = [(text, 't'|'d'|'m'), ...] centred vertically on cy."""
        total = sum(LINE_H[k] for _, k in lines)
        y = cy - total / 2
        for s, k in lines:
            y += LINE_H[k]
            base = y - (5 if k == "t" else 4)
            px = cx if x is None else x
            if k == "t":
                self.text(px, base, s, 15, "bold", INK, anchor)
            elif k == "d":
                self.text(px, base, s, 12.5, "normal", SOFT, anchor)
            else:
                self.text(px, base, s, 10.5, "normal", "#6b7280", anchor, MONO)

    def node(self, cx, cy, w, h, kind, lines, dashed=False):
        self.rect(cx - w / 2, cy - h / 2, w, h, kind, dashed=dashed)
        self.lines_block(cx, cy, lines)

    def arrow(self, pts, color="ink", dashed=False, width=2.0):
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.add(f'<path d="{d}" fill="none" stroke="{ARROW_COLORS[color]}" stroke-width="{width}" '
                 f'stroke-linejoin="round" marker-end="url(#a-{color})"{dash}/>')

    def render(self):
        markers = "".join(
            f'<marker id="a-{n}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for n, c in ARROW_COLORS.items())
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" '
                f'role="img" aria-labelledby="t d"><title id="t">{escape(self.title)}</title><desc id="d">{escape(self.desc)}</desc>'
                f'<defs>{markers}</defs><rect width="{self.w}" height="{self.h}" fill="#ffffff"/>' + "".join(self.parts) + "</svg>")

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(self.render(), encoding="utf-8")
        print("wrote", OUT / name)


def header(s, title, subtitle):
    s.text(30, 42, title, 22, "bold")
    s.text(30, 68, subtitle, 15, "normal", SOFT)


def legend(s, x, y, items):
    for kind, label in items:
        if kind == "retry":
            s.add(f'<line x1="{x}" y1="{y+9}" x2="{x+26}" y2="{y+9}" stroke="#d97706" stroke-width="2.4" stroke-dasharray="6 4"/>')
            s.text(x + 34, y + 14, label, 12.5, "normal", SOFT)
            x += 34 + len(label) * 6.6 + 24
        else:
            s.rect(x, y, 26, 18, kind, r=4, sw=1.4)
            s.text(x + 34, y + 14, label, 12.5, "normal", SOFT)
            x += 34 + len(label) * 6.6 + 24


# ---------------------------------------------------------------- 1. pipeline overview
def pipeline_overview():
    s = Svg(1280, 600, "FreightLens extraction pipeline",
            "A document is parsed, classified by an LLM, extracted by an LLM, then validated by code. "
            "If the totals do not add up, the document goes back to the extractor with a hint, at most twice, "
            "otherwise it goes to a human.")
    header(s, "How one document moves through the pipeline",
           "A LangGraph state graph. graph.py wires the steps; the steps are plain functions in nodes.py.")
    NW, NH = 150, 84
    # centres
    doc, parse, cls = (95, 255), (270, 255), (455, 255)
    eq, ei = (690, 170), (690, 340)
    val = (930, 255)
    ok, rev = (1170, 165), (1170, 345)
    fail, uns = (270, 440), (455, 440)

    s.node(*doc, 130, NH, "end", [("Document", "t"), ("PDF, XLSX, EML", "d")])
    s.node(*parse, NW, NH, "code", [("parse", "t"), ("get the text out", "d"), ("parsing.py", "m")])
    s.node(*cls, 160, NH, "llm", [("classify", "t"), ("quote or invoice?", "d"), ("LLM call", "m")])
    s.node(*eq, 190, NH, "llm", [("extract_quote", "t"), ("copy fields as text", "d"), ("LLM call", "m")])
    s.node(*ei, 190, NH, "llm", [("extract_invoice", "t"), ("copy fields as text", "d"), ("LLM call", "m")])
    s.node(*val, 190, NH, "code", [("validate", "t"), ("convert, check the sums", "d"), ("validation.py", "m")])
    s.node(*ok, 130, 60, "end", [("ok", "t")])
    s.node(*rev, 150, 76, "review", [("needs_review", "t"), ("a human looks", "d")])
    s.node(*fail, 150, 66, "end", [("failed", "t"), ("unreadable file", "d")])
    s.node(*uns, 160, 66, "end", [("unsupported", "t"), ("rate sheet or other", "d")])

    s.arrow([(160, 255), (195, 255)])
    s.arrow([(345, 255), (375, 255)])
    s.arrow([(535, 255), (580, 255), (580, 170), (595, 170)])
    s.arrow([(535, 255), (580, 255), (580, 340), (595, 340)])
    s.text(574, 206, "quote", 12, "bold", SOFT, "end", halo=True)
    s.text(574, 318, "invoice", 12, "bold", SOFT, "end", halo=True)
    # extractors into validate (elbows)
    s.arrow([(785, 170), (810, 170), (810, 235), (835, 235)])
    s.arrow([(785, 340), (810, 340), (810, 275), (835, 275)])
    s.arrow([(1025, 255), (1060, 255), (1060, 165), (1105, 165)])
    s.arrow([(1025, 255), (1060, 255), (1060, 345), (1095, 345)])
    s.text(1066, 212, "no errors", 12, "bold", SOFT, "start", halo=True)
    s.text(1066, 300, "errors remain", 12, "bold", SOFT, "start", halo=True)
    s.arrow([(270, 297), (270, 407)])
    s.text(280, 362, "can't read the file", 12, "bold", SOFT, "start", halo=True)
    s.arrow([(455, 297), (455, 407)])
    s.text(465, 362, "something else", 12, "bold", SOFT, "start", halo=True)

    # retry loops
    s.arrow([(930, 213), (930, 100), (690, 100), (690, 128)], "retry", dashed=True, width=2.6)
    s.text(810, 92, "retry, at most 2 times: back to the same extractor with a hint", 12.5, "bold", "#b45309", "middle", halo=True)
    s.text(810, 118, "only when the charge lines do not add up to the printed total", 12, "normal", "#b45309", "middle", halo=True)
    s.arrow([(930, 297), (930, 505), (690, 505), (690, 382)], "retry", dashed=True, width=2.6)
    s.text(810, 527, "same loop for invoices", 12.5, "bold", "#b45309", "middle", halo=True)

    legend(s, 30, 562, [("llm", "LLM step: only copies text"), ("code", "plain code: converts, checks, decides"),
                        ("retry", "retry loop"), ("review", "goes to a human")])
    s.save("pipeline-overview.svg")


# ---------------------------------------------------------------- 2. execution walkthrough
def walkthrough():
    s = Svg(1350, 980, "What happens when one invoice is processed",
            "Ten numbered steps showing which part of the program calls which: the caller, LangGraph, the step functions, "
            "the OpenAI API and the validation code, including the retry loop.")
    header(s, "What happens when one invoice is processed",
           "Read top to bottom. Each arrow is a function call; the grey text says what comes back or what is added to the state.")
    lanes = [
        (165, "Your code", "eval runner or a script", "plain"),
        (435, "LangGraph", "graph.py: runs the steps", "router"),
        (705, "Step functions", "nodes.py: plain functions", "code"),
        (975, "OpenAI", "llm.py wraps the API call", "llm"),
        (1215, "Checks", "validation.py, money.py (no AI)", "code"),
    ]
    X = {i: lanes[i][0] for i in range(5)}
    for i, (cx, name, sub, kind) in enumerate(lanes):
        s.node(cx, 112, 220, 58, kind, [(name, "t"), (sub, "d")])
        s.add(f'<line x1="{cx}" y1="142" x2="{cx}" y2="935" stroke="{FAINT}" stroke-width="1.4" stroke-dasharray="3 5"/>')

    def call(n, y, a, b, label, sub, color="ink", dashed=False):
        s.add(f'<circle cx="30" cy="{y}" r="13" fill="#111827"/>')
        s.text(30, y + 4.5, str(n), 12.5, "bold", "#ffffff", "middle")
        s.arrow([(X[a], y), (X[b] + (-6 if b > a else 6), y)], color, dashed)
        mid = (X[a] + X[b]) / 2
        s.text(mid, y - 9, label, 13, "bold", INK, "middle", halo=True)
        s.text(mid, y + 19, sub, 11.5, "normal", SOFT, "middle", halo=True)

    def note(n, y, lane, lines, kind="router", w=250):
        s.add(f'<circle cx="30" cy="{y}" r="13" fill="#111827"/>')
        s.text(30, y + 4.5, str(n), 12.5, "bold", "#ffffff", "middle")
        s.node(X[lane], y, w, 50, kind, lines)

    call(1, 195, 0, 1, "run_document(graph, path)", "state starts as {file_path}")
    call(2, 275, 1, 2, "parse_node(state)", "adds parsed (the text of the file)")
    call(3, 355, 1, 2, "classify_node(state)", "calls the LLM, adds doc_type")
    call(4, 435, 2, 3, "extract(DocTypeResult, document)", "answer: invoice")
    note(5, 515, 1, [("route_after_classify", "t"), ("invoice, so go to extract_invoice", "d")], w=290)
    call(6, 600, 1, 2, "extract_invoice node(state)", "adds extraction, attempts = attempts + 1")
    call(7, 680, 2, 3, "extract(InvoiceExtraction, document + hint)", "answer: charges and total as raw text")
    call(8, 760, 2, 4, "validate(doc_type, extraction)", "text to numbers, sums checked, hint built")
    note(9, 845, 1, [("route_after_validate", "t"), ("hint set and attempts <= 2: back to step 6", "d")], w=330)
    call(10, 920, 1, 0, "final state returned", "status is ok or needs_review", "ink")
    # retry loop line
    s.arrow([(270, 845), (270, 600), (433, 600)], "retry", dashed=True, width=2.4)
    s.text(262, 730, "retry", 13, "bold", "#b45309", "end", halo=True)
    s.text(262, 748, "(max 2 times)", 11.5, "normal", "#b45309", "end", halo=True)
    s.text(30, 965, "Steps 6 and 7 only repeat when step 8 found a TOTAL_MISMATCH. Otherwise step 9 ends the run.", 12.5, "normal", SOFT, "start", italic=True)
    s.save("execution-walkthrough.svg")


# ---------------------------------------------------------------- 3. state journey (case-044)
def state_journey():
    cols = [("start", "none"), ("parse", "code"), ("classify", "llm"), ("extract, try 1", "llm"),
            ("validate", "code"), ("extract, try 2", "llm"), ("validate", "code")]
    rows = [  # (key, height)
        ("file_path", 52), ("parsed", 70), ("doc_type", 40), ("extraction", 92), ("attempts", 40),
        ("issues", 40), ("hint", 92), ("status", 40), ("next step", 72)]
    LABW, CW, X0, Y0, HEADH = 130, 172, 30, 96, 52
    W = X0 + LABW + CW * len(cols) + 26
    H = Y0 + HEADH + sum(h for _, h in rows) + 90
    s = Svg(W, H, "How the shared state changes while case-044 is repaired",
            "A table. Rows are the keys of the shared state, columns are the steps. A coloured cell means that step wrote that value. "
            "The first extraction misread 4 195.00 as 195.00, validation caught the mismatch, and the second extraction fixed it.")
    header(s, "How the shared state changes: a real repair (synthetic case-044)",
           "Each column is a step. A coloured cell means that step wrote the value. Empty cells are carried over unchanged.")
    # headers
    for i, (name, kind) in enumerate(cols):
        x = X0 + LABW + i * CW
        if kind == "none":
            s.rect(x + 3, Y0, CW - 6, HEADH - 8, "plain", r=8)
        else:
            s.rect(x + 3, Y0, CW - 6, HEADH - 8, kind, r=8)
        s.text(x + CW / 2, Y0 + 27, name, 14, "bold", INK, "middle")
    ys, y = {}, Y0 + HEADH
    for key, h in rows:
        ys[key] = (y, h)
        s.rect(X0, y + 2, W - X0 - 26, h - 4, "plain", r=6, sw=0.8, fill="#fafafa")
        s.text(X0 + 8, y + h / 2 + 5, key, 13, "bold", INK, "start", MONO)
        y += h

    def cell(col, key, lines, kind="code", bad=False):
        yy, h = ys[key]
        x = X0 + LABW + col * CW + 4
        k = "review" if bad else kind
        s.rect(x, yy + 5, CW - 8, h - 10, k, r=6, sw=1.4)
        n = len(lines)
        for j, ln in enumerate(lines):
            s.text(x + 8, yy + h / 2 - (n - 1) * 8 + j * 16 + 4, ln, 11.5, "normal", INK, "start", FONT)

    cell(0, "file_path", ["…/case-044/", "invoice.pdf"], "plain")
    cell(1, "parsed", ["text from the PDF:", "'Ocean Freight per", "container USD 4 195.00'"], "code")
    cell(2, "doc_type", ["'invoice'"], "llm")
    cell(3, "extraction", ["Ocean Freight:", "'195.00'  ✗ misread", "BAF: '355.00' …", "total: 'USD 5 040.00'"], "llm", bad=True)
    cell(3, "attempts", ["1"], "llm")
    cell(4, "issues", ["TOTAL_MISMATCH"], "code", bad=True)
    cell(4, "hint", ["lines add up to", "1,040.00 but the", "printed total is", "5,040.00. Re-read…"], "code")
    cell(4, "status", ["needs_review (for now)"], "code")
    cell(5, "extraction", ["Ocean Freight:", "'4 195.00'  ✓ fixed", "BAF: '355.00' …", "total: 'USD 5 040.00'"], "llm")
    cell(5, "attempts", ["2"], "llm")
    cell(6, "issues", ["none"], "code")
    cell(6, "hint", ["'' (empty)"], "code")
    cell(6, "status", ["ok"], "code")
    cell(2, "next step", ["extract_invoice"], "router")
    cell(4, "next step", ["hint set, 1 <= 2:", "extract_invoice", "again"], "router")
    cell(6, "next step", ["hint empty:", "END"], "router")
    yb = Y0 + HEADH + sum(h for _, h in rows) + 34
    s.text(30, yb, "1,040.00 = 195.00 + 355.00 + 140.00 + 265.00 + 65.00 + 20.00. The code, not the model, noticed it did not equal 5,040.00.", 12.5, "normal", SOFT, "start", italic=True)
    legend(s, 30, yb + 18, [("llm", "written by an LLM step"), ("code", "written by code"), ("router", "router decision"), ("review", "problem found")])
    s.save("state-journey-case-044.svg")


# ---------------------------------------------------------------- 4. tenant isolation
def tenant_isolation():
    s = Svg(1180, 640, "How a request stays inside one company's data",
            "The client sends a token. The API verifies it and tells Postgres which tenant this is. "
            "Row-level security then returns only that tenant's rows, and returns nothing if no tenant was set.")
    header(s, "How a request stays inside one company's data",
           "The database enforces the rule itself with row-level security, so a missing WHERE clause in app code cannot leak rows.")
    lanes = [(170, "Client", "browser or script", "plain"), (590, "FastAPI", "api/deps.py, db.py, security.py", "code"),
             (1010, "Postgres", "connected as a normal (non-superuser) role", "llm")]
    X = [l[0] for l in lanes]
    for cx, name, sub, kind in lanes:
        s.node(cx, 112, 270, 58, kind, [(name, "t"), (sub, "d")])
        s.add(f'<line x1="{cx}" y1="142" x2="{cx}" y2="520" stroke="{FAINT}" stroke-width="1.4" stroke-dasharray="3 5"/>')

    def call(n, y, a, b, label, sub):
        s.add(f'<circle cx="30" cy="{y}" r="13" fill="#111827"/>')
        s.text(30, y + 4.5, str(n), 12.5, "bold", "#ffffff", "middle")
        s.arrow([(X[a], y), (X[b] + (-6 if b > a else 6), y)])
        mid = (X[a] + X[b]) / 2
        s.text(mid, y - 9, label, 13, "bold", INK, "middle", halo=True)
        s.text(mid, y + 19, sub, 11.5, "normal", SOFT, "middle", halo=True)

    call(1, 195, 0, 1, "GET /me   Authorization: Bearer <token>", "the token holds user id, tenant id and role")
    s.add('<circle cx="30" cy="265" r="13" fill="#111827"/>'); s.text(30, 269.5, "2", 12.5, "bold", "#ffffff", "middle")
    s.node(590, 265, 390, 50, "code", [("check signature and expiry", "t"), ("a forged or expired token stops here (401)", "d")])
    call(3, 335, 1, 2, "BEGIN, then set_config('app.tenant_id', tenant id)", "lasts only for this transaction")
    call(4, 405, 1, 2, "SELECT ... FROM users  (or documents)", "the query has no tenant filter of its own")
    s.add('<circle cx="30" cy="475" r="13" fill="#111827"/>'); s.text(30, 479.5, "5", 12.5, "bold", "#ffffff", "middle")
    s.node(1000, 475, 320, 50, "router", [("row-level security policy", "t"), ("keeps rows where tenant_id = app.tenant_id", "d")])
    call(6, 545, 2, 1, "only this company's rows", "other tenants' rows are invisible, not just filtered")
    call(7, 600, 1, 0, "response", "")
    s.save("tenant-isolation.svg")


# ---------------------------------------------------------------- 5. test flow
def test_flow():
    s = Svg(1280, 520, "How the pipeline is tested without real documents",
            "A seeded generator creates documents and the correct answers. The pipeline processes the documents, "
            "scoring compares its output with the answers and writes a report.")
    header(s, "How the pipeline is tested without real documents",
           "Fictional carriers, repeatable data, and the correct answer saved next to every document.")
    gen, files, truth = (130, 250), (385, 170), (385, 340)
    pipe, res, score, rep = (650, 170), (900, 170), (900, 340), (1150, 340)
    s.node(*gen, 190, 90, "code", [("Generator", "t"), ("seeded, so repeatable", "d"), ("synth/", "m")])
    s.node(*files, 200, 84, "plain", [("Documents", "t"), ("PDF, XLSX, EML", "d"), ("quotes and invoices", "d")])
    s.node(*truth, 200, 84, "plain", [("truth.json", "t"), ("the correct answer", "d"), ("one per case", "d")])
    s.node(*pipe, 220, 96, "llm", [("The pipeline", "t"), ("real LLM (gpt-4o-mini)", "d"), ("or the free oracle", "d")])
    s.node(*res, 190, 84, "plain", [("Extracted results", "t"), ("charges, dates, totals", "d")])
    s.node(*score, 210, 90, "code", [("Scoring", "t"), ("compare each field and", "d"), ("charge with the truth", "d")])
    s.node(*rep, 190, 120, "end", [("Report", "t"), ("accuracy, charge F1", "d"), ("errors caught, false alarms", "d"), ("injection leaks, cost", "d")])
    s.arrow([(225, 232), (270, 232), (270, 170), (285, 170)])
    s.arrow([(225, 268), (270, 268), (270, 340), (285, 340)])
    s.arrow([(485, 170), (540, 170)])
    s.arrow([(760, 170), (805, 170)])
    s.arrow([(900, 212), (900, 295)])
    s.arrow([(485, 340), (795, 340)])
    s.arrow([(1005, 340), (1055, 340)])
    s.text(640, 332, "the answer key", 12, "bold", SOFT, "middle", halo=True)
    s.rect(30, 440, 1220, 56, "plain", r=8, sw=1.0, fill="#fafafa")
    s.text(46, 463, "The dataset: 45 cases, 90 documents, 4 fictional carriers. Scenarios: clean, overcharge, unquoted charge, missing charge,", 12.5, "normal", SOFT)
    s.text(46, 483, "currency mismatch, expired quote, rounding noise, arithmetic error. 7 invoices contain prompt-injection text.", 12.5, "normal", SOFT)
    s.save("test-flow.svg")


if __name__ == "__main__":
    pipeline_overview()
    walkthrough()
    state_journey()
    tenant_isolation()
    test_flow()
