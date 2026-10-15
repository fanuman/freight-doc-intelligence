"""Runs the pipeline over a generated dataset and scores it."""
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from freight_intel.evaluation.metrics import DocScore, score_document, summarize


def load_cases(data_dir: Path, limit: int | None = None) -> list[dict]:
    """Each item is the manifest entry plus its truth.json."""
    manifest = json.loads((data_dir / "manifest.json").read_text())
    entries = manifest["cases"][:limit] if limit else manifest["cases"]
    return [{"entry": e, "truth": json.loads((data_dir / e["truth_file"]).read_text())} for e in entries]


def evaluate(
    data_dir: Path,
    run_one: Callable[[str, list[str], dict], dict],
    *,
    limit: int | None = None,
    workers: int = 4,
) -> tuple[list[DocScore], dict]:
    """`run_one(path, tags, metadata)` runs a single file and returns the final state.
    Passing it in keeps this function independent of LangGraph and of OpenAI."""
    cases = load_cases(data_dir, limit)
    jobs = []
    for item in cases:
        entry, truth = item["entry"], item["truth"]
        for kind, rel in (("quote", entry["quote_file"]), ("invoice", entry["invoice_file"])):
            jobs.append((kind, rel, truth, entry))

    def work(job) -> DocScore:
        kind, rel, truth, entry = job
        metadata = {"case_id": entry["case_id"], "kind": kind, "error_kind": entry["error_kind"],
                    "carrier": entry["carrier_id"], "prompt_injection": entry["prompt_injection"]}
        started = time.perf_counter()
        state = run_one(str(data_dir / rel), ["eval", kind, entry["case_id"]], metadata)
        elapsed = time.perf_counter() - started
        return score_document(kind, truth, state, source_format=Path(rel).suffix.lstrip("."), seconds=elapsed)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        scores = list(pool.map(work, jobs))
    return scores, summarize(scores)


def format_report(summary: dict, usage: dict | None = None, scores: list[DocScore] | None = None) -> str:
    pct = lambda v: "n/a" if v is None else f"{v * 100:5.1f}%"  # noqa: E731
    c, v, p = summary["charges"], summary["validator"], summary["prompt_injection"]
    lines = [
        f"Documents scored           {summary['documents']}   status: {summary['status']}",
        f"Classification accuracy    {pct(summary['classification_accuracy'])}",
        f"Field accuracy (overall)   {pct(summary['field_accuracy'])}",
    ]
    lines += [f"   {name:<16}        {pct(acc)}" for name, acc in summary["field_accuracy_by_field"].items()]
    lines += [
        f"Charge precision / recall  {pct(c['precision'])} / {pct(c['recall'])}   F1 {pct(c['f1'])}",
        f"Charges with the right amount (label ignored)  {pct(summary['charge_amount_recall'])}",
        f"Exact-match documents      {pct(summary['exact_match_rate'])}",
        f"Human-review rate          {pct(summary['human_review_rate'])}",
        f"Validator: wrong totals flagged {v['arithmetic_errors_flagged']}, false alarms {v['false_total_mismatch']}",
        f"Prompt-injection docs      {p['documents']}  field acc {pct(p['field_accuracy'])}  "
        f"leaked into output: {p['leaked_into_extraction']}",
        "By source format:   " + "   ".join(
            f"{k}: F1 {pct(d['charge_f1'])} (n={d['docs']})" for k, d in summary["by_format"].items()),
        "By carrier:         " + "   ".join(
            f"{k}: F1 {pct(d['charge_f1'])}" for k, d in summary["by_carrier"].items()),
        f"Latency per document       mean {summary['latency_seconds']['mean']}s, p95 {summary['latency_seconds']['p95']}s",
    ]
    for message, count in summary.get("errors", {}).items():
        lines.append(f"ERROR x{count}: {message}")
    r = summary["repair_loop"]
    lines.append(f"Repair loop: retried {r['retried']} documents, fixed {r['fixed']}, "
                 f"{r['extra_extractions']} extra extractions")
    n = summary["normalization"]
    lines.append(f"Normalization: charge-code accuracy {pct(n['charge_code_accuracy'])}, "
                 f"confident wrong {n['confident_wrong']}, flagged {n['flagged']}, alias gaps {n['alias_gaps']}")
    wrong = [s for s in (scores or []) if s.missed or s.extra]
    if wrong:
        lines.append(f"Charge mismatches ({len(wrong)} documents; label, amount in cents) - first 8:")
        for s in wrong[:8]:
            lines.append(f"   {s.case_id} {s.kind}: wanted-but-missing {s.missed}  returned-but-wrong {s.extra}")
    if usage:
        lines.append(f"LLM usage                  {usage['calls']} calls, {usage['prompt_tokens']} in / "
                     f"{usage['completion_tokens']} out tokens, about ${usage['approx_cost_usd']:.4f}")
    return "\n".join(lines)
