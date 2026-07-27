from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mas_experiment.domain import AgentResponse, Question
from mas_experiment.metrics import calculate_metrics


QUESTION = Question(
    question_id="q",
    prompt="Choose.",
    options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
    correct_answer="A",
)


def response(
    answer: str,
    agent_id: str,
    round_index: int = 0,
    *,
    changed: bool = False,
) -> AgentResponse:
    return AgentResponse(
        response_id=f"{agent_id}-{round_index}",
        agent_id=agent_id,
        round_index=round_index,
        answer=answer,
        confidence=0.8,
        reasoning="A reason.",
        raw_text="{}",
        changed_from_previous=changed,
        timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )


def test_wrong_consensus_requires_unanimous_incorrect_answer() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[
            response("B", "a"),
            response("B", "b"),
            response("B", "c"),
        ],
        final_answer="B",
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )

    assert metrics.accuracy == 0.0
    assert metrics.wrong_consensus is True
    assert metrics.consensus_rate == 1.0
    assert metrics.pairwise_disagreement == 0.0


def test_normalized_entropy_is_one_for_uniform_four_way_split() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[
            response("A", "a"),
            response("B", "b"),
            response("C", "c"),
            response("D", "d"),
        ],
        final_answer="A",
        speaker_counts={"a": 1, "b": 1, "c": 1, "d": 1},
    )

    assert metrics.answer_entropy == pytest.approx(1.0)
    assert metrics.consensus_rate == pytest.approx(0.25)
    assert metrics.pairwise_disagreement == pytest.approx(1.0)


def test_flip_rate_uses_agent_trajectories() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[
            response("A", "a", 0),
            response("B", "b", 0),
            response("B", "a", 1, changed=True),
            response("B", "b", 1),
        ],
        final_answer="B",
        speaker_counts={"a": 2, "b": 2},
    )

    assert metrics.flip_rate == pytest.approx(0.5)
    assert metrics.consensus_rate == 1.0


def test_speaker_share_is_normalized() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[response("A", "a"), response("A", "b")],
        final_answer="A",
        speaker_counts={"a": 3, "b": 1},
    )

    assert metrics.speaker_share == {"a": 0.75, "b": 0.25}
