from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    prompt: str
    options: dict[str, str]
    correct_answer: str
    public_context: str = ""
    private_contexts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_correct_answer(self) -> Question:
        if self.correct_answer not in self.options:
            raise ValueError("correct_answer must be one of the question options")
        return self

    def private_context_for(self, agent_id: str) -> str:
        return self.private_contexts.get(agent_id, "")


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
    probabilities: dict[str, float]
    reasoning: str
    raw_text: str
    changed_from_previous: bool
    answer_tie_break: bool = False
    provider_metadata: Mapping[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(
        cls,
        values: dict[str, float],
    ) -> dict[str, float]:
        if not values:
            raise ValueError("probabilities must not be empty")
        parsed = {key: float(value) for key, value in values.items()}
        if any(value < 0.0 or value > 1.0 for value in parsed.values()):
            raise ValueError("probabilities must be from 0 to 1")
        total = sum(parsed.values())
        if total <= 0.0 or abs(total - 1.0) > 0.01:
            raise ValueError("probabilities must sum to 1")
        return {key: value / total for key, value in parsed.items()}

    @model_validator(mode="after")
    def validate_answer(self) -> AgentResponse:
        if self.answer not in self.probabilities:
            raise ValueError("answer must be present in probabilities")
        maximum = max(self.probabilities.values())
        first_winner = next(
            key
            for key, value in self.probabilities.items()
            if abs(value - maximum) <= 1e-12
        )
        if self.answer != first_winner:
            raise ValueError(
                "answer must equal the highest-probability option"
            )
        return self

    @computed_field
    @property
    def confidence(self) -> float:
        return max(self.probabilities.values())


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    speaker: str
    round_index: int = Field(ge=0)
    content: str
    visible_history_ids: tuple[str, ...] = ()
    user_prompt: str = ""


class InitialState(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_state_id: str
    question_id: str
    agent_ids: tuple[str, ...]
    messages: tuple[Message, ...]
    responses: tuple[AgentResponse, ...]
    errors: tuple[str, ...] = ()


class SelectionScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=0)
    agent_id: str
    disagreement: float = Field(ge=0.0, le=1.0)
    waiting: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    total: float = Field(ge=0.0, le=1.0)
    selected: bool = False


class BeliefState(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_option: str
    beliefs: dict[str, float]
    mean_b: float = Field(ge=-1.0, le=1.0)
    order_parameter_r: float = Field(ge=0.0, le=1.0)
    temperature_proxy: float = Field(ge=0.0, le=1.0)
    entropy_proxy: float = Field(ge=0.0, le=1.0)
    disorder_proxy: float = Field(ge=0.0)


class ExperimentMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    accuracy: float = Field(ge=0.0, le=1.0)
    majority_share: float = Field(ge=0.0, le=1.0)
    unanimity: bool
    wrong_consensus: bool
    flip_rate: float = Field(ge=0.0, le=1.0)
    pairwise_disagreement: float = Field(ge=0.0, le=1.0)
    answer_entropy: float = Field(ge=0.0, le=1.0)
    js_disagreement: float = Field(ge=0.0, le=1.0)
    group_brier: float = Field(ge=0.0)
    speaker_share: dict[str, float]
    pooled_probabilities: dict[str, float]
    pooled_answer: str
    majority_answer: str
    pooled_tie_break: bool = False
    runtime_belief_state: BeliefState
    evaluation_belief_state: BeliefState


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
