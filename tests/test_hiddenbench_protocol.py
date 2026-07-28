from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import assign_hidden_information
from mas_experiment.hiddenbench_prompts import (
    build_hidden_system_prompt,
    build_vote_user_prompt,
)
from mas_experiment.hiddenbench_protocol import (
    complete_hiddenbench_vote,
    parse_hiddenbench_vote,
    run_hiddenbench_task,
)
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
EXPECTED_SHA = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)
TASK = load_hiddenbench_task(
    DATASET,
    task_id=25,
    expected_sha256=EXPECTED_SHA,
)


def vote_text(vote: str = "Station Delta") -> str:
    return json.dumps(
        {"vote": vote, "rationale": f"Evidence favors {vote}."}
    )


def protocol_script() -> tuple[str, ...]:
    outputs: list[str] = []
    outputs.extend(vote_text() for _ in range(4))
    outputs.extend(
        f"Discussion statement {index:02d} supports Station Delta."
        for index in range(60)
    )
    outputs.extend(vote_text() for _ in range(4))
    outputs.extend(vote_text() for _ in range(4))
    return tuple(outputs)


def test_vote_parser_accepts_json_inside_code_fence() -> None:
    parsed = parse_hiddenbench_vote(
        TASK,
        '```json\n{"vote":"Station Delta","rationale":"Safe."}\n```',
    )

    assert parsed == ("Station Delta", "Safe.")


@pytest.mark.parametrize(
    "payload,match",
    [
        ('{"vote":"Unknown","rationale":"R"}', "official possible_answers"),
        ('{"vote":"Station Delta"}', "rationale"),
        ("not-json", "JSON object"),
    ],
)
def test_vote_parser_rejects_invalid_payload(
    payload: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_hiddenbench_vote(TASK, payload)


@pytest.mark.asyncio
async def test_invalid_vote_gets_exactly_one_repair_request() -> None:
    assignment = assign_hidden_information(TASK, seed=20260728)
    system_prompt = build_hidden_system_prompt(
        TASK,
        assignment,
        "agent-a",
    )
    user_prompt = build_vote_user_prompt(
        TASK,
        (),
        phase="hidden_pre",
    )
    provider = ScriptedPromptProvider(("not-json", vote_text()))

    vote = await complete_hiddenbench_vote(
        TASK,
        provider,
        agent_id="agent-a",
        condition="hidden_pre",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        seed=20260728,
    )

    assert len(provider.calls) == 2
    assert vote.vote == "Station Delta"
    assert vote.user_prompt == user_prompt
    assert vote.provider_metadata["repair_requests"] == 1
    assert vote.provider_metadata["invalid_raw_text"] == "not-json"
    assert "Return only one valid JSON object" in str(
        vote.provider_metadata["repair_prompt"]
    )


@pytest.mark.asyncio
async def test_vote_fails_after_one_unsuccessful_repair() -> None:
    assignment = assign_hidden_information(TASK, seed=20260728)
    provider = ScriptedPromptProvider(("not-json", "still-not-json"))

    with pytest.raises(ValueError, match="invalid after one repair request"):
        await complete_hiddenbench_vote(
            TASK,
            provider,
            agent_id="agent-a",
            condition="hidden_pre",
            system_prompt=build_hidden_system_prompt(
                TASK,
                assignment,
                "agent-a",
            ),
            user_prompt=build_vote_user_prompt(
                TASK,
                (),
                phase="hidden_pre",
            ),
            seed=20260728,
        )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_full_protocol_has_72_slots_and_fixed_round_robin() -> None:
    provider = ScriptedPromptProvider(protocol_script())

    run = await run_hiddenbench_task(
        TASK,
        provider,
        seed=20260728,
        discussion_rounds=15,
    )

    assert len(provider.calls) == 72
    assert len(run.hidden_pre_votes) == 4
    assert len(run.discussion_messages) == 60
    assert len(run.hidden_post_votes) == 4
    assert len(run.full_profile_votes) == 4
    assert [
        message.agent_id for message in run.discussion_messages[:8]
    ] == [
        "agent-a",
        "agent-b",
        "agent-c",
        "agent-d",
        "agent-a",
        "agent-b",
        "agent-c",
        "agent-d",
    ]
    assert run.discussion_messages[-1].round_index == 15
    assert run.discussion_messages[-1].turn_index == 59
    assert len(run.discussion_messages[-1].visible_message_ids) == 59


@pytest.mark.asyncio
async def test_protocol_preserves_visibility_boundaries_and_full_history() -> None:
    provider = ScriptedPromptProvider(protocol_script())

    run = await run_hiddenbench_task(
        TASK,
        provider,
        seed=20260728,
    )

    for vote in run.hidden_pre_votes:
        own_fact = run.assignment.private_information[vote.agent_id]
        assert own_fact in vote.system_prompt
        for agent_id, fact in run.assignment.private_information.items():
            if agent_id != vote.agent_id:
                assert fact not in vote.system_prompt
    for index, message in enumerate(run.discussion_messages):
        assert message.visible_message_ids == tuple(
            previous.message_id
            for previous in run.discussion_messages[:index]
        )
    for vote in run.hidden_post_votes:
        assert all(
            message.content in vote.user_prompt
            for message in run.discussion_messages
        )
    for vote in run.full_profile_votes:
        assert all(
            fact in vote.system_prompt
            for fact in TASK.hidden_information
        )


@pytest.mark.asyncio
async def test_protocol_does_not_stop_when_all_votes_are_identical() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(protocol_script()),
        seed=20260728,
    )

    assert {vote.vote for vote in run.hidden_pre_votes} == {
        "Station Delta"
    }
    assert len(run.discussion_messages) == 60
