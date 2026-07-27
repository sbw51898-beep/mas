from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mas_experiment.domain import AgentResponse, Message, Question
from mas_experiment.selectors import score_candidates, select_next_speaker


def response(
    answer: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
    probabilities: dict[str, float] | None = None,
) -> AgentResponse:
    other_probability = (1.0 - confidence) / 3
    selected_probabilities = probabilities or {
        option: (confidence if option == answer else other_probability)
        for option in ("A", "B", "C", "D")
    }
    return AgentResponse(
        response_id=f"{agent_id}-{answer}",
        agent_id=agent_id,
        round_index=0,
        answer=answer,
        probabilities=selected_probabilities,
        reasoning="A reason.",
        raw_text="{}",
        changed_from_previous=False,
        timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )


def test_unseen_agents_start_with_maximum_score() -> None:
    scores = score_candidates(
        agent_ids=("agent-a", "agent-b"),
        latest_responses={},
        last_spoken_steps={},
        current_step=0,
    )

    assert [score.agent_id for score in scores] == ["agent-a", "agent-b"]
    assert all(score.disagreement == 1.0 for score in scores)
    assert all(score.waiting == 1.0 for score in scores)
    assert all(score.uncertainty == 1.0 for score in scores)
    assert all(score.total == pytest.approx(1.0) for score in scores)


def test_selector_prefers_disagreement_when_other_factors_are_equal() -> None:
    scores = score_candidates(
        agent_ids=("agent-a", "agent-b", "agent-c"),
        latest_responses={
            "agent-a": response(
                "A",
                "agent-a",
                probabilities={"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1},
            ),
            "agent-b": response(
                "A",
                "agent-b",
                probabilities={"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1},
            ),
            "agent-c": response(
                "B",
                "agent-c",
                probabilities={"A": 0.1, "B": 0.7, "C": 0.1, "D": 0.1},
            ),
        },
        last_spoken_steps={"agent-a": 0, "agent-b": 0, "agent-c": 0},
        current_step=1,
    )

    by_agent = {score.agent_id: score for score in scores}
    assert scores[0].agent_id == "agent-c"
    assert (
        by_agent["agent-c"].disagreement
        > by_agent["agent-a"].disagreement
    )


def test_selector_uses_waiting_time_when_answers_and_confidence_match() -> None:
    chosen = select_next_speaker(
        agent_ids=("agent-a", "agent-b"),
        latest_responses={
            "agent-a": response("A", "agent-a"),
            "agent-b": response("A", "agent-b"),
        },
        last_spoken_steps={"agent-a": 4, "agent-b": 1},
        current_step=5,
    )

    assert chosen.agent_id == "agent-b"
    assert chosen.waiting == pytest.approx(1.0)


def test_selector_uses_uncertainty_when_other_factors_match() -> None:
    chosen = select_next_speaker(
        agent_ids=("agent-a", "agent-b"),
        latest_responses={
            "agent-a": response("A", "agent-a", confidence=0.9),
            "agent-b": response("A", "agent-b", confidence=0.5),
        },
        last_spoken_steps={"agent-a": 0, "agent-b": 0},
        current_step=1,
    )

    assert chosen.agent_id == "agent-b"
    assert chosen.uncertainty == pytest.approx(0.5)


def test_equal_scores_use_ascending_agent_id() -> None:
    chosen = select_next_speaker(
        agent_ids=("agent-b", "agent-a"),
        latest_responses={},
        last_spoken_steps={},
        current_step=0,
    )

    assert chosen.agent_id == "agent-a"


def test_unexposed_dependency_information_can_outrank_waiting_time() -> None:
    question = Question(
        question_id="hidden",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
        correct_answer="A",
        information_keywords={
            "agent-a": ("secret-a",),
            "agent-b": ("secret-b",),
        },
        dependency_keywords={
            "agent-a": ("trigger-a",),
            "agent-b": (),
        },
    )
    public_messages = (
        Message(
            message_id="m0",
            speaker="agent-a",
            round_index=0,
            content="No private value disclosed.",
        ),
        Message(
            message_id="m1",
            speaker="agent-b",
            round_index=0,
            content="secret-b and trigger-a",
        ),
    )

    scores = score_candidates(
        agent_ids=("agent-a", "agent-b"),
        latest_responses={
            "agent-a": response("A", "agent-a"),
            "agent-b": response("A", "agent-b"),
        },
        last_spoken_steps={"agent-a": 0, "agent-b": -2},
        current_step=1,
        question=question,
        public_messages=public_messages,
    )

    assert scores[0].agent_id == "agent-a"
    assert scores[0].information_exposure == pytest.approx(1.0)
    assert scores[0].dependency_trigger == pytest.approx(1.0)


def test_selector_recognizes_model_output_without_dimension_prefix() -> None:
    question = Question(
        question_id="hidden-prefix",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
        correct_answer="A",
        information_keywords={"agent-a": ("ACCESS_A=92",)},
        dependency_keywords={"agent-a": ("MEDICAL_B=78",)},
    )
    messages = (
        Message(
            message_id="m1",
            speaker="agent-b",
            round_index=0,
            content="Medical readiness includes B=78.",
        ),
    )

    score = score_candidates(
        agent_ids=("agent-a",),
        latest_responses={"agent-a": response("A", "agent-a")},
        last_spoken_steps={"agent-a": -1},
        current_step=0,
        question=question,
        public_messages=messages,
    )[0]

    assert score.information_exposure == pytest.approx(1.0)
    assert score.dependency_trigger == pytest.approx(1.0)


def test_selector_does_not_expose_same_alias_spoken_by_wrong_owner() -> None:
    question = Question(
        question_id="collision",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
        correct_answer="A",
        information_keywords={
            "agent-a": ("THREAT_C=88",),
            "agent-b": ("CONTINUITY_C=88",),
        },
    )
    messages = (
        Message(
            message_id="m1",
            speaker="agent-a",
            round_index=1,
            content="My threat score is C=88.",
        ),
    )

    scores = score_candidates(
        agent_ids=("agent-a", "agent-b"),
        latest_responses={
            "agent-a": response("A", "agent-a"),
            "agent-b": response("A", "agent-b"),
        },
        last_spoken_steps={"agent-a": 0},
        current_step=1,
        question=question,
        public_messages=messages,
    )
    by_agent = {score.agent_id: score for score in scores}

    assert by_agent["agent-a"].information_exposure == pytest.approx(0.0)
    assert by_agent["agent-b"].information_exposure == pytest.approx(1.0)
