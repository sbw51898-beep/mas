from __future__ import annotations

import pytest

from mas_experiment.beliefs import (
    ProbabilityValidationError,
    normalize_probabilities,
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
