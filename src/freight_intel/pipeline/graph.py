"""Wires the nodes into a LangGraph graph.

  START -> parse -> classify -+-> extract_quote   -+-> validate -+-> END
                              +-> extract_invoice -+      ^       |
                              |                    ^      |       | TOTAL_MISMATCH and retries left
                              |                    +------+-------+  (hint goes back to the extractor)
                              +-> unsupported -> END      (any step can also jump to END on failure)

With human_review=True, a document that still has errors after the retries goes to a person instead of
straight to END:   validate -> human_review (pauses until someone answers) -> END

The two `add_conditional_edges` calls are the router pattern from Day 31, now
for real: after `classify`, the *state* decides which extractor runs.
"""
from collections.abc import Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from freight_intel.pipeline import nodes, prompts, review
from freight_intel.pipeline.llm import LLM
from freight_intel.pipeline.schemas import InvoiceExtraction, QuoteExtraction


class NoPendingReview(Exception):
    """Tried to answer a review request, but this document is not waiting for one."""


def human_review_node(state: nodes.DocState) -> dict:
    # interrupt() stops the graph here. When someone resumes it, this function runs again from the top
    # and interrupt() returns their answer, so nothing above it may have side effects.
    return review.review_loop(state, interrupt)


def build_graph(llm: LLM, *, checkpointer=None, human_review: bool = False):
    """human_review=True adds the pause-for-a-person step. It needs a checkpointer, which is what lets
    the graph remember where it stopped. Without it (the default) behaviour is exactly as before."""
    if human_review and checkpointer is None:
        raise ValueError("human_review=True needs a checkpointer so the graph can remember where it paused")
    g = StateGraph(nodes.DocState)

    g.add_node("parse", nodes.parse_node)
    g.add_node("classify", nodes.make_classify_node(llm))
    g.add_node("extract_quote", nodes.make_extract_node(llm, QuoteExtraction, prompts.EXTRACT_QUOTE_SYSTEM))
    g.add_node("extract_invoice", nodes.make_extract_node(llm, InvoiceExtraction, prompts.EXTRACT_INVOICE_SYSTEM))
    g.add_node("unsupported", nodes.unsupported_node)
    g.add_node("validate", nodes.validate_node)
    if human_review:
        g.add_node("human_review", human_review_node)
        g.add_edge("human_review", END)

    g.add_edge(START, "parse")
    # Conditional edge: call the router function, look its answer up in this map.
    g.add_conditional_edges("parse", nodes.route_after_parse, {"classify": "classify", "end": END})
    g.add_conditional_edges(
        "classify",
        nodes.route_after_classify,
        {"extract_quote": "extract_quote", "extract_invoice": "extract_invoice",
         "unsupported": "unsupported", "end": END},
    )
    for name in ("extract_quote", "extract_invoice"):
        g.add_conditional_edges(name, nodes.route_after_extract, {"validate": "validate", "end": END})
    g.add_edge("unsupported", END)
    # The loop: after validate, either finish or go back to the same extractor with a hint.
    g.add_conditional_edges(
        "validate",
        nodes.route_after_validate,
        {"extract_quote": "extract_quote", "extract_invoice": "extract_invoice",
         "review": "human_review" if human_review else END, "end": END},
    )

    return g.compile(checkpointer=checkpointer)


def review_thread_id(tenant_id, document_id) -> str:
    """One thread per document. The tenant is part of the name, so two companies can never share a thread."""
    return f"{tenant_id}:{document_id}"


def run_document(
    graph, path: str, *, tags: list[str] | None = None, metadata: dict | None = None, thread_id: str | None = None
) -> dict:
    """Run one file through the graph and return the final state.

    A graph built with a checkpointer needs a `thread_id`. If the run stopped for a review, the returned
    state is the one so far; check pending_review() to see whether a person is being waited for.

    `tags` and `metadata` appear on the trace in LangSmith, which is how you
    later filter "show me every invoice that needed review".
    """
    config = {"run_name": "freight_document", "tags": tags or [], "metadata": metadata or {}}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}
    return graph.invoke({"file_path": str(path)}, config=config)


def pending_review(graph, thread_id: str) -> dict | None:
    """The request a person has to answer, or None if this document is not waiting for anyone."""
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def resume_document(graph, thread_id: str, decision: Mapping) -> dict:
    """Give the waiting graph the person's answer and run it to the end (or to the next question)."""
    if pending_review(graph, thread_id) is None:
        raise NoPendingReview(thread_id)
    return graph.invoke(
        Command(resume=dict(decision)),
        config={"run_name": "freight_document_review", "configurable": {"thread_id": thread_id}},
    )
