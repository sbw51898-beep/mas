from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import AGENT_IDS, assign_hidden_information
from mas_experiment.hiddenbench_dynamic_domain import load_dynamic_pilot_config
from mas_experiment.hiddenbench_dynamic_protocol import (
    run_hiddenbench_dynamic_task,
)
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).parents[1]
TASK = load_hiddenbench_task(
    ROOT / "data" / "hiddenbench" / "benchmark.json",
    task_id=1,
    expected_sha256=(
        "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
    ),
)
CONFIG = load_dynamic_pilot_config(
    ROOT / "configs" / "hiddenbench-dynamic-pilot.json"
)
ASSIGNMENT = assign_hidden_information(TASK, seed=CONFIG.base_seed)


def vote_text(vote: str) -> str:
    return json.dumps(
        {"vote": vote, "rationale": f"Evidence favors {vote}."}
    )


def protocol_script() -> tuple[str, ...]:
    return (
        *(vote_text("West City") for _ in range(4)),
        *(
            f"Discussion statement {index:02d} supports West City."
            for index in range(60)
        ),
        *(vote_text("West City") for _ in range(4)),
        *(vote_text("West City") for _ in range(4)),
    )


@pytest.mark.asyncio
async def test_dynamic_protocol_has_72_slots_and_exact_15_each() -> None:
    provider = ScriptedPromptProvider(protocol_script())

    dynamic = await run_hiddenbench_dynamic_task(
        TASK,
        provider,
        seed=CONFIG.base_seed,
        assignment=ASSIGNMENT,
        baseline_run_id="frozen-run",
        config=CONFIG,
    )

    assert len(provider.calls) == 72
    assert len(dynamic.run.discussion_messages) == 60
    assert Counter(
        message.agent_id for message in dynamic.run.discussion_messages
    ) == {agent: 15 for agent in AGENT_IDS}
    assert len(dynamic.selection_events) == 60
    assert dynamic.run.provider_metadata["selector_llm_calls"] == 0


@pytest.mark.asyncio
async def test_dynamic_protocol_preserves_visibility_and_reporting_blocks() -> None:
    dynamic = await run_hiddenbench_dynamic_task(
        TASK,
        ScriptedPromptProvider(protocol_script()),
        seed=CONFIG.base_seed,
        assignment=ASSIGNMENT,
        baseline_run_id="frozen-run",
        config=CONFIG,
    )

    for index, message in enumerate(dynamic.run.discussion_messages):
        assert message.turn_index == index
        assert message.round_index == index // 4 + 1
        assert message.visible_message_ids == tuple(
            previous.message_id
            for previous in dynamic.run.discussion_messages[:index]
        )
        assert dynamic.selection_events[index].selected_agent_id == (
            message.agent_id
        )
    assert all(
        all(
            message.content in vote.user_prompt
            for message in dynamic.run.discussion_messages
        )
        for vote in dynamic.run.hidden_post_votes
    )


@pytest.mark.asyncio
async def test_assignment_mismatch_fails_before_provider_call() -> None:
    provider = ScriptedPromptProvider(protocol_script())
    wrong_assignment = ASSIGNMENT.model_copy(update={"task_id": 999})

    with pytest.raises(ValueError, match="assignment task ID mismatch"):
        await run_hiddenbench_dynamic_task(
            TASK,
            provider,
            seed=CONFIG.base_seed,
            assignment=wrong_assignment,
            baseline_run_id="frozen-run",
            config=CONFIG,
        )

    assert provider.calls == []
