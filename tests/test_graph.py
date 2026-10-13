"""Needs the real langgraph library; skipped where it isn't installed.

Checks that the compiled graph gives the same answers as calling the nodes by
hand (nodes.run_sequentially), i.e. that the wiring matches the routing logic.
"""
import pytest

pytest.importorskip("langgraph")

from freight_intel.pipeline import nodes  # noqa: E402
from freight_intel.pipeline.graph import build_graph, run_document  # noqa: E402
from freight_intel.synth.oracle import OracleLLM  # noqa: E402
from freight_intel.synth.scenario import build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402


def test_graph_gives_same_answers_as_sequential_run(tmp_path):
    cases = build_dataset(45, 42)
    write_dataset(45, 42, tmp_path)
    graph = build_graph(OracleLLM(cases))
    checked = 0
    for case in cases:
        for kind, fmt in (("quote", case.quote_format), ("invoice", case.invoice_format)):
            path = tmp_path / "cases" / case.case_id / f"{kind}.{fmt}"
            via_graph = run_document(graph, str(path))
            by_hand = nodes.run_sequentially(OracleLLM(cases), str(path))
            assert via_graph["status"] == by_hand["status"]
            assert via_graph["doc_type"] == by_hand["doc_type"] == kind
            assert [i.code for i in via_graph["issues"]] == [i.code for i in by_hand["issues"]]
            checked += 1
    assert checked == 90


def test_graph_ends_cleanly_on_a_broken_file(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    state = run_document(build_graph(OracleLLM([])), str(bad))
    assert state["status"] == "failed"
