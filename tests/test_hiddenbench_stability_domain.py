from pathlib import Path

from mas_experiment.hiddenbench_stability_domain import (
    StudyKey,
    derive_pair_seed,
    load_stability_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_stability_config_locks_matrix_and_budget() -> None:
    config = load_stability_config(
        ROOT / "configs/hiddenbench-ai-disclosure-stability.json"
    )

    assert config.task_ids == (1, 5, 7, 25)
    assert config.conditions == ("fixed", "dynamic")
    assert config.repetitions == 10
    assert config.total_speeches == 60
    assert config.speeches_per_agent == 15
    assert config.selector_llm_calls == 0


def test_pair_seed_is_deterministic_and_shared_by_condition() -> None:
    first = derive_pair_seed(20260729, task_id=7, repetition=3)

    assert first == derive_pair_seed(20260729, task_id=7, repetition=3)
    assert first != derive_pair_seed(20260729, task_id=7, repetition=4)


def test_study_key_has_stable_serialized_value() -> None:
    key = StudyKey(task_id=25, condition="dynamic", repetition=9)

    assert key.value == "task-25:dynamic:rep-9"
