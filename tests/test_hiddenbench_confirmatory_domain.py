from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_confirmatory_domain import (
    CONFIRMATORY_CONDITIONS,
    ConfirmatoryStudyConfig,
    load_confirmatory_config,
    validate_confirmatory_tasks,
)
from mas_experiment.hiddenbench_data import load_hiddenbench_tasks


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
CONFIG = ROOT / "configs" / "hiddenbench-confirmatory-20260804.json"
EXPECTED_SHA = (
    "2815afffca4e470d1dfbc81e625160447df1109ce371968181c9e1e6b90443a3"
)


def _valid_payload() -> dict[str, object]:
    return {
        "configuration_version": "hiddenbench-confirmatory-v1",
        "task_ids": [1, 2, 3],
        "conditions": list(CONFIRMATORY_CONDITIONS),
        "repetitions": 10,
        "base_seed": 20260804,
        "dataset_sha256": EXPECTED_SHA,
        "frozen_code_commit": "b" * 40,
        "experiment_workers": 8,
        "judge_workers": 16,
        "provider": {
            "model": "deepseek-v4-flash",
            "temperature": 0,
            "thinking": "disabled",
        },
    }


def test_config_requires_exact_210_run_matrix() -> None:
    config = ConfirmatoryStudyConfig.model_validate(_valid_payload())

    assert config.expected_run_count == 210
    assert config.task_ids == (1, 2, 3)
    assert config.conditions == CONFIRMATORY_CONDITIONS


def test_official_short_tasks_are_exactly_ids_1_2_3() -> None:
    tasks = load_hiddenbench_tasks(DATASET, expected_sha256=EXPECTED_SHA)

    selected = validate_confirmatory_tasks(tasks)

    assert [task.id for task in selected] == [1, 2, 3]
    assert [task.name for task in selected] == [
        "evacuation_west_city",
        "evacuation_north_hill",
        "evacuation_east_town",
    ]


def test_wrong_task_set_is_rejected() -> None:
    payload = _valid_payload()
    payload["task_ids"] = [1, 5, 7]

    with pytest.raises(ValueError, match="1, 2, 3"):
        ConfirmatoryStudyConfig.model_validate(payload)


def test_wrong_model_is_rejected() -> None:
    payload = _valid_payload()
    payload["provider"] = {
        "model": "deepseek-chat",
        "temperature": 0,
        "thinking": "disabled",
    }

    with pytest.raises(ValueError, match="deepseek-v4-flash"):
        ConfirmatoryStudyConfig.model_validate(payload)


def test_checked_in_config_loads_and_matches_dataset() -> None:
    config = load_confirmatory_config(CONFIG)
    tasks = load_hiddenbench_tasks(
        DATASET,
        expected_sha256=config.dataset_sha256,
    )

    assert config.expected_run_count == 210
    assert len(validate_confirmatory_tasks(tasks)) == 3
    assert json.loads(CONFIG.read_text(encoding="utf-8"))["task_ids"] == [1, 2, 3]
