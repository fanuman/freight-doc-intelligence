"""The quality gate must itself be trustworthy: it passes a perfect run, fails a damaged one, and never passes silently."""
import json
from pathlib import Path

import pytest

from freight_intel.evaluation import gate
from freight_intel.evaluation.runner import evaluate
from freight_intel.pipeline import nodes
from freight_intel.synth.oracle import OracleLLM
from freight_intel.synth.scenario import build_dataset

THRESHOLDS = Path(__file__).resolve().parent.parent / "eval_thresholds.json"
CASES = build_dataset(45, 42)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("openpyxl")
    pytest.importorskip("pdfplumber")
    from freight_intel.synth.writer import write_dataset

    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return out


def summary_for(data_dir, llm):
    _, summary = evaluate(data_dir, lambda path, tags, meta: nodes.run_sequentially(llm, path), workers=4)
    return summary


# --- the lookup and the comparison, on small hand-made summaries ---------------------------------

def test_metric_finds_nested_values_and_turns_fractions_into_numbers():
    s = {"charges": {"f1": 0.98}, "validator": {"ok": "5/5", "bad": "2/40", "none": "0/0"}}
    assert gate.metric(s, "charges.f1") == 0.98
    assert gate.metric(s, "validator.ok") == 1.0 and gate.metric(s, "validator.bad") == 0.05
    assert gate.metric(s, "validator.none") is None
    assert gate.metric(s, "charges.nope") is gate.MISSING and gate.metric(s, "nope.f1") is gate.MISSING


def test_check_passes_when_every_rule_holds_and_names_each_broken_rule():
    summary = {"charges": {"f1": 0.9}, "normalization": {"confident_wrong": 2}, "exact_match_rate": 1.0}
    assert gate.check(summary, {"min": {"exact_match_rate": 1.0}, "max": {"normalization.confident_wrong": 2}}) == []
    failures = gate.check(summary, {"min": {"charges.f1": 0.97}, "max": {"normalization.confident_wrong": 0}})
    assert failures == ["charges.f1: 0.9 is below the minimum 0.97",
                        "normalization.confident_wrong: 2 is above the maximum 0"]


def test_a_missing_or_empty_metric_fails_instead_of_passing_silently():
    summary = {"a": None}
    failures = gate.check(summary, {"min": {"a": 0.5, "renamed": 0.5}})
    assert "no value" in failures[0] and "not found" in failures[1]


def test_a_typo_in_the_rules_is_an_error_not_a_pass():
    with pytest.raises(ValueError, match="unknown rule kind"):
        gate.check({}, {"mim": {"a": 1}})
    with pytest.raises(ValueError, match="no rules for 'gpt'"):
        gate.load_rules(THRESHOLDS, "gpt")


# --- the real thresholds file against the real scoring --------------------------------------------

def test_the_oracle_rules_pass_on_a_perfect_model(data_dir):
    rules = gate.load_rules(THRESHOLDS, "oracle")
    assert gate.check(summary_for(data_dir, OracleLLM(CASES)), rules) == []


def test_the_oracle_rules_catch_a_damaged_model(data_dir):
    def drop_last_charge_on_invoices(result, case, kind):
        if kind == "invoice":
            result.charges = result.charges[:-1]
        return result

    summary = summary_for(data_dir, OracleLLM(CASES, corrupt=drop_last_charge_on_invoices))
    failures = gate.check(summary, gate.load_rules(THRESHOLDS, "oracle"))
    assert any(f.startswith("charges.f1") for f in failures)
    assert any(f.startswith("validator.false_total_mismatch") for f in failures)


def test_every_metric_named_in_the_thresholds_file_exists(data_dir):
    """Guards against a typo in the JSON, and against someone renaming a metric in metrics.py."""
    summary = summary_for(data_dir, OracleLLM(CASES))
    for profile, rules in json.loads(THRESHOLDS.read_text()).items():
        for kind in ("min", "max"):
            for path in rules.get(kind, {}):
                assert gate.metric(summary, path) is not gate.MISSING, f"{profile}: {path}"
