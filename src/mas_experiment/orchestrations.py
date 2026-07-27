from __future__ import annotations

import asyncio
import hashlib
import platform
import random
from collections import Counter
from collections.abc import Sequence
from uuid import uuid4

from mas_experiment import __version__
from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    ExperimentResult,
    InitialState,
    Message,
    ModelProvider,
    Question,
    SelectionScore,
)
from mas_experiment.metrics import calculate_metrics
from mas_experiment.selectors import score_candidates
from mas_experiment.voting import NoValidAnswerError, majority_vote


class InitialStateValidationError(ValueError):
    """Raised when a shared initial snapshot cannot seed a run."""


def _prompt_for(
    question: Question,
    role: AgentRole,
    visible_messages: Sequence[Message],
) -> str:
    options = "\n".join(
        f"{label}. {text}" for label, text in question.options.items()
    )
    history = "\n".join(
        f"{message.speaker}: {message.content}" for message in visible_messages
    )
    history_section = history if history else "(no prior public messages)"
    return (
        f"Public task context:\n{question.public_context or '(none)'}\n\n"
        f"Your private information:\n"
        f"{question.private_context_for(role.agent_id) or '(none)'}\n\n"
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
    public_messages: Sequence[Message],
    responses: Sequence[AgentResponse],
    selection_scores: Sequence[SelectionScore],
    initial_state: InitialState,
    shared_initial_state: bool,
    seed: int,
    errors: Sequence[str],
) -> ExperimentResult:
    shared_initialization_api_requests = sum(
        int(
            response.provider_metadata.get("api_requests", 0)
            or 0
        )
        for response in initial_state.responses
    )
    follow_up_responses = responses[len(initial_state.responses):]
    mode_follow_up_api_requests = sum(
        int(
            response.provider_metadata.get("api_requests", 0)
            or 0
        )
        for response in follow_up_responses
    )
    shared_initialization_repair_requests = sum(
        int(
            response.provider_metadata.get("repair_requests", 0)
            or 0
        )
        for response in initial_state.responses
    )
    mode_follow_up_repair_requests = sum(
        int(
            response.provider_metadata.get("repair_requests", 0)
            or 0
        )
        for response in follow_up_responses
    )
    if not shared_initialization_api_requests:
        shared_initialization_api_requests = len(
            initial_state.responses
        )
    if not mode_follow_up_api_requests:
        mode_follow_up_api_requests = len(follow_up_responses)

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
            speaker_counts={
                role.agent_id: speaker_counts.get(role.agent_id, 0)
                for role in roles
            },
            messages=tuple(public_messages),
            initial_message_count=0,
        )
        if responses
        else None
    )
    if metrics is not None:
        final_answer = metrics.pooled_answer
        tie_break = metrics.pooled_tie_break
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
            "equal_budget_calls": 9,
            "shared_initialization_api_requests": (
                shared_initialization_api_requests
            ),
            "mode_follow_up_api_requests": (
                mode_follow_up_api_requests
            ),
            "shared_initialization_repair_requests": (
                shared_initialization_repair_requests
            ),
            "mode_follow_up_repair_requests": (
                mode_follow_up_repair_requests
            ),
            "initial_state_id": initial_state.initial_state_id,
            "shared_initial_state": shared_initial_state,
            "logical_response_count": len(responses),
        },
    )


def _initial_state_id(
    question: Question,
    roles: tuple[AgentRole, ...],
    responses: Sequence[AgentResponse],
) -> str:
    identity = "|".join(
        (
            question.question_id,
            *(role.agent_id for role in roles),
            *(response.response_id for response in responses),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


async def prepare_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
) -> InitialState:
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
        prompt = _prompt_for(question, role, visible_messages)
        messages.append(
            _message_for(
                mode="initial",
                index=len(messages),
                response=outcome,
                visible_messages=visible_messages,
                user_prompt=prompt,
            )
        )
    return InitialState(
        initial_state_id=_initial_state_id(question, roles, responses),
        question_id=question.question_id,
        agent_ids=tuple(role.agent_id for role in roles),
        messages=tuple(messages),
        responses=tuple(responses),
        errors=tuple(errors),
    )


def validate_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    state: InitialState,
) -> None:
    role_ids = tuple(role.agent_id for role in roles)
    if state.question_id != question.question_id:
        raise InitialStateValidationError(
            "initial state question does not match"
        )
    if state.agent_ids != role_ids:
        raise InitialStateValidationError(
            "initial state agent order does not match"
        )
    if state.errors:
        raise InitialStateValidationError(
            "initial state contains initialization errors: "
            + "; ".join(state.errors)
        )
    if len(state.responses) != len(roles):
        raise InitialStateValidationError(
            "initial state must contain exactly one response per agent"
        )
    if len(state.messages) != len(roles):
        raise InitialStateValidationError(
            "initial state must contain exactly one message per agent"
        )
    response_ids = tuple(
        response.agent_id for response in state.responses
    )
    message_ids = tuple(message.speaker for message in state.messages)
    if response_ids != role_ids or message_ids != role_ids:
        raise InitialStateValidationError(
            "initial state response and message agents do not match"
        )
    if any(response.round_index != 0 for response in state.responses):
        raise InitialStateValidationError(
            "initial responses must use round_index 0"
        )
    if any(message.round_index != 0 for message in state.messages):
        raise InitialStateValidationError(
            "initial messages must use round_index 0"
        )
    if any(message.visible_history_ids for message in state.messages):
        raise InitialStateValidationError(
            "initial messages must have empty visible history"
        )
    option_ids = set(question.options)
    if any(
        set(response.probabilities) != option_ids
        for response in state.responses
    ):
        raise InitialStateValidationError(
            "initial response probability options do not match question"
        )


async def _resolve_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None,
) -> tuple[list[Message], list[AgentResponse], InitialState, bool]:
    shared = initial_state is not None
    state = initial_state or await prepare_initial_state(
        question,
        roles,
        provider,
        seed=seed,
    )
    validate_initial_state(question, roles, state)
    return (
        list(state.messages),
        list(state.responses),
        state,
        shared,
    )


async def run_independent(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
    messages, responses, resolved_initial_state, shared = (
        await _resolve_initial_state(
            question,
            roles,
            provider,
            seed=seed,
            initial_state=initial_state,
        )
    )
    errors = list(resolved_initial_state.errors)
    latest = _latest_by_agent(responses)
    self_histories = {
        role.agent_id: [
            message
            for message in messages
            if message.speaker == role.agent_id
        ]
        for role in roles
    }

    for round_index in (1, 2):
        calls = [
            provider.generate(
                question=question,
                role=role,
                round_index=round_index,
                visible_messages=tuple(self_histories[role.agent_id]),
                seed=seed,
            )
            for role in roles
        ]
        outcomes = await asyncio.gather(*calls, return_exceptions=True)
        for role, outcome in zip(roles, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                errors.append(
                    f"{role.agent_id}: {type(outcome).__name__}: {outcome}"
                )
                continue
            response = _with_change_flag(
                outcome,
                latest.get(role.agent_id),
            )
            latest[role.agent_id] = response
            visible = tuple(self_histories[role.agent_id])
            message = _message_for(
                mode="independent",
                index=len(messages),
                response=response,
                visible_messages=visible,
                user_prompt=_prompt_for(question, role, visible),
            )
            responses.append(response)
            messages.append(message)
            self_histories[role.agent_id].append(message)

    return _build_result(
        question=question,
        mode="independent",
        roles=roles,
        messages=messages,
        public_messages=(),
        responses=responses,
        selection_scores=(),
        initial_state=resolved_initial_state,
        shared_initial_state=shared,
        seed=seed,
        errors=errors,
    )


async def run_concurrent(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
    """Compatibility alias for the equal-budget independent baseline."""
    return await run_independent(
        question,
        roles,
        provider,
        seed=seed,
        initial_state=initial_state,
    )


async def run_round_robin(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
    messages, responses, resolved_initial_state, shared = (
        await _resolve_initial_state(
            question,
            roles,
            provider,
            seed=seed,
            initial_state=initial_state,
        )
    )
    errors = list(resolved_initial_state.errors)
    latest = _latest_by_agent(responses)
    public_messages: list[Message] = []
    for round_index in (1, 2):
        for role in roles:
            visible = tuple(public_messages)
            prompt = _prompt_for(question, role, visible)
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
            message = _message_for(
                mode="round_robin",
                index=len(messages),
                response=response,
                visible_messages=visible,
                user_prompt=prompt,
            )
            messages.append(message)
            public_messages.append(message)
    return _build_result(
        question=question,
        mode="round_robin",
        roles=roles,
        messages=messages,
        public_messages=public_messages,
        responses=responses,
        selection_scores=(),
        initial_state=resolved_initial_state,
        shared_initial_state=shared,
        seed=seed,
        errors=errors,
    )


async def run_random_order(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
    messages, responses, resolved_initial_state, shared = (
        await _resolve_initial_state(
            question,
            roles,
            provider,
            seed=seed,
            initial_state=initial_state,
        )
    )
    errors = list(resolved_initial_state.errors)
    latest = _latest_by_agent(responses)
    public_messages: list[Message] = []
    roles_by_id = {role.agent_id: role for role in roles}
    schedule = [role.agent_id for role in roles] * 2
    random.Random(seed).shuffle(schedule)

    for selected_agent in schedule:
        role = roles_by_id[selected_agent]
        visible = tuple(public_messages)
        prompt = _prompt_for(question, role, visible)
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
        message = _message_for(
            mode="random_order",
            index=len(messages),
            response=response,
            visible_messages=visible,
            user_prompt=prompt,
        )
        messages.append(message)
        public_messages.append(message)

    return _build_result(
        question=question,
        mode="random_order",
        roles=roles,
        messages=messages,
        public_messages=public_messages,
        responses=responses,
        selection_scores=(),
        initial_state=resolved_initial_state,
        shared_initial_state=shared,
        seed=seed,
        errors=errors,
    )


async def run_dynamic(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
    roles_by_id = {role.agent_id: role for role in roles}
    agent_ids = tuple(roles_by_id)
    messages, responses, resolved_initial_state, shared = (
        await _resolve_initial_state(
            question,
            roles,
            provider,
            seed=seed,
            initial_state=initial_state,
        )
    )
    errors = list(resolved_initial_state.errors)
    latest = _latest_by_agent(responses)
    public_messages: list[Message] = []
    last_spoken_steps: dict[str, int] = {}
    selection_history: list[SelectionScore] = []

    for step in range(6):
        scores = score_candidates(
            agent_ids=agent_ids,
            latest_responses=latest,
            last_spoken_steps=last_spoken_steps,
            current_step=step,
            question=question,
            public_messages=tuple(public_messages),
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
        visible = tuple(public_messages)
        prompt = _prompt_for(question, role, visible)
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
        message = _message_for(
            mode="dynamic",
            index=len(messages),
            response=response,
            visible_messages=visible,
            user_prompt=prompt,
        )
        messages.append(message)
        public_messages.append(message)

    return _build_result(
        question=question,
        mode="dynamic",
        roles=roles,
        messages=messages,
        public_messages=public_messages,
        responses=responses,
        selection_scores=selection_history,
        initial_state=resolved_initial_state,
        shared_initial_state=shared,
        seed=seed,
        errors=errors,
    )
