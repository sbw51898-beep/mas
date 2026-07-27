from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from mas_experiment.domain import AgentResponse, Question


class NoValidAnswerError(ValueError):
    """Raised when no response contains an answer from the question."""


class VoteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    tie_break: bool
    counts: dict[str, int]


def majority_vote(
    question: Question,
    responses: list[AgentResponse] | tuple[AgentResponse, ...],
) -> VoteResult:
    counts = Counter(
        response.answer
        for response in responses
        if response.answer in question.options
    )
    if not counts:
        raise NoValidAnswerError("no response contains a valid question option")

    highest_count = max(counts.values())
    tied_answers = {
        answer for answer, count in counts.items() if count == highest_count
    }
    selected = next(answer for answer in question.options if answer in tied_answers)
    ordered_counts = {
        answer: counts[answer] for answer in question.options if answer in counts
    }
    return VoteResult(
        answer=selected,
        tie_break=len(tied_answers) > 1,
        counts=ordered_counts,
    )
