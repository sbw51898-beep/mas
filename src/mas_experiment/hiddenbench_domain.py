from __future__ import annotations

import hashlib
import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mas_experiment.hiddenbench_data import HiddenBenchTask


AGENT_IDS = ("agent-a", "agent-b", "agent-c", "agent-d")
VoteCondition = Literal["hidden_pre", "hidden_post", "full_profile", "shadow"]
FailureMode = Literal["FM-2.4", "FM-2.5", "FM-2.6"]


def stable_shuffle(
    values: list[str],
    *,
    seed: int,
    namespace: str,
) -> None:
    digest = hashlib.sha256(
        f"{seed}|{namespace}".encode("utf-8")
    ).digest()
    random.Random(int.from_bytes(digest, "big")).shuffle(values)


class HiddenBenchAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: int
    seed: int
    shared_information: tuple[str, ...]
    private_information: dict[str, str]

    @model_validator(mode="after")
    def validate_assignment(self) -> HiddenBenchAssignment:
        if set(self.private_information) != set(AGENT_IDS):
            raise ValueError(
                "private_information must contain exactly the four "
                "HiddenBench agent IDs"
            )
        if len(set(self.private_information.values())) != len(AGENT_IDS):
            raise ValueError("each agent must receive one unique private fact")
        return self

    def visible_information_for(self, agent_id: str) -> tuple[str, ...]:
        if agent_id not in self.private_information:
            raise KeyError(f"unknown HiddenBench agent: {agent_id}")
        information = [
            *self.shared_information,
            self.private_information[agent_id],
        ]
        stable_shuffle(
            information,
            seed=self.seed,
            namespace=f"{self.task_id}:{agent_id}:hidden",
        )
        return tuple(information)


class PromptCompletion(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HiddenBenchVote(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    condition: VoteCondition
    vote: str
    rationale: str
    raw_text: str
    system_prompt: str
    user_prompt: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HiddenBenchMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    round_index: int = Field(ge=1)
    turn_index: int = Field(ge=0)
    agent_id: str
    content: str
    visible_message_ids: tuple[str, ...]
    system_prompt: str
    user_prompt: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HiddenBenchMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    y_pre_average: float = Field(ge=0, le=1)
    y_post_average: float = Field(ge=0, le=1)
    y_full_average: float = Field(ge=0, le=1)
    integration_gain: float = Field(ge=-1, le=1)
    full_profile_gap: float = Field(ge=-1, le=1)
    pre_majority_correct: bool
    post_majority_correct: bool
    full_majority_correct: bool
    pre_unanimous: bool
    post_unanimous: bool
    full_unanimous: bool
    consensus_round: int | None = None
    private_fact_disclosure_rate: float = Field(ge=0, le=1)
    cross_agent_use_rate: float = Field(ge=0, le=1)
    api_requests: int = Field(ge=0)
    repair_requests: int = Field(ge=0)
    usage: dict[str, int | float] = Field(default_factory=dict)


class MastCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    failure_mode: FailureMode
    agent_id: str
    owner_agent_id: str | None = None
    fact: str | None = None
    evidence_message_ids: tuple[str, ...] = ()
    evidence_text: tuple[str, ...]
    rule_version: str
    requires_manual_review: bool = True


class HiddenBenchRawRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    task: HiddenBenchTask
    assignment: HiddenBenchAssignment
    hidden_pre_votes: tuple[HiddenBenchVote, ...]
    discussion_messages: tuple[HiddenBenchMessage, ...]
    hidden_post_votes: tuple[HiddenBenchVote, ...]
    full_profile_votes: tuple[HiddenBenchVote, ...]
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    configuration_fingerprint: str
    code_commit: str


class HiddenBenchRun(HiddenBenchRawRun):
    metrics: HiddenBenchMetrics
    mast_candidates: tuple[MastCandidate, ...]


def assign_hidden_information(
    task: HiddenBenchTask,
    *,
    seed: int,
) -> HiddenBenchAssignment:
    if len(task.hidden_information) != len(AGENT_IDS):
        raise ValueError(
            "HiddenBench replication requires exactly four hidden facts"
        )
    private_facts = list(task.hidden_information)
    random.Random(seed + task.id).shuffle(private_facts)
    return HiddenBenchAssignment(
        task_id=task.id,
        seed=seed,
        shared_information=task.shared_information,
        private_information=dict(
            zip(AGENT_IDS, private_facts, strict=True)
        ),
    )
