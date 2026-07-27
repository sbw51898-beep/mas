from __future__ import annotations

import asyncio
import platform
from collections import Counter
from collections.abc import Sequence
from uuid import uuid4

from mas_experiment import __version__
from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    ExperimentResult,
    Message,
    ModelProvider,
    Question,
    SelectionScore,
)
from mas_experiment.metrics import calculate_metrics
from mas_experiment.selectors import score_candidates
from mas_experiment.voting import NoValidAnswerError, majority_vote


def _prompt_for(question: Question, visible_messages: Sequence[Message]) -> str:
    options = "\n".join(
        f"{label}. {text}" for label, text in question.options.items()
    )
    history = "\n".join(
        f"{message.speaker}: {message.content}" for message in visible_messages
    )
    history_section = history if history else "(no prior public messages)"
    return (
        f"Public task context:\n{question.public_context or '(none)'}\n\n"
        f"Question: {question.prompt}\n{options}\n\n"
        f"Public discussion:\n{history_section}\n\n"
        "Return JSON with answer, probabilities for every option summing "
        "to 1, and concise reasoning."
    )


def _with_change_flag(
    response: AgentResponse,
    previous: AgentResponse | None,
) -> AgentResponse:
    changed = previous is not None and previous.answer != response.answer
    return response.model_copy(update={"changed_from_previous": changed})


def _message_for(
    *,
    mode: str,
    index: int,
    response: AgentResponse,
    visible_messages: Sequence[Message],
    user_prompt: str,
) -> Message:
    return Message(
        message_id=f"m-{mode}-{index}-{response.response_id}",
        speaker=response.agent_id,
        round_index=response.round_index,
        content=response.raw_text,
        visible_history_ids=tuple(
            message.message_id for message in visible_messages
        ),
        user_prompt=user_prompt,
    )


def _latest_by_agent(
    responses: Sequence[AgentResponse],
) -> dict[str, AgentResponse]:
    latest: dict[str, AgentResponse] = {}
    for response in responses:
        latest[response.agent_id] = response
    return latest


def _build_result(
    *,
    question: Question,
    mode: str,
    roles: tuple[AgentRole, ...],
    messages: Sequence[Message],
    responses: Sequence[AgentResponse],
    selection_scores: Sequence[SelectionScore],
    seed: int,
    errors: Sequence[str],
) -> ExperimentResult:
    latest = tuple(_latest_by_agent(responses).values())
    final_answer: str | None = None
    tie_break = False
    result_errors = list(errors)
    try:
        vote = majority_vote(question, latest)
        final_answer = vote.answer
        tie_break = vote.tie_break
    except NoValidAnswerError as error:
        result_errors.append(str(error))

    speaker_counts = Counter(message.speaker for message in messages)
    metrics = (
        calculate_metrics(
            question=question,
            responses=tuple(responses),
            final_answer=final_answer,
            speaker_counts={
                role.agent_id: speaker_counts.get(role.agent_id, 0)
                for role in roles
            },
        )
        if responses
        else None
    )
    return ExperimentResult(
        run_id=str(uuid4()),
        mode=mode,
        seed=seed,
        question=question,
        roles=roles,
        messages=tuple(messages),
        responses=tuple(responses),
        selection_scores=tuple(selection_scores),
        final_answer=final_answer,
        tie_break=tie_break,
        metrics=metrics,
        errors=tuple(result_errors),
        metadata={
            "project_version": __version__,
            "python_version": platform.python_version(),
            "engine": "framework-independent-core",
            "single_round_baseline": mode == "concurrent",
        },
    )


async def run_concurrent(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
) -> ExperimentResult:
    visible_messages: tuple[Message, ...] = ()
    calls = [
        provider.generate(
            question=question,
            role=role,
            round_index=0,
            visible_messages=visible_messages,
            seed=seed,
        )
        for role in roles
    ]
    outcomes = await asyncio.gather(*calls, return_exceptions=True)
    responses: list[AgentResponse] = []
    messages: list[Message] = []
    errors: list[str] = []
    for role, outcome in zip(roles, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            errors.append(f"{role.agent_id}: {type(outcome).__name__}: {outcome}")
            continue
        responses.append(outcome)
        prompt = _prompt_for(question, visible_messages)
        messages.append(
            _message_for(
                mode="concurrent",
                index=len(messages),
                response=outcome,
                visible_messages=visible_messages,
                user_prompt=prompt,
            )
        )
    return _build_result(
        question=question,
        mode="concurrent",
        roles=roles,
        messages=messages,
        responses=responses,
        selection_scores=(),
        seed=seed,
        errors=errors,
    )


async def run_round_robin(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    rounds: int,
    seed: int,
) -> ExperimentResult:
    messages: list[Message] = []
    responses: list[AgentResponse] = []
    latest: dict[str, AgentResponse] = {}
    errors: list[str] = []
    for round_index in range(rounds):
        for role in roles:
            visible = tuple(messages)
            prompt = _prompt_for(question, visible)
            try:
                response = await provider.generate(
                    question=question,
                    role=role,
                    round_index=round_index,
                    visible_messages=visible,
                    seed=seed,
                )
            except Exception as error:  # noqa: BLE001 - experiment logs failures
                errors.append(
                    f"{role.agent_id}: {type(error).__name__}: {error}"
                )
                continue
            response = _with_change_flag(response, latest.get(role.agent_id))
            latest[role.agent_id] = response
            responses.append(response)
            messages.append(
                _message_for(
                    mode="round_robin",
                    index=len(messages),
                    response=response,
                    visible_messages=visible,
                    user_prompt=prompt,
                )
            )
    return _build_result(
        question=question,
        mode="round_robin",
        roles=roles,
        messages=messages,
        responses=responses,
        selection_scores=(),
        seed=seed,
        errors=errors,
    )


async def run_dynamic(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    turns: int,
    seed: int,
) -> ExperimentResult:
    roles_by_id = {role.agent_id: role for role in roles}
    agent_ids = tuple(roles_by_id)
    messages: list[Message] = []
    responses: list[AgentResponse] = []
    latest: dict[str, AgentResponse] = {}
    last_spoken_steps: dict[str, int] = {}
    selection_history: list[SelectionScore] = []
    errors: list[str] = []

    for step in range(turns):
        scores = score_candidates(
            agent_ids=agent_ids,
            latest_responses=latest,
            last_spoken_steps=last_spoken_steps,
            current_step=step,
        )
        selected_agent = scores[0].agent_id
        selection_history.extend(
            score.model_copy(
                update={"selected": score.agent_id == selected_agent}
            )
            for score in scores
        )
        last_spoken_steps[selected_agent] = step
        role = roles_by_id[selected_agent]
        visible = tuple(messages)
        prompt = _prompt_for(question, visible)
        round_index = sum(
            response.agent_id == selected_agent for response in responses
        )
        try:
            response = await provider.generate(
                question=question,
                role=role,
                round_index=round_index,
                visible_messages=visible,
                seed=seed,
            )
        except Exception as error:  # noqa: BLE001 - experiment logs failures
            errors.append(
                f"{selected_agent}: {type(error).__name__}: {error}"
            )
            continue
        response = _with_change_flag(response, latest.get(selected_agent))
        latest[selected_agent] = response
        responses.append(response)
        messages.append(
            _message_for(
                mode="dynamic",
                index=len(messages),
                response=response,
                visible_messages=visible,
                user_prompt=prompt,
            )
        )

    return _build_result(
        question=question,
        mode="dynamic",
        roles=roles,
        messages=messages,
        responses=responses,
        selection_scores=selection_history,
        seed=seed,
        errors=errors,
    )
