"""A quality gate: compare an evaluation summary with agreed limits and say what is wrong.

Plain functions: no model, no LangGraph, no database. `python -m freight_intel.evaluation --gate eval_thresholds.json`
calls check() and exits with an error when anything fails, which is what turns a CI run red.

Rules look like {"min": {"charges.f1": 0.97}, "max": {"normalization.confident_wrong": 0}}.
A rule names a metric by its dotted path in the summary. A "5/5" style string counts as the fraction 1.0.
"""
import json
from pathlib import Path

MISSING = object()  # "this path is not in the summary at all", different from "it is there but empty"


def metric(summary: dict, path: str):
    """The number at a dotted path. "5/5" becomes 1.0 and "0/0" becomes None. MISSING if the path does not exist."""
    value = summary
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    if isinstance(value, str) and "/" in value:
        top, _, bottom = value.partition("/")
        return int(top) / int(bottom) if int(bottom) else None
    return value


def check(summary: dict, rules: dict) -> list[str]:
    """Every rule that is broken, as a readable line. An empty list means the gate passes.

    A metric that is missing or has no value FAILS its rule: a renamed metric or an empty
    result must never pass silently.
    """
    unknown = set(rules) - {"min", "max"}
    if unknown:
        raise ValueError(f"unknown rule kind(s) {sorted(unknown)}; use 'min' and 'max'")
    failures = []
    for kind in ("min", "max"):
        for path, limit in rules.get(kind, {}).items():
            value = metric(summary, path)
            if value is MISSING:
                failures.append(f"{path}: not found in the evaluation results (was the metric renamed?)")
            elif value is None:
                failures.append(f"{path}: no value (n/a), but a {kind} of {limit} is required")
            elif kind == "min" and value < limit:
                failures.append(f"{path}: {value:.4g} is below the minimum {limit}")
            elif kind == "max" and value > limit:
                failures.append(f"{path}: {value:.4g} is above the maximum {limit}")
    return failures


def load_rules(path: Path, profile: str) -> dict:
    """One file holds a rule set per kind of run, e.g. "oracle" (strict) and "openai" (a little slack)."""
    profiles = json.loads(Path(path).read_text())
    if profile not in profiles:
        raise ValueError(f"{path} has no rules for {profile!r}; it has: {', '.join(profiles)}")
    return profiles[profile]


def count_rules(rules: dict) -> int:
    return sum(len(rules.get(kind, {})) for kind in ("min", "max"))
