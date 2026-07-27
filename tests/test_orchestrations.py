from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS
from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    ExperimentResult,
    Message,
    Question,
)
from mas_experiment.orchestrations import (
    run_concurrent,
    run_dynamic,
    run_round_robin,
)
from mas_experiment.providers import DeterministicProvider


class RecordingProvider:
    def __init__(self) -> None:
        self.visible_histories: list[tuple[str, ...]] = []

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
        answer = question.options.keys().__iter__().__next__()
        payload = {
            "answer": answer,
            "confidence": 0.8,
            "reasoning": f"{role.agent_id} response",
        }
        return AgentResponse(
            response_id=f"{role.agent_id}-{round_index}-{len(visible_ids)}",
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            confidence=0.8,
            reasoning=payload["reasoning"],
            raw_text=json.dumps(payload),
            changed_from_previous=False,
            timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_concurrent_agents_see_no_peer_messages() -> None:
    provider = RecordingProvider()

    result = await run_concurrent(
        QUESTIONS[0], AGENT_ROLES, provider, seed=20260727
    )

    assert isinstance(result, ExperimentResult)
    assert provider.visible_histories == [(), (), ()]
    assert all(message.visible_history_ids == () for message in result.messages)
    assert len(result.responses) == 3


@pytest.mark.asyncio
async def test_round_robin_visibility_grows_after_each_turn() -> None:
    provider = RecordingProvider()

    result = await run_round_robin(
        QUESTIONS[0], AGENT_ROLES, provider, rounds=1, seed=20260727
    )

    assert [len(ids) for ids in provider.visible_histories] == [0, 1, 2]
    assert [len(message.visible_history_ids) for message in result.messages] == [
        0,
        1,
        2,
    ]


@pytest.mark.asyncio
async def test_dynamic_records_all_scores_and_one_selection_per_turn() -> None:
    result = await run_dynamic(
        QUESTIONS[0],
        AGENT_ROLES,
        DeterministicProvider(),
        turns=9,
        seed=20260727,
    )

    assert len(result.messages) == 9
    assert len(result.selection_scores) == 27
    for step in range(9):
        step_scores = [
            score for score in result.selection_scores if score.step == step
        ]
        assert len(step_scores) == 3
        assert sum(score.selected for score in step_scores) == 1


@pytest.mark.asyncio
async def test_offline_trajectory_is_reproducible_for_same_seed() -> None:
    provider = DeterministicProvider()

    first = await run_dynamic(
        QUESTIONS[0], AGENT_ROLES, provider, turns=4, seed=7
    )
    second = await run_dynamic(
        QUESTIONS[0], AGENT_ROLES, provider, turns=4, seed=7
    )

    assert first.messages == second.messages
    assert first.responses == second.responses
    assert first.selection_scores == second.selection_scores
    assert first.final_answer == second.final_answer
    assert first.metrics == second.metrics
