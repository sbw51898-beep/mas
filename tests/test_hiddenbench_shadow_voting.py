from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import HiddenBenchVote
from mas_experiment.hiddenbench_protocol import run_hiddenbench_task
from mas_experiment.hiddenbench_shadow_voting import (
    ShadowVoteCheckpoint,
    evaluate_early_stop,
    find_candidate_stop,
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


def _vote(answer: str, agent_index: int = 0) -> HiddenBenchVote:
    return HiddenBenchVote(
        agent_id=f"agent-{chr(ord('a') + agent_index)}",
        condition="shadow",
        vote=answer,
        rationale=f"shadow rationale {answer} {agent_index}",
        raw_text="{}",
        system_prompt="system",
        user_prompt="vote",
    )


def _checkpoint(round_index: int, answers: list[str]) -> ShadowVoteCheckpoint:
    return ShadowVoteCheckpoint(
        round_index=round_index,
        after_public_message_count=round_index * 4,
        votes=tuple(_vote(answer, index) for index, answer in enumerate(answers)),
    )


def test_stop_requires_two_consecutive_identical_unanimous_rounds() -> None:
    checkpoints = (
        _checkpoint(1, ["A", "A", "A", "A"]),
        _checkpoint(2, ["B", "B", "B", "B"]),
        _checkpoint(3, ["B", "B", "B", "B"]),
    )

    stop = find_candidate_stop(checkpoints)

    assert stop is not None
    assert stop.round_index == 3
    assert stop.answer == "B"


def test_split_vote_resets_consecutive_consensus() -> None:
    checkpoints = (
        _checkpoint(1, ["A", "A", "A", "A"]),
        _checkpoint(2, ["A", "A", "A", "B"]),
        _checkpoint(3, ["A", "A", "A", "A"]),
    )

    assert find_candidate_stop(checkpoints) is None


def test_no_consensus_returns_none() -> None:
    checkpoints = (
        _checkpoint(1, ["A", "B", "A", "B"]),
        _checkpoint(2, ["A", "A", "B", "B"]),
    )

    assert find_candidate_stop(checkpoints) is None


def test_early_stop_evaluation_compares_with_final_majority() -> None:
    checkpoints = (
        _checkpoint(1, ["A", "A", "A", "A"]),
        _checkpoint(2, ["A", "A", "A", "A"]),
    )

    evaluation = evaluate_early_stop(
        checkpoints,
        final_votes=tuple(
            _vote(answer, index)
            for index, answer in enumerate(["A", "A", "A", "B"])
        ),
        correct_answer="A",
        total_public_messages=60,
    )

    assert evaluation.candidate_round == 2
    assert evaluation.exact_match is True
    assert evaluation.candidate_correct is True
    assert evaluation.final_correct is True
    assert evaluation.saved_public_messages == 52


def _vote_text(answer: str, rationale: str) -> str:
    return json.dumps({"vote": answer, "rationale": rationale})


def _shadow_protocol_script() -> tuple[str, ...]:
    outputs: list[str] = []
    outputs.extend(
        _vote_text("West City", f"pre-{index}") for index in range(4)
    )
    for round_index in range(1, 4):
        outputs.extend(
            f"public round {round_index} speaker {index}"
            for index in range(4)
        )
        outputs.extend(
            _vote_text(
                "West City",
                f"SHADOW-ONLY-R{round_index}-A{index}",
            )
            for index in range(4)
        )
    outputs.extend(
        _vote_text("West City", f"post-{index}") for index in range(4)
    )
    outputs.extend(
        _vote_text("West City", f"full-{index}") for index in range(4)
    )
    return tuple(outputs)


@pytest.mark.asyncio
async def test_shadow_votes_are_collected_but_never_publicly_visible() -> None:
    provider = ScriptedPromptProvider(_shadow_protocol_script())

    record = await run_hiddenbench_task(
        TASK,
        provider,
        seed=20260804,
        discussion_rounds=3,
        collect_round_shadow_votes=True,
    )

    assert len(record.shadow_checkpoints) == 3
    assert all(len(item.votes) == 4 for item in record.shadow_checkpoints)
    public_prompts = [
        message.user_prompt for message in record.run.discussion_messages
    ]
    assert all("SHADOW-ONLY" not in prompt for prompt in public_prompts)
    assert not any(
        vote.rationale in message.user_prompt
        for checkpoint in record.shadow_checkpoints
        for vote in checkpoint.votes
        for message in record.run.discussion_messages
    )
    assert len(record.run.discussion_messages) == 12
    assert record.run.provider_metadata["shadow_vote_checkpoints"] == 3
