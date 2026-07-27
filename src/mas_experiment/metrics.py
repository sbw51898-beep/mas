from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from math import log

from statistics import mean

from mas_experiment.beliefs import (
    belief_state,
    brier_score,
    generalized_js_disagreement,
    pool_probabilities,
)
from mas_experiment.domain import AgentResponse, ExperimentMetrics, Question
from mas_experiment.voting import majority_vote


def _latest_valid_responses(
    question: Question,
    responses: list[AgentResponse] | tuple[AgentResponse, ...],
) -> dict[str, AgentResponse]:
    latest: dict[str, AgentResponse] = {}
    for response in responses:
        if response.answer in question.options:
            latest[response.agent_id] = response
    return latest


def _flip_rate(
    responses: list[AgentResponse] | tuple[AgentResponse, ...],
) -> float:
    trajectories: dict[str, list[str]] = defaultdict(list)
    for response in responses:
        trajectories[response.agent_id].append(response.answer)

    comparable = 0
    changed = 0
    for answers in trajectories.values():
        for previous, current in zip(answers, answers[1:], strict=False):
            comparable += 1
            changed += previous != current
    return changed / comparable if comparable else 0.0


def _pairwise_disagreement(answers: list[str]) -> float:
    pairs = list(combinations(answers, 2))
    if not pairs:
        return 0.0
    return sum(left != right for left, right in pairs) / len(pairs)


def _normalized_entropy(answers: list[str], option_count: int) -> float:
    if not answers or option_count <= 1:
        return 0.0
    counts = Counter(answers)
    total = len(answers)
    entropy = -sum(
        (count / total) * log(count / total) for count in counts.values()
    )
    reachable_states = min(option_count, len(answers))
    return entropy / log(reachable_states) if reachable_states > 1 else 0.0


def calculate_metrics(
    *,
    question: Question,
    responses: list[AgentResponse] | tuple[AgentResponse, ...],
    speaker_counts: dict[str, int],
) -> ExperimentMetrics:
    latest = _latest_valid_responses(question, responses)
    if not latest:
        raise ValueError("metrics require at least one valid response")
    final_answers = [response.answer for response in latest.values()]
    answer_counts = Counter(final_answers)
    valid_count = len(final_answers)
    majority_share = (
        max(answer_counts.values()) / valid_count if valid_count else 0.0
    )
    unanimous = bool(final_answers) and len(answer_counts) == 1
    probabilities_by_agent = {
        agent_id: response.probabilities
        for agent_id, response in latest.items()
    }
    pooled_probabilities, pooled_answer, pooled_tie_break = (
        pool_probabilities(
            probabilities_by_agent,
            tuple(question.options),
        )
    )
    majority_answer = majority_vote(
        question,
        tuple(latest.values()),
    ).answer
    total_speeches = sum(speaker_counts.values())
    speaker_share = {
        agent_id: count / total_speeches if total_speeches else 0.0
        for agent_id, count in speaker_counts.items()
    }

    return ExperimentMetrics(
        accuracy=float(pooled_answer == question.correct_answer),
        majority_share=majority_share,
        unanimity=unanimous,
        wrong_consensus=(
            unanimous and pooled_answer != question.correct_answer
        ),
        flip_rate=_flip_rate(responses),
        pairwise_disagreement=_pairwise_disagreement(final_answers),
        answer_entropy=_normalized_entropy(final_answers, len(question.options)),
        js_disagreement=generalized_js_disagreement(
            probabilities_by_agent
        ),
        group_brier=mean(
            brier_score(
                response.probabilities,
                correct_answer=question.correct_answer,
            )
            for response in latest.values()
        ),
        speaker_share=speaker_share,
        pooled_probabilities=pooled_probabilities,
        pooled_answer=pooled_answer,
        majority_answer=majority_answer,
        pooled_tie_break=pooled_tie_break,
        runtime_belief_state=belief_state(
            probabilities_by_agent,
            reference_option=pooled_answer,
        ),
        evaluation_belief_state=belief_state(
            probabilities_by_agent,
            reference_option=question.correct_answer,
        ),
    )
