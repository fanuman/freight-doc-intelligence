"""Human review of a document the pipeline could not settle. Plain functions: no LangGraph, no database.

When validation still finds errors after the retries, a person looks at the extraction and answers with a
decision. This file says what a valid answer looks like and what each answer does to the state. The graph
(graph.py) only handles the pausing; the rules live here so they can be tested without it.

A human is not trusted blindly either: a correction goes through the same validate() as the model's reading.
"""
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from freight_intel.pipeline.schemas import InvoiceExtraction, QuoteExtraction
from freight_intel.pipeline.validation import validate

ACTIONS = ("approve", "correct", "reject")
MAX_ROUNDS = 3  # the reviewer gets this many tries; after that the document stays needs_review
MAX_NOTE_CHARS = 1000
SCHEMAS = {"quote": QuoteExtraction, "invoice": InvoiceExtraction}


@dataclass(frozen=True)
class Decision:
    action: str  # approve | correct | reject
    reviewer: str  # who decided; set by our code from the logged-in user, never by the model
    note: str = ""
    extraction: dict | None = None  # "correct" only: the whole corrected extraction, in the model's text shape


def parse_decision(raw) -> Decision:
    """Check what came back from the person. Raises ValueError with a message the person can read."""
    if not isinstance(raw, Mapping):
        raise ValueError("the decision must be a JSON object")
    action = raw.get("action")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(ACTIONS)}")
    reviewer = str(raw.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("the reviewer is required")
    note = str(raw.get("note") or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"the note is longer than {MAX_NOTE_CHARS} characters")
    extraction = raw.get("extraction")
    if action == "correct":
        if not isinstance(extraction, Mapping):
            raise ValueError("a correction must include the corrected extraction")
        return Decision(action, reviewer, note, dict(extraction))
    return Decision(action, reviewer, note)


def build_review_request(state: Mapping, *, error: str | None = None) -> dict:
    """What the person is shown: plain JSON-friendly values only (it is saved with the checkpoint)."""
    request = {
        "doc_type": state["doc_type"],
        "extraction": state["extraction"].model_dump(mode="json"),
        "issues": [asdict(issue) for issue in state.get("issues", [])],
        "attempts": state.get("attempts", 0),
    }
    if error:
        request["error"] = error
    return request


def apply_decision(state: Mapping, decision: Decision) -> dict:
    """The state changes one decision causes. Raises ValueError if the decision cannot be applied."""
    review = {"action": decision.action, "reviewer": decision.reviewer, "note": decision.note}
    if decision.action == "reject":
        return {"status": "rejected", "review": review}
    if decision.action == "approve":
        still_has_errors = any(issue.severity == "error" for issue in state.get("issues", []))
        if still_has_errors and not decision.note:
            raise ValueError("approving a document that still has errors needs a note saying why")
        return {"status": "reviewed", "review": review}
    corrected = SCHEMAS[state["doc_type"]].model_validate(decision.extraction)  # ValidationError is a ValueError
    result = validate(state["doc_type"], corrected)
    return {
        "extraction": corrected,
        "typed": result.typed,
        "issues": result.issues,
        "status": "reviewed" if result.ok else "needs_review",
        "hint": "",
        "review": review,
    }


def review_loop(state: Mapping, ask: Callable[[dict], object]) -> dict:
    """Ask until the person gives a usable answer (at most MAX_ROUNDS times). Returns the state update.

    `ask` shows a request and returns the person's raw answer. In the graph it is LangGraph's interrupt();
    in tests it is a scripted function. This function must be repeatable: after a pause the graph runs it
    again from the top, and interrupt() hands back the earlier answers in order.
    """
    request = build_review_request(state)
    latest: dict = {}
    for _ in range(MAX_ROUNDS):
        raw = ask(request)
        try:
            update = apply_decision(state, parse_decision(raw))
        except ValueError as exc:
            request = build_review_request(state, error=str(exc)[:500])
            continue
        if update["status"] != "needs_review":
            return update
        latest = update  # a correction that still has errors: show what remains and ask again
        state = {**state, **update}
        request = build_review_request(state)
    return {**latest, "status": "needs_review", "error": f"review not completed after {MAX_ROUNDS} attempts"}
