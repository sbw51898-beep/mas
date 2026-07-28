from __future__ import annotations

from pathlib import Path

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import (
    HiddenBenchMessage,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_prompts import (
    build_discussion_user_prompt,
    build_full_profile_system_prompt,
    build_hidden_system_prompt,
    build_vote_repair_prompt,
    build_vote_user_prompt,
)


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
ASSIGNMENT = assign_hidden_information(TASK, seed=20260728)


def make_message(index: int) -> HiddenBenchMessage:
    return HiddenBenchMessage(
        message_id=f"message-{index:02d}",
        round_index=index // 4 + 1,
        turn_index=index,
        agent_id=f"agent-{chr(ord('a') + index % 4)}",
        content=f"Public statement {index:02d}",
        visible_message_ids=tuple(
            f"message-{previous:02d}" for previous in range(index)
        ),
        system_prompt="system",
        user_prompt="user",
    )


def test_hidden_system_prompt_contains_only_one_private_fact() -> None:
    prompt = build_hidden_system_prompt(TASK, ASSIGNMENT, "agent-a")

    assert TASK.description in prompt
    assert all(item in prompt for item in TASK.shared_information)
    assert ASSIGNMENT.private_information["agent-a"] in prompt
    for agent_id in ("agent-b", "agent-c", "agent-d"):
        assert ASSIGNMENT.private_information[agent_id] not in prompt
    assert "order of facts does not indicate importance or relationship" in prompt
    assert "Keep your response concise-just one or two sentences." in prompt
    assert prompt.count("\n- ") == 5


def test_hidden_system_prompt_does_not_explain_information_asymmetry() -> None:
    prompt = build_hidden_system_prompt(
        TASK,
        ASSIGNMENT,
        "agent-a",
    ).casefold()

    assert "hidden information" not in prompt
    assert "different information" not in prompt
    assert "information asymmetry" not in prompt
    assert "other agents may" not in prompt


def test_full_profile_prompt_contains_all_information_in_stable_order() -> None:
    first = build_full_profile_system_prompt(
        TASK,
        agent_id="agent-a",
        seed=20260728,
    )
    second = build_full_profile_system_prompt(
        TASK,
        agent_id="agent-a",
        seed=20260728,
    )

    assert first == second
    assert all(item in first for item in TASK.shared_information)
    assert all(item in first for item in TASK.hidden_information)
    assert first.count("\n- ") == 8


def test_discussion_prompts_match_turn_position() -> None:
    first = build_discussion_user_prompt(())
    later = build_discussion_user_prompt((make_message(0),))

    assert first == "You are the first to speak."
    assert "Previous messages from other people:" in later
    assert "agent-a: Public statement 00" in later
    assert "It’s your turn to speak." in later


def test_post_vote_prompt_contains_all_60_public_messages() -> None:
    messages = tuple(make_message(index) for index in range(60))

    prompt = build_vote_user_prompt(
        TASK,
        messages,
        phase="hidden_post",
    )

    assert all(message.content in prompt for message in messages)
    assert prompt.index("Public statement 00") < prompt.index(
        "Public statement 59"
    )
    assert '"vote"' in prompt
    assert '"rationale"' in prompt
    assert all(answer in prompt for answer in TASK.possible_answers)


def test_pre_and_full_vote_prompts_do_not_include_discussion_header() -> None:
    for phase in ("hidden_pre", "full_profile"):
        prompt = build_vote_user_prompt(TASK, (), phase=phase)
        assert "Previous messages from other people:" not in prompt
        assert "Please decide and provide your rationale" in prompt


def test_vote_repair_prompt_keeps_candidates_and_invalid_text() -> None:
    prompt = build_vote_repair_prompt(TASK, "not-json")

    assert "not-json" in prompt
    assert all(answer in prompt for answer in TASK.possible_answers)
    assert "Return only one valid JSON object" in prompt
