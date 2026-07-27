from __future__ import annotations

from mas_experiment.beliefs import js_divergence, pool_probabilities
from mas_experiment.domain import (
    AgentResponse,
    Message,
    Question,
    SelectionScore,
)
from mas_experiment.information import (
    contains_any_keyword,
    keyword_present,
)


def score_candidates(
    *,
    agent_ids: tuple[str, ...],
    latest_responses: dict[str, AgentResponse],
    last_spoken_steps: dict[str, int],
    current_step: int,
    question: Question | None = None,
    public_messages: tuple[Message, ...] = (),
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

        information_keywords = (
            question.information_keywords.get(agent_id, ())
            if question is not None
            else ()
        )
        information_exposure = (
            sum(
                not any(
                    message.speaker == agent_id
                    and keyword_present(message.content, keyword)
                    for message in public_messages
                )
                for keyword in information_keywords
            )
            / len(information_keywords)
            if information_keywords
            else 0.0
        )
        dependency_keywords = (
            question.dependency_keywords.get(agent_id, ())
            if question is not None
            else ()
        )
        dependency_start = last_spoken_steps.get(agent_id, -1) + 1
        new_public_messages = public_messages[
            max(0, dependency_start):
        ]
        dependency_owners = {
            keyword: {
                owner
                for owner, owned_keywords in (
                    question.information_keywords.items()
                    if question is not None
                    else ()
                )
                if keyword in owned_keywords
            }
            for keyword in dependency_keywords
        }
        dependency_trigger = float(
            any(
                keyword_present(message.content, keyword)
                and (
                    message.speaker in dependency_owners[keyword]
                    if dependency_owners[keyword]
                    else message.speaker != agent_id
                )
                for keyword in dependency_keywords
                for message in new_public_messages
            )
        )

        waiting = (
            1.0
            if agent_id not in last_spoken_steps
            else waits[agent_id] / maximum_wait
        )
        total = (
            1.0
            if previous is None
            else (
                0.30 * disagreement
                + 0.25 * information_exposure
                + 0.20 * dependency_trigger
                + 0.15 * uncertainty
                + 0.10 * waiting
            )
        )
        scores.append(
            SelectionScore(
                step=current_step,
                agent_id=agent_id,
                disagreement=disagreement,
                information_exposure=information_exposure,
                dependency_trigger=dependency_trigger,
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
    question: Question | None = None,
    public_messages: tuple[Message, ...] = (),
) -> SelectionScore:
    scores = score_candidates(
        agent_ids=agent_ids,
        latest_responses=latest_responses,
        last_spoken_steps=last_spoken_steps,
        current_step=current_step,
        question=question,
        public_messages=public_messages,
    )
    if not scores:
        raise ValueError("at least one candidate agent is required")
    return scores[0].model_copy(update={"selected": True})
