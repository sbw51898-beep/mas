from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mas_experiment.domain import AgentResponse
from mas_experiment.selectors import score_candidates, select_next_speaker


def response(
    answer: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
) -> AgentResponse:
    return AgentResponse(
        response_id=f"{agent_id}-{answer}",
        agent_id=agent_id,
        round_index=0,
        answer=answer,
        confidence=confidence,
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
    chosen = select_next_speaker(
        agent_ids=("agent-a", "agent-b", "agent-c"),
        latest_responses={
            "agent-a": response("A", "agent-a"),
            "agent-b": response("A", "agent-b"),
            "agent-c": response("B", "agent-c"),
        },
        last_spoken_steps={"agent-a": 0, "agent-b": 0, "agent-c": 0},
        current_step=1,
    )

    assert chosen.agent_id == "agent-c"
    assert chosen.disagreement == 1.0
    assert chosen.selected is True


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
