from __future__ import annotations

from mas_experiment.beliefs import js_divergence, pool_probabilities
from mas_experiment.domain import AgentResponse, SelectionScore


def score_candidates(
    *,
    agent_ids: tuple[str, ...],
    latest_responses: dict[str, AgentResponse],
    last_spoken_steps: dict[str, int],
    current_step: int,
) -> tuple[SelectionScore, ...]:
    pooled_probabilities: dict[str, float] | None = None
    if latest_responses:
        first = next(iter(latest_responses.values()))
        pooled_probabilities, _, _ = pool_probabilities(
            {
                agent_id: response.probabilities
                for agent_id, response in latest_responses.items()
            },
            tuple(first.probabilities),
        )
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
            disagreement = js_divergence(
                previous.probabilities,
                pooled_probabilities or previous.probabilities,
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
