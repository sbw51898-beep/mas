from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_dynamic_domain import DynamicProviderConfig


ConfirmatoryCondition = Literal[
    "fixed-60",
    "dynamic-60",
    "fixed-reveal-all",
    "dynamic-reveal-all",
    "structured-12",
    "fixed-12",
    "single-local",
]

CONFIRMATORY_CONDITIONS: tuple[ConfirmatoryCondition, ...] = (
    "fixed-60",
    "dynamic-60",
    "fixed-reveal-all",
    "dynamic-reveal-all",
    "structured-12",
    "fixed-12",
    "single-local",
)

CONFIRMATORY_TASK_NAMES = {
    1: "evacuation_west_city",
    2: "evacuation_north_hill",
    3: "evacuation_east_town",
}


class ConfirmatoryStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: Literal["hiddenbench-confirmatory-v1"]
    task_ids: tuple[int, ...]
    conditions: tuple[ConfirmatoryCondition, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    frozen_code_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    experiment_workers: int = Field(ge=1, le=16)
    judge_workers: int = Field(ge=1, le=32)
    provider: DynamicProviderConfig

    @model_validator(mode="after")
    def validate_confirmatory_lock(self) -> ConfirmatoryStudyConfig:
        if self.task_ids != (1, 2, 3):
            raise ValueError("task_ids must be exactly 1, 2, 3")
        if self.conditions != CONFIRMATORY_CONDITIONS:
            raise ValueError("conditions must match the locked seven-condition order")
        if self.repetitions != 10:
            raise ValueError("repetitions must be exactly 10")
        if self.provider.model != "deepseek-v4-flash":
            raise ValueError("provider model must be deepseek-v4-flash")
        if self.provider.temperature != 0:
            raise ValueError("provider temperature must be 0")
        if self.provider.thinking != "disabled":
            raise ValueError("provider thinking must be disabled")
        return self

    @computed_field
    @property
    def expected_run_count(self) -> int:
        return len(self.task_ids) * len(self.conditions) * self.repetitions


class ConfirmatoryStudyKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: ConfirmatoryCondition
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return (
            f"task-{self.task_id}:{self.condition}:"
            f"rep-{self.repetition}"
        )


def load_confirmatory_config(path: Path) -> ConfirmatoryStudyConfig:
    return ConfirmatoryStudyConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def validate_confirmatory_tasks(
    tasks: tuple[HiddenBenchTask, ...],
) -> tuple[HiddenBenchTask, ...]:
    by_id = {task.id: task for task in tasks}
    selected: list[HiddenBenchTask] = []
    for task_id, expected_name in CONFIRMATORY_TASK_NAMES.items():
        task = by_id.get(task_id)
        if task is None:
            raise ValueError(f"official confirmatory task missing: {task_id}")
        if task.name != expected_name:
            raise ValueError(
                f"confirmatory task {task_id} name mismatch: "
                f"expected {expected_name}, found {task.name}"
            )
        if len(task.hidden_information) != 4:
            raise ValueError(
                f"confirmatory task {task_id} must have four private facts"
            )
        selected.append(task)
    return tuple(selected)
