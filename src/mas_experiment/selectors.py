from __future__ import annotations

from collections import Counter

from mas_experiment.domain import AgentResponse, SelectionScore


def _majority_answer(
    latest_responses: dict[str, AgentResponse],
) -> str | None:
    if not latest_responses:
        return None
    counts = Counter(response.answer for response in latest_responses.values())
    highest = max(counts.values())
    return min(answer for answer, count in counts.items() if count == highest)


def score_candidates(
    *,
    agent_ids: tuple[str, ...],
    latest_responses: dict[str, AgentResponse],
    last_spoken_steps: dict[str, int],
    current_step: int,
) -> tuple[SelectionScore, ...]:
    majority = _majority_answer(latest_responses)
    waits = {
        agent_id: max(0, current_step - last_spoken_steps[agent_id])
        for agent_id in agent_ids
        if agent_id in last_spoken_steps
    }
    maximum_wait = max(waits.values(), default=1)
    maximum_wait = max(maximum_wait, 1)

    scores: list[SelectionScore] = []
    for agent_id in agent_ids:
        previous = latest_responses.get(agent_id)
        if previous is None:
            disagreement = 1.0
            uncertainty = 1.0
        else:
            disagreement = float(
                majority is None or previous.answer != majority
            )
            uncertainty = 1.0 - previous.confidence

        waiting = (
            1.0
            if agent_id not in last_spoken_steps
            else waits[agent_id] / maximum_wait
        )
        total = (
            0.45 * disagreement
            + 0.30 * waiting
            + 0.25 * uncertainty
        )
        scores.append(
            SelectionScore(
                step=current_step,
                agent_id=agent_id,
                disagreement=disagreement,
                waiting=waiting,
                uncertainty=uncertainty,
                total=total,
            )
        )

    return tuple(sorted(scores, key=lambda score: (-score.total, score.agent_id)))


def select_next_speaker(
    *,
    agent_ids: tuple[str, ...],
    latest_responses: dict[str, AgentResponse],
    last_spoken_steps: dict[str, int],
    current_step: int,
) -> SelectionScore:
    scores = score_candidates(
        agent_ids=agent_ids,
        latest_responses=latest_responses,
        last_spoken_steps=last_spoken_steps,
        current_step=current_step,
    )
    if not scores:
        raise ValueError("at least one candidate agent is required")
    return scores[0].model_copy(update={"selected": True})
