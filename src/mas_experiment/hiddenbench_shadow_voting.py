from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
    HiddenBenchRawRun,
    HiddenBenchVote,
)
from mas_experiment.hiddenbench_prompts import build_vote_user_prompt


class ShadowVoteCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    round_index: int = Field(ge=1)
    after_public_message_count: int = Field(ge=4)
    votes: tuple[HiddenBenchVote, ...]

    @model_validator(mode="after")
    def validate_checkpoint(self) -> ShadowVoteCheckpoint:
        if self.after_public_message_count != self.round_index * len(AGENT_IDS):
            raise ValueError("checkpoint must follow one complete public round")
        if len(self.votes) != len(AGENT_IDS):
            raise ValueError("checkpoint requires exactly four shadow votes")
        if {vote.agent_id for vote in self.votes} != set(AGENT_IDS):
            raise ValueError("checkpoint requires one vote per agent")
        if any(vote.condition != "shadow" for vote in self.votes):
            raise ValueError("checkpoint votes must use shadow condition")
        return self


class EarlyStopCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    round_index: int = Field(ge=2)
    answer: str


class EarlyStopEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_round: int | None
    candidate_answer: str | None
    final_votes: tuple[str, ...]
    exact_match: bool | None
    candidate_correct: bool | None
    final_correct: bool
    saved_public_messages: int = Field(ge=0)


class ShadowVotingRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run: HiddenBenchRawRun
    shadow_checkpoints: tuple[ShadowVoteCheckpoint, ...]
    early_stop: EarlyStopEvaluation

    @model_validator(mode="after")
    def validate_trace(self) -> ShadowVotingRun:
        expected = len(self.run.discussion_messages) // len(AGENT_IDS)
        if len(self.shadow_checkpoints) != expected:
            raise ValueError("one shadow checkpoint is required per public round")
        return self


def _unanimous_answer(checkpoint: ShadowVoteCheckpoint) -> str | None:
    answers = {vote.vote for vote in checkpoint.votes}
    return next(iter(answers)) if len(answers) == 1 else None


def find_candidate_stop(
    checkpoints: tuple[ShadowVoteCheckpoint, ...],
) -> EarlyStopCandidate | None:
    for previous, current in zip(checkpoints, checkpoints[1:]):
        previous_answer = _unanimous_answer(previous)
        current_answer = _unanimous_answer(current)
        if previous_answer is not None and previous_answer == current_answer:
            return EarlyStopCandidate(
                round_index=current.round_index,
                answer=current_answer,
            )
    return None


def evaluate_early_stop(
    checkpoints: tuple[ShadowVoteCheckpoint, ...],
    *,
    final_votes: tuple[HiddenBenchVote, ...],
    correct_answer: str,
    total_public_messages: int,
) -> EarlyStopEvaluation:
    candidate = find_candidate_stop(checkpoints)
    answers = tuple(vote.vote for vote in final_votes)
    counts = Counter(answers)
    ranked = counts.most_common()
    final_majority_answer = (
        ranked[0][0]
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1])
        else None
    )
    if candidate is None:
        return EarlyStopEvaluation(
            candidate_round=None,
            candidate_answer=None,
            final_votes=answers,
            exact_match=None,
            candidate_correct=None,
            final_correct=final_majority_answer == correct_answer,
            saved_public_messages=0,
        )
    used_messages = candidate.round_index * len(AGENT_IDS)
    return EarlyStopEvaluation(
        candidate_round=candidate.round_index,
        candidate_answer=candidate.answer,
        final_votes=answers,
        exact_match=(
            final_majority_answer is not None
            and candidate.answer == final_majority_answer
        ),
        candidate_correct=candidate.answer == correct_answer,
        final_correct=final_majority_answer == correct_answer,
        saved_public_messages=max(0, total_public_messages - used_messages),
    )


async def collect_shadow_votes(
    task: HiddenBenchTask,
    provider: Any,
    *,
    system_prompts: Mapping[str, str],
    public_history: tuple[HiddenBenchMessage, ...],
    round_index: int,
    seed: int,
) -> ShadowVoteCheckpoint:
    # Local import avoids a module cycle: the fixed protocol owns vote parsing.
    from mas_experiment.hiddenbench_protocol import complete_hiddenbench_vote

    votes: list[HiddenBenchVote] = []
    for agent_index, agent_id in enumerate(AGENT_IDS):
        try:
            vote = await complete_hiddenbench_vote(
                task,
                provider,
                agent_id=agent_id,
                condition="shadow",
                system_prompt=system_prompts[agent_id],
                user_prompt=build_vote_user_prompt(
                    task,
                    public_history,
                    phase="hidden_post",
                ),
                seed=seed + round_index * 100 + agent_index,
            )
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} shadow vote failed for {agent_id} "
                f"after round {round_index}"
            ) from error
        votes.append(vote)
    return ShadowVoteCheckpoint(
        round_index=round_index,
        after_public_message_count=len(public_history),
        votes=tuple(votes),
    )
