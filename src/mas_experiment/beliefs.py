from __future__ import annotations

import math
from collections.abc import Mapping
from cmath import exp
from statistics import mean, pstdev

from mas_experiment.domain import BeliefState, Question


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


def _entropy(probabilities: Mapping[str, float]) -> float:
    return -sum(
        probability * math.log(probability)
        for probability in probabilities.values()
        if probability > 0.0
    )


def pool_probabilities(
    probabilities_by_agent: Mapping[str, Mapping[str, float]],
    option_order: tuple[str, ...],
) -> tuple[dict[str, float], str, bool]:
    if not probabilities_by_agent:
        raise ValueError("at least one probability vector is required")
    pooled = {
        option: mean(
            probabilities[option]
            for probabilities in probabilities_by_agent.values()
        )
        for option in option_order
    }
    maximum = max(pooled.values())
    winners = [
        option
        for option in option_order
        if math.isclose(pooled[option], maximum, abs_tol=1e-12)
    ]
    return pooled, winners[0], len(winners) > 1


def generalized_js_disagreement(
    probabilities_by_agent: Mapping[str, Mapping[str, float]],
) -> float:
    if len(probabilities_by_agent) <= 1:
        return 0.0
    first = next(iter(probabilities_by_agent.values()))
    option_order = tuple(first)
    pooled, _, _ = pool_probabilities(
        probabilities_by_agent,
        option_order,
    )
    raw = _entropy(pooled) - mean(
        _entropy(probabilities)
        for probabilities in probabilities_by_agent.values()
    )
    denominator = math.log(min(len(option_order), len(probabilities_by_agent)))
    if denominator <= 0.0:
        return 0.0
    return min(1.0, max(0.0, raw / denominator))


def brier_score(
    probabilities: Mapping[str, float],
    *,
    correct_answer: str,
) -> float:
    return sum(
        (
            probability
            - (1.0 if option == correct_answer else 0.0)
        )
        ** 2
        for option, probability in probabilities.items()
    )


def belief_state(
    probabilities_by_agent: Mapping[str, Mapping[str, float]],
    *,
    reference_option: str,
) -> BeliefState:
    if not probabilities_by_agent:
        raise ValueError("at least one probability vector is required")
    beliefs = {
        agent_id: 2.0 * probabilities[reference_option] - 1.0
        for agent_id, probabilities in probabilities_by_agent.items()
    }
    values = list(beliefs.values())
    phases = [math.pi * value / 2.0 for value in values]
    order_parameter = abs(
        sum(exp(1j * phase) for phase in phases) / len(phases)
    )
    temperature = pstdev(values) if len(values) > 1 else 0.0
    bin_counts = [0, 0, 0, 0, 0]
    for value in values:
        index = min(4, max(0, int((value + 1.0) / 0.4)))
        bin_counts[index] += 1
    bin_probabilities = [
        count / len(values)
        for count in bin_counts
        if count
    ]
    raw_entropy = -sum(
        probability * math.log(probability)
        for probability in bin_probabilities
    )
    denominator = math.log(min(5, len(values))) if len(values) > 1 else 0.0
    entropy_proxy = raw_entropy / denominator if denominator else 0.0
    entropy_proxy = min(1.0, max(0.0, entropy_proxy))
    order_parameter = min(1.0, max(0.0, order_parameter))
    temperature = min(1.0, max(0.0, temperature))
    return BeliefState(
        reference_option=reference_option,
        beliefs=beliefs,
        mean_b=mean(values),
        order_parameter_r=order_parameter,
        temperature_proxy=temperature,
        entropy_proxy=entropy_proxy,
        disorder_proxy=(
            (1.0 - order_parameter)
            + temperature * entropy_proxy
        ),
    )
