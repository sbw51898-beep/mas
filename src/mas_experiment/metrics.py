from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from math import log

from mas_experiment.domain import AgentResponse, ExperimentMetrics, Question


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
    return entropy / log(option_count)


def calculate_metrics(
    *,
    question: Question,
    responses: list[AgentResponse] | tuple[AgentResponse, ...],
    final_answer: str | None,
    speaker_counts: dict[str, int],
) -> ExperimentMetrics:
    latest = _latest_valid_responses(question, responses)
    final_answers = [response.answer for response in latest.values()]
    answer_counts = Counter(final_answers)
    valid_count = len(final_answers)
    consensus_rate = (
        max(answer_counts.values()) / valid_count if valid_count else 0.0
    )
    unanimous = bool(final_answers) and len(answer_counts) == 1
    total_speeches = sum(speaker_counts.values())
    speaker_share = {
        agent_id: count / total_speeches if total_speeches else 0.0
        for agent_id, count in speaker_counts.items()
    }

    return ExperimentMetrics(
        accuracy=float(final_answer == question.correct_answer),
        consensus_rate=consensus_rate,
        wrong_consensus=unanimous and final_answer != question.correct_answer,
        flip_rate=_flip_rate(responses),
        pairwise_disagreement=_pairwise_disagreement(final_answers),
        answer_entropy=_normalized_entropy(final_answers, len(question.options)),
        speaker_share=speaker_share,
    )
