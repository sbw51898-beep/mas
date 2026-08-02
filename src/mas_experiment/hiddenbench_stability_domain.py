from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchRun,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicProviderConfig,
    DynamicSelectorConfig,
    SelectorEvent,
)


StudyCondition = Literal[
    "fixed",
    "dynamic",
    "fixed-disc",
    "dynamic-disc",
    "structured",
]
DynamicProviderSettings = DynamicProviderConfig
SelectorWeights = DynamicSelectorConfig


class StabilityStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: Literal[
        "hiddenbench-stability-v1",
        "hiddenbench-stability-v2",
    ]
    task_ids: tuple[int, ...]
    conditions: tuple[StudyCondition, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_source: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    total_speeches: Literal[60]
    speeches_per_agent: Literal[15]
    selector_llm_calls: Literal[0]
    experiment_workers: int = Field(ge=1, le=16)
    judge_workers: int = Field(ge=1, le=16)
    judge_model: str = Field(min_length=1)
    judge_prompt_version: str = Field(min_length=1)
    evidence_rule_version: str = Field(min_length=1)
    provider: DynamicProviderSettings
    selector: SelectorWeights
    frozen_baseline_commit: str = Field(min_length=7)
    disclosure_first: bool = False

    @model_validator(mode="after")
    def validate_frozen_protocol(self) -> StabilityStudyConfig:
        if self.task_ids != (1, 5, 7, 25):
            raise ValueError("task_ids must be exactly 1, 5, 7, 25")
        allowed_condition_sets = {
            "hiddenbench-stability-v1": (("fixed", "dynamic"),),
            "hiddenbench-stability-v2": (
                ("fixed-disc", "dynamic-disc"),
            ),
        }
        allowed = allowed_condition_sets[self.configuration_version]
        if self.conditions not in allowed:
            raise ValueError(
                f"{self.configuration_version} requires conditions "
                f"{allowed[0]}, got {self.conditions}"
            )
        if self.disclosure_first != any(
            condition.endswith("-disc") for condition in self.conditions
        ):
            raise ValueError(
                "disclosure_first must match the -disc conditions"
            )
        if self.repetitions != 10:
            raise ValueError("repetitions must be exactly 10")
        if self.total_speeches != len(AGENT_IDS) * self.speeches_per_agent:
            raise ValueError("total speech budget must equal per-agent quotas")
        if self.selector_llm_calls != 0:
            raise ValueError("speaker selection must not call an LLM")
        return self


class StudyKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: StudyCondition
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return (
            f"task-{self.task_id}:{self.condition}:"
            f"rep-{self.repetition}"
        )


class StudyRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: StudyKey
    pair_seed: int
    assignment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    run: HiddenBenchRun
    baseline_run_id: str | None = None
    selection_events: tuple[SelectorEvent, ...] = ()

    @model_validator(mode="after")
    def validate_key_and_condition(self) -> StudyRunRecord:
        if self.run.task.id != self.key.task_id:
            raise ValueError("study key task must match run task")
        if self.run.assignment.seed != self.pair_seed:
            raise ValueError("pair seed must match run assignment seed")
        if self.key.condition in ("fixed", "fixed-disc"):
            if self.baseline_run_id is not None or self.selection_events:
                raise ValueError(
                    "fixed record cannot contain dynamic metadata"
                )
        else:
            if not self.baseline_run_id:
                raise ValueError("dynamic record requires baseline_run_id")
            if len(self.selection_events) != 60:
                raise ValueError(
                    "dynamic record requires 60 selector events"
                )
        return self


def derive_pair_seed(
    base_seed: int,
    *,
    task_id: int,
    repetition: int,
) -> int:
    payload = f"{base_seed}|{task_id}|{repetition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def assignment_fingerprint(run: HiddenBenchRun) -> str:
    payload = json.dumps(
        run.assignment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_stability_config(path: Path) -> StabilityStudyConfig:
    return StabilityStudyConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )
