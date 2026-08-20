from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_tasks
from mas_experiment.hiddenbench_official_results import (
    build_official_source_record,
    score_official_short_results,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "official_hidden_short_minimal.json"
TASKS = load_hiddenbench_tasks(
    ROOT / "data" / "hiddenbench" / "benchmark.json",
    expected_sha256=(
        "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
    ),
)


def test_scores_legacy_official_results_per_task() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    result = score_official_short_results(payload, TASKS)

    west = result.by_task[1]
    assert result.model == "gpt-4.1"
    assert west.runs == 2
    assert west.average_accuracy == 0.75
    assert west.majority_accuracy == 0.5
    assert west.unanimous_correct_rate == 0.5
    assert west.false_consensus_rate == 0.0
    east = result.by_task[3]
    assert east.average_accuracy == 0.0
    assert east.false_consensus_rate == 1.0


def test_source_record_hashes_exact_downloaded_bytes() -> None:
    content = FIXTURE.read_bytes()

    source = build_official_source_record(
        url="https://example.test/official.json",
        content=content,
    )

    assert source.bytes == len(content)
    assert len(source.sha256) == 64
    assert source.url.endswith("official.json")


def test_unknown_scenario_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["conditions"][0]["runs"][0]["scenario"] = "unknown"

    with pytest.raises(ValueError, match="scenario"):
        score_official_short_results(payload, TASKS)
