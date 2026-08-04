from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mas_experiment.hiddenbench_data import load_hiddenbench_tasks  # noqa: E402
from mas_experiment.hiddenbench_official_results import (  # noqa: E402
    build_official_source_record,
    score_official_short_results,
)


BASE = (
    "https://huggingface.co/datasets/YuxuanLi1225/HiddenBench-results/"
    "resolve/main/short_and_ablations/"
)
SOURCES = {
    "baseline": BASE + "results_hidden_short_hidden_short.json",
    "reveal_all": BASE
    + "results_hidden_short_reveal_all_hidden_hidden_short_reveal_all_hidden.json",
}
DATASET_SHA = (
    "2815afffca4e470d1dfbc81e625160447df1109ce371968181c9e1e6b90443a3"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "hiddenbench-official-short",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tasks = load_hiddenbench_tasks(
        ROOT / "data" / "hiddenbench" / "benchmark.json",
        expected_sha256=DATASET_SHA,
    )
    summaries = {}
    for label, url in SOURCES.items():
        with urlopen(url, timeout=120) as response:  # noqa: S310
            content = response.read()
        raw_path = args.output_dir / f"official_{label}.json"
        raw_path.write_bytes(content)
        source = build_official_source_record(url=url, content=content)
        payload = json.loads(content)
        summaries[label] = score_official_short_results(
            payload,
            tasks,
            source=source,
        ).model_dump(mode="json")
    summary_path = args.output_dir / "official_short_summary.json"
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(summary_path)


if __name__ == "__main__":
    main()
