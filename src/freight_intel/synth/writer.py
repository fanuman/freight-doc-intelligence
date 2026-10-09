"""Writes a dataset to disk: one folder per case, plus a manifest."""
import json
from pathlib import Path

from freight_intel.synth.records import Case
from freight_intel.synth.scenario import build_dataset
from freight_intel.synth.view import build_view


def _render(case: Case, kind: str, fmt: str, path: Path) -> None:
    view = build_view(case, kind)
    if fmt == "pdf":
        from freight_intel.synth.render_pdf import render_pdf  # imported lazily: optional dependency
        render_pdf(view, path)
    elif fmt == "xlsx":
        from freight_intel.synth.render_xlsx import render_xlsx
        render_xlsx(view, case, path)
    elif fmt == "eml":
        from freight_intel.synth.render_eml import render_eml
        render_eml(view, case, path)
    else:
        raise ValueError(f"unknown format: {fmt}")


def write_case(case: Case, out_dir: Path) -> dict:
    folder = out_dir / "cases" / case.case_id
    folder.mkdir(parents=True, exist_ok=True)
    _render(case, "quote", case.quote_format, folder / f"quote.{case.quote_format}")
    _render(case, "invoice", case.invoice_format, folder / f"invoice.{case.invoice_format}")
    (folder / "truth.json").write_text(case.to_json())
    return {
        "case_id": case.case_id,
        "error_kind": case.error_kind,
        "carrier_id": case.quote.carrier_id,
        "quote_file": f"cases/{case.case_id}/quote.{case.quote_format}",
        "invoice_file": f"cases/{case.case_id}/invoice.{case.invoice_format}",
        "truth_file": f"cases/{case.case_id}/truth.json",
        "expected_discrepancies": [d.type for d in case.expected],
        "prompt_injection": case.prompt_injection,
    }


def write_dataset(count: int, seed: int, out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = [write_case(case, out_dir) for case in build_dataset(count, seed)]
    manifest = {"seed": seed, "count": count, "cases": entries}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return entries
