from __future__ import annotations

import pytest

from mas_experiment.beliefs import (
    ProbabilityValidationError,
    belief_state,
    brier_score,
    generalized_js_disagreement,
    normalize_probabilities,
    pool_probabilities,
    validate_answer_matches_probabilities,
)
from mas_experiment.domain import Question


QUESTION = Question(
    question_id="q",
    prompt="Choose.",
    options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
    correct_answer="A",
)


def test_probabilities_are_normalized_within_rounding_tolerance() -> None:
    result = normalize_probabilities(
        QUESTION,
        {"A": 0.50, "B": 0.30, "C": 0.19, "D": 0.009},
    )

    assert sum(result.values()) == pytest.approx(1.0)
    assert set(result) == set(QUESTION.options)


def test_probabilities_reject_missing_option() -> None:
    with pytest.raises(ProbabilityValidationError, match="exactly"):
        normalize_probabilities(
            QUESTION,
            {"A": 0.5, "B": 0.3, "C": 0.2},
        )


def test_probabilities_reject_large_sum_error() -> None:
    with pytest.raises(ProbabilityValidationError, match="sum"):
        normalize_probabilities(
            QUESTION,
            {"A": 0.7, "B": 0.3, "C": 0.2, "D": 0.1},
        )


def test_answer_must_match_highest_probability() -> None:
    with pytest.raises(ProbabilityValidationError, match="highest"):
        validate_answer_matches_probabilities(
            QUESTION,
            "A",
            {"A": 0.1, "B": 0.7, "C": 0.1, "D": 0.1},
        )


def test_pool_probabilities_uses_agent_mean() -> None:
    pooled, answer, tie_break = pool_probabilities(
        {
            "a": {"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1},
            "b": {"A": 0.1, "B": 0.7, "C": 0.1, "D": 0.1},
            "c": {"A": 0.2, "B": 0.6, "C": 0.1, "D": 0.1},
        },
        ("A", "B", "C", "D"),
    )

    assert pooled == {
        "A": pytest.approx(1 / 3),
        "B": pytest.approx(1.4 / 3),
        "C": pytest.approx(0.1),
        "D": pytest.approx(0.1),
    }
    assert answer == "B"
    assert tie_break is False


def test_identical_probability_vectors_have_zero_js_disagreement() -> None:
    probabilities = {
        agent: {"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1}
        for agent in ("a", "b", "c")
    }

    assert generalized_js_disagreement(probabilities) == pytest.approx(0.0)


def test_runtime_and_evaluation_beliefs_use_different_references() -> None:
    probabilities = {
        "a": {"A": 0.6, "B": 0.2, "C": 0.1, "D": 0.1},
        "b": {"A": 0.5, "B": 0.2, "C": 0.2, "D": 0.1},
        "c": {"A": 0.4, "B": 0.2, "C": 0.3, "D": 0.1},
    }

    runtime = belief_state(probabilities, reference_option="A")
    evaluation = belief_state(probabilities, reference_option="C")

    assert runtime.reference_option == "A"
    assert evaluation.reference_option == "C"
    assert runtime.mean_b > evaluation.mean_b
    assert 0.0 <= runtime.order_parameter_r <= 1.0
    assert 0.0 <= runtime.temperature_proxy <= 1.0
    assert 0.0 <= runtime.entropy_proxy <= 1.0


def test_brier_score_is_zero_for_certain_correct_prediction() -> None:
    assert brier_score(
        {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0},
        correct_answer="A",
    ) == pytest.approx(0.0)
