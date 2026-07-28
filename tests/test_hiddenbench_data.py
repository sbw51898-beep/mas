from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import (
    load_hiddenbench_task,
    load_hiddenbench_tasks,
)


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
CONFIG = ROOT / "configs" / "hiddenbench-screening.json"
EXPECTED_SHA = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)


def test_official_snapshot_has_expected_hash_and_65_tasks() -> None:
    tasks = load_hiddenbench_tasks(DATASET, expected_sha256=EXPECTED_SHA)

    assert len(tasks) == 65


def test_showcase_task_matches_official_record() -> None:
    task = load_hiddenbench_task(
        DATASET,
        task_id=25,
        expected_sha256=EXPECTED_SHA,
    )

    assert task.name == "select_emergency_shelter"
    assert len(task.shared_information) == 4
    assert len(task.hidden_information) == 4
    assert len(task.possible_answers) == 4
    assert task.correct_answer == "Station Delta"
    assert task.rationale


def test_locked_screening_ids_all_exist() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    tasks = load_hiddenbench_tasks(DATASET, expected_sha256=EXPECTED_SHA)
    selected = [
        task
        for task in tasks
        if task.id in config["screening_task_ids"]
    ]

    assert set(config["screening_task_ids"]) <= {task.id for task in tasks}
    assert all(len(task.hidden_information) == 4 for task in selected)


def test_tampered_snapshot_is_rejected(tmp_path: Path) -> None:
    tampered = tmp_path / "benchmark.json"
    tampered.write_bytes(DATASET.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_hiddenbench_tasks(tampered, expected_sha256=EXPECTED_SHA)


def test_duplicate_task_id_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload[1]["id"] = payload[0]["id"]
    duplicate = tmp_path / "benchmark.json"
    duplicate.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    duplicate_sha = hashlib.sha256(duplicate.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="duplicate HiddenBench task ID"):
        load_hiddenbench_tasks(
            duplicate,
            expected_sha256=duplicate_sha,
        )
