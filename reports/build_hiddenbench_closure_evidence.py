from __future__ import annotations

import argparse
import json
from pathlib import Path

from mas_experiment.hiddenbench_closure import build_closure_evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive bounded HiddenBench closure evidence from frozen JSONL files."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/data/hiddenbench-closure-evidence-20260817.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = build_closure_evidence(root)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
