"""Wires the nodes into a LangGraph graph.

  START -> parse -> classify -+-> extract_quote   -+-> validate -+-> END
                              +-> extract_invoice -+      ^       |
                              |                    ^      |       | TOTAL_MISMATCH and retries left
                              |                    +------+-------+  (hint goes back to the extractor)
                              +-> unsupported -> END      (any step can also jump to END on failure)

The two `add_conditional_edges` calls are the router pattern from Day 31, now
for real: after `classify`, the *state* decides which extractor runs.
"""
from langgraph.graph import END, START, StateGraph

from freight_intel.pipeline import nodes, prompts
from freight_intel.pipeline.llm import LLM
from freight_intel.pipeline.schemas import InvoiceExtraction, QuoteExtraction


def build_graph(llm: LLM):
    g = StateGraph(nodes.DocState)

    g.add_node("parse", nodes.parse_node)
    g.add_node("classify", nodes.make_classify_node(llm))
    g.add_node("extract_quote", nodes.make_extract_node(llm, QuoteExtraction, prompts.EXTRACT_QUOTE_SYSTEM))
    g.add_node("extract_invoice", nodes.make_extract_node(llm, InvoiceExtraction, prompts.EXTRACT_INVOICE_SYSTEM))
    g.add_node("unsupported", nodes.unsupported_node)
    g.add_node("validate", nodes.validate_node)

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
        {"extract_quote": "extract_quote", "extract_invoice": "extract_invoice", "end": END},
    )

    return g.compile()


def run_document(graph, path: str, *, tags: list[str] | None = None, metadata: dict | None = None) -> dict:
    """Run one file through the graph and return the final state.

    `tags` and `metadata` appear on the trace in LangSmith, which is how you
    later filter "show me every invoice that needed review".
    """
    return graph.invoke(
        {"file_path": str(path)},
        config={"run_name": "freight_document", "tags": tags or [], "metadata": metadata or {}},
    )
