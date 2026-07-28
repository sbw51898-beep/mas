from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mas_experiment.domain import AgentResponse, Question
from mas_experiment.voting import NoValidAnswerError, majority_vote


QUESTION = Question(
    question_id="q",
    prompt="Choose.",
    options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
    correct_answer="A",
)


def response(answer: str, agent_id: str = "agent-a") -> AgentResponse:
    probabilities = (
        {"Z": 1.0}
        if answer == "Z"
        else {
            option: (0.7 if option == answer else 0.1)
            for option in QUESTION.options
        }
    )
    return AgentResponse(
        response_id=f"{agent_id}-{answer}",
        agent_id=agent_id,
        round_index=0,
        answer=answer,
        probabilities=probabilities,
        reasoning="A reason.",
        raw_text="{}",
        changed_from_previous=False,
        timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )


def test_majority_vote_selects_most_common_valid_answer() -> None:
    result = majority_vote(
        QUESTION,
        [response("B", "a"), response("B", "b"), response("A", "c")],
    )

    assert result.answer == "B"
    assert result.tie_break is False
    assert result.counts == {"A": 1, "B": 2}


def test_majority_vote_uses_question_order_for_tie() -> None:
    result = majority_vote(QUESTION, [response("B", "a"), response("A", "b")])

    assert result.answer == "A"
    assert result.tie_break is True


def test_majority_vote_ignores_answers_outside_question_options() -> None:
    result = majority_vote(QUESTION, [response("Z", "a"), response("C", "b")])

    assert result.answer == "C"
    assert result.counts == {"C": 1}


def test_majority_vote_rejects_no_valid_answers() -> None:
    with pytest.raises(NoValidAnswerError):
        majority_vote(QUESTION, [response("Z")])
