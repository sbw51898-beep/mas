from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    prompt: str
    options: dict[str, str]
    correct_answer: str

    @model_validator(mode="after")
    def validate_correct_answer(self) -> Question:
        if self.correct_answer not in self.options:
            raise ValueError("correct_answer must be one of the question options")
        return self


class AgentRole(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    system_prompt: str


class AgentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    response_id: str
    agent_id: str
    round_index: int = Field(ge=0)
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    raw_text: str
    changed_from_previous: bool
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    speaker: str
    round_index: int = Field(ge=0)
    content: str
    visible_history_ids: tuple[str, ...] = ()
    user_prompt: str = ""


class SelectionScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=0)
    agent_id: str
    disagreement: float = Field(ge=0.0, le=1.0)
    waiting: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    total: float = Field(ge=0.0, le=1.0)
    selected: bool = False


class ExperimentMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    accuracy: float = Field(ge=0.0, le=1.0)
    consensus_rate: float = Field(ge=0.0, le=1.0)
    wrong_consensus: bool
    flip_rate: float = Field(ge=0.0, le=1.0)
    pairwise_disagreement: float = Field(ge=0.0, le=1.0)
    answer_entropy: float = Field(ge=0.0, le=1.0)
    speaker_share: dict[str, float]


class ExperimentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    mode: str
    seed: int
    question: Question
    roles: tuple[AgentRole, ...]
    messages: tuple[Message, ...]
    responses: tuple[AgentResponse, ...]
    selection_scores: tuple[SelectionScore, ...] = ()
    final_answer: str | None = None
    tie_break: bool = False
    metrics: ExperimentMetrics | None = None
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ModelProvider(Protocol):
    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        raise NotImplementedError
