"""python -m freight_intel.evaluation --data data/synthetic --llm openai --limit 18"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the extraction pipeline on the synthetic dataset.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--llm", choices=["openai", "oracle"], default="openai",
                        help="oracle = a perfect pretend model, to test the harness for free")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases (each has 2 documents)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("eval_results"))
    args = parser.parse_args()

    from freight_intel.evaluation.runner import evaluate, format_report
    from freight_intel.pipeline.graph import build_graph, run_document

    manifest = json.loads((args.data / "manifest.json").read_text())
    if args.llm == "oracle":
        from freight_intel.synth.oracle import OracleLLM
        from freight_intel.synth.scenario import build_dataset

        llm, model = OracleLLM(build_dataset(manifest["count"], manifest["seed"])), "oracle"
    else:
        from freight_intel.config import get_settings
        from freight_intel.pipeline.llm import OpenAILLM
        from freight_intel.pipeline.tracing import configure_tracing

        settings = get_settings()
        if not settings.openai_api_key:
            raise SystemExit("OPENAI_API_KEY is not set in .env")
        print("LangSmith tracing:", "ON" if configure_tracing() else "off (no LANGSMITH_API_KEY)")
        llm, model = OpenAILLM(settings.extraction_model, settings.openai_api_key), settings.extraction_model

    graph = build_graph(llm)
    scores, summary = evaluate(
        args.data, lambda path, tags, meta: run_document(graph, path, tags=tags, metadata=meta),
        limit=args.limit, workers=args.workers)

    usage = {"calls": llm.calls, "prompt_tokens": llm.prompt_tokens,
             "completion_tokens": llm.completion_tokens, "approx_cost_usd": llm.approx_cost_usd}
    print(format_report(summary, usage, scores))

    args.out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_file = args.out / f"{stamp}_{model}.json"
    result_file.write_text(json.dumps({
        "model": model, "seed": manifest["seed"], "summary": summary, "usage": usage,
        "documents": [s.__dict__ for s in scores]}, indent=2, default=str))
    print(f"\nFull results: {result_file}")


if __name__ == "__main__":
    main()
