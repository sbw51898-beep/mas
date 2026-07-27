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
    probabilities: dict[str, float] | None = None,
) -> AgentResponse:
    selected_probabilities = probabilities or {
        option: (0.7 if option == answer else 0.1)
        for option in QUESTION.options
    }
    return AgentResponse(
        response_id=f"{agent_id}-{round_index}",
        agent_id=agent_id,
        round_index=round_index,
        answer=answer,
        probabilities=selected_probabilities,
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
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )

    assert metrics.accuracy == 0.0
    assert metrics.wrong_consensus is True
    assert metrics.majority_share == 1.0
    assert metrics.unanimity is True
    assert metrics.pairwise_disagreement == 0.0


def test_three_agents_can_reach_unit_answer_entropy() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[
            response("A", "a"),
            response("B", "b"),
            response("C", "c"),
        ],
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )

    assert metrics.answer_entropy == pytest.approx(1.0)
    assert metrics.majority_share == pytest.approx(1 / 3)
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
        speaker_counts={"a": 2, "b": 2},
    )

    assert metrics.flip_rate == pytest.approx(0.5)
    assert metrics.majority_share == 1.0


def test_speaker_share_is_normalized() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[response("A", "a"), response("A", "b")],
        speaker_counts={"a": 3, "b": 1},
    )

    assert metrics.speaker_share == {"a": 0.75, "b": 0.25}


def test_metrics_use_pooled_probabilities_for_primary_answer() -> None:
    metrics = calculate_metrics(
        question=QUESTION,
        responses=[
            response(
                "B",
                "a",
                probabilities={"A": 0.35, "B": 0.4, "C": 0.15, "D": 0.1},
            ),
            response(
                "B",
                "b",
                probabilities={"A": 0.35, "B": 0.4, "C": 0.15, "D": 0.1},
            ),
            response(
                "A",
                "c",
                probabilities={"A": 0.95, "B": 0.02, "C": 0.02, "D": 0.01},
            ),
        ],
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )

    assert metrics.majority_answer == "B"
    assert metrics.pooled_answer == "A"
    assert metrics.accuracy == 1.0
    assert metrics.group_brier >= 0.0
    assert metrics.runtime_belief_state.reference_option == "A"
    assert metrics.evaluation_belief_state.reference_option == "A"
