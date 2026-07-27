from __future__ import annotations

import pytest
from pydantic import ValidationError

from mas_experiment.domain import AgentResponse, Question


def test_response_rejects_confidence_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(
            response_id="r1",
            agent_id="agent-a",
            round_index=0,
            answer="A",
            confidence=1.1,
            reasoning="Because A follows from the evidence.",
            raw_text='{"answer":"A"}',
            changed_from_previous=False,
        )


def test_question_rejects_correct_answer_not_in_options() -> None:
    with pytest.raises(ValidationError):
        Question(
            question_id="q1",
            prompt="Choose one.",
            options={"A": "One", "B": "Two"},
            correct_answer="C",
        )


def test_question_is_immutable() -> None:
    question = Question(
        question_id="q1",
        prompt="Choose one.",
        options={"A": "One", "B": "Two"},
        correct_answer="A",
    )

    with pytest.raises(ValidationError):
        question.correct_answer = "B"
