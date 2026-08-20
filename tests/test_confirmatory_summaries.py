from __future__ import annotations

import hashlib
from pathlib import Path

from reports.build_confirmatory_summaries import (
    build_confirmatory_summary,
    build_historical_summary,
    write_confirmatory_summaries,
)


ROOT = Path(__file__).parents[1]
ARTIFACTS = ROOT / "artifacts"


def test_confirmatory_summary_recomputes_locked_totals() -> None:
    summary = build_confirmatory_summary(
        runs_path=ARTIFACTS / "hiddenbench-confirmatory-20260804.jsonl",
        audits_path=ARTIFACTS
        / "hiddenbench-confirmatory-20260804.audits.jsonl",
        gate_path=ARTIFACTS / "hiddenbench-confirmatory-20260804.gate.json",
    )

    assert summary["run_count"] == 210
    assert summary["audit_count"] == 210
    assert summary["condition_count"] == 7
    assert summary["task_ids"] == [1, 2, 3]
    assert summary["run_api_requests"] == 11971
    assert summary["audit_api_requests"] == 152
    assert summary["early_stop"]["candidate_runs"] == 30
    assert summary["early_stop"]["exact_match_false"] == 1
    assert summary["gate_passed"] is True


def test_historical_appendix_uses_correct_400_run_scope() -> None:
    historical = build_historical_summary(ARTIFACTS)

    assert historical["total_conditions"] == 10
    assert historical["total_runs"] == 400
    assert historical["multi_agent_correct_range"] == [14, 24]
    assert historical["earlystop_by_task"]["fixed-4"] == {
        "1": 10,
        "5": 0,
        "7": 1,
        "25": 9,
    }
    assert historical["earlystop_by_task"]["fixed-8"] == {
        "1": 10,
        "5": 0,
        "7": 2,
        "25": 8,
    }
    assert historical["earlystop_by_task"]["fixed"] == {
        "1": 10,
        "5": 0,
        "7": 2,
        "25": 8,
    }


def test_summary_outputs_are_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    paths_one = write_confirmatory_summaries(
        root=ROOT,
        output_dir=first,
    )
    paths_two = write_confirmatory_summaries(
        root=ROOT,
        output_dir=second,
    )

    assert set(paths_one) == set(paths_two)
    for name in paths_one:
        assert hashlib.sha256(paths_one[name].read_bytes()).digest() == (
            hashlib.sha256(paths_two[name].read_bytes()).digest()
        )
