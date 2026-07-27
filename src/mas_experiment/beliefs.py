from __future__ import annotations

import math
from collections.abc import Mapping

from mas_experiment.domain import Question


class ProbabilityValidationError(ValueError):
    """Raised when a model probability vector violates the experiment contract."""


def normalize_probabilities(
    question: Question,
    values: Mapping[str, float],
    *,
    tolerance: float = 0.01,
) -> dict[str, float]:
    if set(values) != set(question.options):
        raise ProbabilityValidationError(
            "probabilities must contain exactly the question options"
        )
    try:
        parsed = {key: float(values[key]) for key in question.options}
    except (TypeError, ValueError) as error:
        raise ProbabilityValidationError(
            "probabilities must be numeric"
        ) from error
    if any(
        not math.isfinite(value) or value < 0.0 or value > 1.0
        for value in parsed.values()
    ):
        raise ProbabilityValidationError(
            "probabilities must be finite values from 0 to 1"
        )
    total = sum(parsed.values())
    if total <= 0.0 or abs(total - 1.0) > tolerance:
        raise ProbabilityValidationError(
            "probabilities must sum to 1 within tolerance 0.01"
        )
    return {key: value / total for key, value in parsed.items()}


def validate_answer_matches_probabilities(
    question: Question,
    answer: str,
    probabilities: Mapping[str, float],
) -> tuple[str, bool]:
    maximum = max(probabilities.values())
    winners = [
        key
        for key in question.options
        if math.isclose(probabilities[key], maximum, abs_tol=1e-12)
    ]
    expected = winners[0]
    if answer != expected:
        raise ProbabilityValidationError(
            "answer must equal the highest-probability option"
        )
    return expected, len(winners) > 1
