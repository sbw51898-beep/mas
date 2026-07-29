from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "reports" / "build_hiddenbench_official_comparison.py"
)
SPEC = importlib.util.spec_from_file_location(
    "hiddenbench_official_comparison", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_official_scoring_matches_hiddenbench_majority_definition() -> None:
    runs = [
        {
            "initial_votes": [
                {"vote": "A"},
                {"vote": "B"},
                {"vote": "B"},
                {"vote": "B"},
            ],
            "final_votes": [
                {"vote": "A"},
                {"vote": "A"},
                {"vote": "A"},
                {"vote": "B"},
            ],
            "majority_vote": "A",
            "rounds": [{}] * 15,
        },
        {
            "initial_votes": [
                {"vote": "A"},
                {"vote": "A"},
                {"vote": "B"},
                {"vote": "B"},
            ],
            "final_votes": [
                {"vote": "A"},
                {"vote": "A"},
                {"vote": "B"},
                {"vote": "B"},
            ],
            "majority_vote": "B",
            "rounds": [{}] * 15,
        },
    ]

    result = MODULE._score_runs(runs, "A")

    assert result["runs"] == 2
    assert result["pre_average_accuracy"] == 0.375
    assert result["post_average_accuracy"] == 0.625
    assert result["pre_majority_accuracy"] == 0.0
    assert result["post_majority_accuracy"] == 0.5
    assert result["rounds"] == [15]


def test_local_summary_loader_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "summary.csv"
    path.write_text(
        "task_id,condition,repetitions\n1,fixed,10\n",
        encoding="utf-8-sig",
    )

    result = MODULE._load_local_summary(path)

    assert result[(1, "fixed")]["repetitions"] == "10"
