"""The steps of the pipeline as plain functions, plus the routing decisions.

A LangGraph node is just "a function that takes the state and returns the parts
of the state it wants to change". Writing them as ordinary functions (no
LangGraph import here) means we can test every step, and every routing choice,
without LangGraph and without an LLM.
"""
from typing import TypedDict

from freight_intel.pipeline import prompts
from freight_intel.pipeline.money import format_minor
from freight_intel.pipeline.llm import LLM, ExtractionFailed
from freight_intel.pipeline.parsing import ParsedDocument, parse_document
from freight_intel.pipeline.schemas import DocTypeResult, InvoiceExtraction, QuoteExtraction
from freight_intel.pipeline.validation import Issue, TypedDocument, validate

MAX_RETRIES = 2  # first read + at most 2 re-reads = 3 reads in total
MAX_CHARS = 30_000  # a hard cap, so a huge or hostile file can't run up the bill


class DocState(TypedDict, total=False):
    """Everything the graph knows about one document. Each node adds to it.

    status ends as one of: ok | needs_review | reviewed | rejected | failed | unsupported
    (reviewed and rejected only appear when a person answered a review request)
    """

    file_path: str
    parsed: ParsedDocument
    doc_type: str
    extraction: QuoteExtraction | InvoiceExtraction
    typed: TypedDocument
    issues: list[Issue]
    status: str
    error: str
    attempts: int  # how many times the extractor has run on this document
    hint: str  # what the last validation found wrong, for the next attempt
    review: dict  # who reviewed it and what they decided (set by the review step)


def _text(state: DocState) -> str:
    return state["parsed"].text[:MAX_CHARS]


# --- nodes ----------------------------------------------------------------------

def parse_node(state: DocState) -> dict:
    try:
        parsed = parse_document(state["file_path"])
    except Exception as exc:  # corrupt file, unsupported type, ...
        return {"status": "failed", "error": f"could not read file: {exc}"}
    if not parsed.text:
        return {"parsed": parsed, "status": "failed", "error": "; ".join(parsed.warnings) or "empty document"}
    return {"parsed": parsed}


def make_classify_node(llm: LLM):
    def classify_node(state: DocState) -> dict:
        try:
            result = llm.extract(DocTypeResult, prompts.CLASSIFY_SYSTEM, prompts.build_user_message(_text(state)))
        except ExtractionFailed as exc:
            return {"status": "failed", "error": str(exc)}
        return {"doc_type": result.doc_type}

    return classify_node


def make_extract_node(llm: LLM, schema, system: str):
    def extract_node(state: DocState) -> dict:
        try:
            extraction = llm.extract(schema, system, prompts.build_user_message(_text(state), state.get("hint", "")))
        except ExtractionFailed as exc:
            return {"status": "failed", "error": str(exc)}
        return {"extraction": extraction, "attempts": state.get("attempts", 0) + 1}

    return extract_node


def unsupported_node(state: DocState) -> dict:
    return {"status": "unsupported", "error": f"document type {state.get('doc_type')!r} is not supported yet"}


def build_hint(typed: TypedDocument, issues: list[Issue]) -> str:
    """Facts for the next attempt, never the answer. Empty unless the lines don't add up to the total."""
    if not any(i.code == "TOTAL_MISMATCH" for i in issues):
        return ""
    line_sum = sum(c.amount_minor for c in typed.charges)  # safe: TOTAL_MISMATCH only exists if every amount parsed
    return (f"the charge amounts you returned add up to {format_minor(line_sum)}, but the printed total is "
            f"{format_minor(typed.total_minor)}. Re-read every amount in the charge table, digit by digit, "
            f"and extract again.")


def validate_node(state: DocState) -> dict:
    result = validate(state["doc_type"], state["extraction"])
    return {
        "typed": result.typed,
        "issues": result.issues,
        "status": "ok" if result.ok else "needs_review",
        "hint": build_hint(result.typed, result.issues),
    }


# --- routing: which node runs next -----------------------------------------------------

def route_after_parse(state: DocState) -> str:
    return "end" if state.get("status") == "failed" else "classify"


def route_after_classify(state: DocState) -> str:
    if state.get("status") == "failed":
        return "end"
    return {"quote": "extract_quote", "invoice": "extract_invoice"}.get(state.get("doc_type"), "unsupported")


def route_after_extract(state: DocState) -> str:
    return "end" if state.get("status") == "failed" else "validate"


def route_after_validate(state: DocState) -> str:
    """The loop: go back to the same extractor while there is a hint and retries left.
    Otherwise a document that still has errors goes to a person; a clean one is finished."""
    if state.get("hint") and state["attempts"] <= MAX_RETRIES:
        return f"extract_{state['doc_type']}"  # extract_quote or extract_invoice
    return "review" if state.get("status") == "needs_review" else "end"


def run_sequentially(llm: LLM, path: str) -> DocState:
    """The same nodes and the same routers as the graph, called one after another.

    For tests and debugging only. The real pipeline is the LangGraph graph in
    graph.py; a test (test_graph.py) checks that both give the same answers.
    """
    state: DocState = {"file_path": str(path)}
    state.update(parse_node(state))
    if route_after_parse(state) == "end":
        return state
    state.update(make_classify_node(llm)(state))
    nxt = route_after_classify(state)
    if nxt == "end":
        return state
    if nxt == "unsupported":
        state.update(unsupported_node(state))
        return state
    if nxt == "extract_quote":
        extract = make_extract_node(llm, QuoteExtraction, prompts.EXTRACT_QUOTE_SYSTEM)
    else:
        extract = make_extract_node(llm, InvoiceExtraction, prompts.EXTRACT_INVOICE_SYSTEM)
    while True:
        state.update(extract(state))
        if route_after_extract(state) == "end":
            return state
        state.update(validate_node(state))
        if route_after_validate(state) in ("end", "review"):  # nobody to ask here: stop with needs_review
            return state
