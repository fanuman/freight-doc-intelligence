"""python -m freight_intel.synth --count 45 --seed 42 --out data/synthetic"""
import argparse
from collections import Counter
from pathlib import Path

from freight_intel.synth.writer import write_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic freight documents with ground truth.")
    parser.add_argument("--count", type=int, default=45, help="number of quote+invoice cases (default 45)")
    parser.add_argument("--seed", type=int, default=42, help="same seed => identical dataset")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()

    entries = write_dataset(args.count, args.seed, args.out)
    kinds = Counter(e["error_kind"] for e in entries)
    print(f"Wrote {len(entries)} cases to {args.out}/ (seed {args.seed})")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind:<18} {n}")
    print(f"  prompt-injection invoices: {sum(e['prompt_injection'] for e in entries)}")


if __name__ == "__main__":
    main()
