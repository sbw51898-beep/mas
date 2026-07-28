from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from mas_experiment.datasets import (
    AGENT_ROLES,
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    QUESTIONS,
)
from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    ExperimentResult,
    InitialState,
    Message,
    Question,
)
from mas_experiment.orchestrations import (
    InitialStateValidationError,
    prepare_initial_state,
    run_dynamic,
    run_independent,
    run_random_order,
    run_round_robin,
    validate_initial_state,
)
from mas_experiment.providers import DeterministicProvider


class RecordingProvider:
    def __init__(self, *, fail_agent_id: str | None = None) -> None:
        self.fail_agent_id = fail_agent_id
        self.visible_histories: list[tuple[str, ...]] = []
        self.calls: list[tuple[str, tuple[Message, ...]]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        visible_ids = tuple(message.message_id for message in visible_messages)
        self.visible_histories.append(visible_ids)
        self.calls.append((role.agent_id, visible_messages))
        if role.agent_id == self.fail_agent_id:
            raise RuntimeError("initial failure")
        answer = question.options.keys().__iter__().__next__()
        payload = {
            "answer": answer,
            "probabilities": {
                option: (0.7 if option == answer else 0.1)
                for option in question.options
            },
            "reasoning": f"{role.agent_id} response",
        }
        return AgentResponse(
            response_id=f"{role.agent_id}-{round_index}-{len(visible_ids)}",
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            probabilities=payload["probabilities"],
            reasoning=payload["reasoning"],
            raw_text=json.dumps(payload),
            changed_from_previous=False,
            timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_prepare_initial_state_makes_three_mutually_invisible_calls() -> None:
    provider = RecordingProvider()

    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert provider.call_count == 3
    assert provider.visible_histories == [(), (), ()]
    assert state.question_id == FORMAL_PILOT_QUESTION.question_id
    assert state.agent_ids == tuple(
        role.agent_id for role in FORMAL_PILOT_ROLES
    )
    assert len(state.messages) == 3
    assert len(state.responses) == 3
    assert state.errors == ()


@pytest.mark.asyncio
async def test_prepare_initial_state_preserves_failures_for_validation() -> None:
    provider = RecordingProvider(fail_agent_id="agent-b")

    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert len(state.responses) == 2
    assert state.errors == (
        "agent-b: RuntimeError: initial failure",
    )


def test_validate_initial_state_rejects_a_different_question() -> None:
    state = InitialState(
        initial_state_id="shared-1",
        question_id="other-question",
        agent_ids=tuple(role.agent_id for role in FORMAL_PILOT_ROLES),
        messages=(),
        responses=(),
    )

    with pytest.raises(
        InitialStateValidationError,
        match="question",
    ):
        validate_initial_state(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            state,
        )


@pytest.mark.asyncio
async def test_validate_initial_state_rejects_an_incomplete_snapshot() -> None:
    provider = RecordingProvider(fail_agent_id="agent-b")
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    with pytest.raises(
        InitialStateValidationError,
        match="initialization errors",
    ):
        validate_initial_state(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            state,
        )


@pytest.mark.asyncio
async def test_validate_initial_state_rejects_incomplete_probabilities() -> None:
    provider = RecordingProvider()
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )
    first = state.responses[0]
    invalid_response = AgentResponse(
        response_id=first.response_id,
        agent_id=first.agent_id,
        round_index=0,
        answer="A",
        probabilities={"A": 0.8, "B": 0.1, "C": 0.1},
        reasoning=first.reasoning,
        raw_text=first.raw_text,
        changed_from_previous=False,
        timestamp=first.timestamp,
    )
    invalid_state = state.model_copy(
        update={
            "responses": (invalid_response, *state.responses[1:]),
        }
    )

    with pytest.raises(
        InitialStateValidationError,
        match="probability options",
    ):
        validate_initial_state(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            invalid_state,
        )


@pytest.mark.asyncio
async def test_three_modes_reuse_one_initial_state_without_provider_calls() -> None:
    preparation_provider = RecordingProvider()
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        preparation_provider,
        seed=20260727,
    )
    mode_provider = RecordingProvider()

    results = [
        await runner(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            mode_provider,
            seed=20260727,
            initial_state=state,
        )
        for runner in (run_independent, run_round_robin, run_dynamic)
    ]

    assert preparation_provider.call_count == 3
    assert mode_provider.call_count == 18
    assert all(len(result.responses) == 9 for result in results)
    assert all(
        result.responses[:3] == state.responses
        for result in results
    )
    assert all(
        result.metadata["initial_state_id"]
        == state.initial_state_id
        for result in results
    )
    assert all(
        result.metadata["shared_initial_state"] is True
        for result in results
    )


@pytest.mark.asyncio
async def test_runner_reuse_does_not_mutate_initial_state() -> None:
    provider = RecordingProvider()
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )
    original = state.model_dump(mode="json")

    await run_round_robin(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
        initial_state=state,
    )

    assert state.model_dump(mode="json") == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runner",
    [run_independent, run_round_robin, run_random_order, run_dynamic],
)
async def test_every_mode_uses_exactly_nine_discussion_calls(runner) -> None:
    provider = RecordingProvider()

    result = await runner(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert isinstance(result, ExperimentResult)
    assert provider.call_count == 9
    assert len(result.responses) == 9


@pytest.mark.asyncio
async def test_initial_three_calls_are_mutually_invisible() -> None:
    provider = RecordingProvider()

    await run_dynamic(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert provider.visible_histories[:3] == [(), (), ()]


@pytest.mark.asyncio
async def test_independent_mode_sees_only_same_agent_history() -> None:
    provider = RecordingProvider()

    await run_independent(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    for agent_id, visible_messages in provider.calls[3:]:
        assert visible_messages
        assert all(
            message.speaker == agent_id
            for message in visible_messages
        )


@pytest.mark.asyncio
async def test_independent_private_reflections_do_not_count_as_public_exposure() -> None:
    question = FORMAL_PILOT_QUESTION.model_copy(
        update={
            "information_keywords": {
                role.agent_id: (f"{role.agent_id} response",)
                for role in FORMAL_PILOT_ROLES
            }
        }
    )

    result = await run_independent(
        question,
        FORMAL_PILOT_ROLES,
        RecordingProvider(),
        seed=20260727,
    )

    assert result.metrics is not None
    assert result.metrics.information_coverage == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_round_robin_visibility_grows_after_each_turn() -> None:
    provider = RecordingProvider()

    result = await run_round_robin(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert [len(ids) for ids in provider.visible_histories] == [
        0, 0, 0, 0, 1, 2, 3, 4, 5
    ]
    assert [len(message.visible_history_ids) for message in result.messages] == [
        0, 0, 0, 0, 1, 2, 3, 4, 5
    ]


@pytest.mark.asyncio
async def test_random_order_is_seeded_and_gives_every_agent_two_turns() -> None:
    result = await run_random_order(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        RecordingProvider(),
        seed=17,
    )

    assert [message.speaker for message in result.messages[3:]] == [
        "agent-a",
        "agent-c",
        "agent-b",
        "agent-c",
        "agent-a",
        "agent-b",
    ]


@pytest.mark.asyncio
async def test_dynamic_records_all_scores_and_one_selection_per_turn() -> None:
    result = await run_dynamic(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        DeterministicProvider(),
        seed=20260727,
    )

    assert len(result.messages) == 9
    assert len(result.selection_scores) == 18
    steps = sorted({score.step for score in result.selection_scores})
    assert len(steps) == 6
    for step in steps:
        step_scores = [
            score for score in result.selection_scores if score.step == step
        ]
        assert len(step_scores) == 3
        assert sum(score.selected for score in step_scores) == 1


@pytest.mark.asyncio
async def test_offline_trajectory_is_reproducible_for_same_seed() -> None:
    provider = DeterministicProvider()

    first = await run_dynamic(
        QUESTIONS[0], AGENT_ROLES, provider, seed=7
    )
    second = await run_dynamic(
        QUESTIONS[0], AGENT_ROLES, provider, seed=7
    )

    assert first.messages == second.messages
    assert first.responses == second.responses
    assert first.selection_scores == second.selection_scores
    assert first.final_answer == second.final_answer
    assert first.metrics == second.metrics
