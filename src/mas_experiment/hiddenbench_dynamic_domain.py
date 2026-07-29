from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mas_experiment.hiddenbench_domain import AGENT_IDS, HiddenBenchRun


TieBreakReason = Literal[
    "highest_score",
    "remaining_quota",
    "raw_waiting",
    "agent_id",
]


class DynamicSelectorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    disagreement: float = Field(ge=0, le=1)
    undisclosed: float = Field(ge=0, le=1)
    related_discussion: float = Field(ge=0, le=1)
    response_due: float = Field(ge=0, le=1)
    waiting: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_weight_sum(self) -> DynamicSelectorConfig:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("selector weights must sum to 1")
        return self


class FrozenBaselineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    git_commit: str
    jsonl: str
    jsonl_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: str
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DynamicProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    temperature: float
    thinking: Literal["disabled"]


class DynamicPilotConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    configuration_version: Literal["hiddenbench-dynamic-pilot-v1"]
    pilot_task_ids: tuple[int, ...]
    base_seed: int
    dataset_sha256: str
    prompt_version: str
    total_speeches: int = Field(gt=0)
    speeches_per_agent: int = Field(gt=0)
    selector_llm_calls: int = Field(ge=0)
    selector: DynamicSelectorConfig
    evidence_rule_version: str
    provider: DynamicProviderConfig
    frozen_baseline: FrozenBaselineConfig

    @model_validator(mode="after")
    def validate_pilot(self) -> DynamicPilotConfig:
        if self.pilot_task_ids != (1, 5, 7):
            raise ValueError("pilot_task_ids must be exactly 1, 5, 7")
        if self.total_speeches != len(AGENT_IDS) * self.speeches_per_agent:
            raise ValueError("total speech budget must equal per-agent quotas")
        if self.selector_llm_calls != 0:
            raise ValueError("speaker selection must not call an LLM")
        return self


class InformationAtom(BaseModel):
    model_config = ConfigDict(frozen=True)

    atom_id: str
    owner_agent_id: str
    index: int = Field(ge=0)
    text: str = Field(min_length=1)


class SelectorCandidateScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    disagreement: float = Field(ge=0, le=1)
    undisclosed: float = Field(ge=0, le=1)
    related_discussion: float = Field(ge=0, le=1)
    response_due: float = Field(ge=0, le=1)
    waiting: float = Field(ge=0, le=1)
    weighted_total: float = Field(ge=0, le=1)
    remaining_quota: int = Field(ge=0)
    raw_waiting: int = Field(ge=0)
    latest_stance: str | None
    evidence_atom_ids: tuple[str, ...] = ()
    selected: bool = False
    tie_break_reason: TieBreakReason | None = None


class SelectorEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: int
    turn_index: int = Field(ge=0, lt=60)
    round_index: int = Field(ge=1, le=15)
    selected_agent_id: str
    candidates: tuple[SelectorCandidateScore, ...]

    @model_validator(mode="after")
    def validate_selection(self) -> SelectorEvent:
        selected = tuple(item for item in self.candidates if item.selected)
        if len(selected) != 1:
            raise ValueError("selector event must contain one selected candidate")
        if selected[0].agent_id != self.selected_agent_id:
            raise ValueError("selected candidate must match selected_agent_id")
        return self


class DynamicHiddenBenchRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    orchestration_mode: Literal["dynamic"] = "dynamic"
    baseline_run_id: str
    dynamic_configuration_fingerprint: str
    run: HiddenBenchRun
    selection_events: tuple[SelectorEvent, ...]

    @model_validator(mode="after")
    def validate_trace_length(self) -> DynamicHiddenBenchRun:
        if len(self.selection_events) != 60:
            raise ValueError("dynamic run requires exactly 60 selector events")
        return self


def load_dynamic_pilot_config(path: Path) -> DynamicPilotConfig:
    return DynamicPilotConfig.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
