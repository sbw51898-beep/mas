from __future__ import annotations

from pathlib import Path

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import DynamicSelectorConfig
from mas_experiment.hiddenbench_dynamic_selector import (
    atomize_private_text,
    extract_stance,
    score_dynamic_candidates,
    select_dynamic_speaker,
)


TASK = load_hiddenbench_task(
    Path("data/hiddenbench/benchmark.json"),
    task_id=1,
    expected_sha256=(
        "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
    ),
)
ASSIGNMENT = assign_hidden_information(TASK, seed=20260728)
CONFIG = DynamicSelectorConfig(
    disagreement=0.30,
    undisclosed=0.30,
    related_discussion=0.15,
    response_due=0.15,
    waiting=0.10,
)


def message(turn: int, agent: str, content: str) -> HiddenBenchMessage:
    return HiddenBenchMessage(
        message_id=f"m{turn}",
        round_index=turn // 4 + 1,
        turn_index=turn,
        agent_id=agent,
        content=content,
        visible_message_ids=tuple(f"m{i}" for i in range(turn)),
        system_prompt="system",
        user_prompt="user",
    )


def selector_kwargs() -> dict:
    return {
        "task": TASK,
        "assignment": ASSIGNMENT,
        "pre_stances": {
            "agent-a": "West City",
            "agent-b": "East Town",
            "agent-c": "East Town",
            "agent-d": "East Town",
        },
        "public_messages": (),
        "remaining_quotas": {agent: 15 for agent in AGENT_IDS},
        "last_spoken_turns": {agent: -1 for agent in AGENT_IDS},
        "config": CONFIG,
        "turn_index": 0,
    }


def test_atomizer_keeps_heading_on_criterion_lines() -> None:
    atoms = atomize_private_text(
        "agent-a",
        "Starlight Incorporated:\n- (e) Y\n- (h) Y",
    )

    assert [atom.text for atom in atoms] == [
        "Starlight Incorporated: (e) Y",
        "Starlight Incorporated: (h) Y",
    ]


def test_atomizer_keeps_candidate_heading_on_biographical_bullets() -> None:
    atoms = atomize_private_text(
        "agent-a",
        "Stevens' information:\n"
        "- Left before raising funds\n"
        "Roberts' information:\n"
        "- Increased faculty diversity",
    )

    assert [atom.text for atom in atoms] == [
        "Stevens' information: Left before raising funds",
        "Roberts' information: Increased faculty diversity",
    ]


def test_atomizer_treats_single_sentence_as_one_atom() -> None:
    atoms = atomize_private_text(
        "agent-a",
        "A mudslide covered the driveway to North Hill.",
    )

    assert [atom.text for atom in atoms] == [
        "A mudslide covered the driveway to North Hill."
    ]


def test_stance_updates_only_for_one_exact_possible_answer() -> None:
    assert extract_stance(TASK, "West City is safest.", "East Town") == (
        "West City"
    )
    assert extract_stance(
        TASK,
        "West City is open but East Town has volunteers.",
        "North Hill",
    ) == "North Hill"


def test_unique_plurality_gives_dissenter_disagreement_one() -> None:
    scores = score_dynamic_candidates(**selector_kwargs())
    by_agent = {score.agent_id: score for score in scores}

    assert by_agent["agent-a"].disagreement == 1
    assert by_agent["agent-b"].disagreement == 0


def test_agents_with_zero_quota_are_not_scored() -> None:
    kwargs = selector_kwargs()
    kwargs["remaining_quotas"] = {
        "agent-a": 0,
        "agent-b": 15,
        "agent-c": 15,
        "agent-d": 15,
    }

    scores = score_dynamic_candidates(**kwargs)

    assert {score.agent_id for score in scores} == {
        "agent-b",
        "agent-c",
        "agent-d",
    }


def test_owner_disclosure_reduces_undisclosed_score() -> None:
    owner = "agent-a"
    fact = ASSIGNMENT.private_information[owner]
    before = {
        score.agent_id: score
        for score in score_dynamic_candidates(**selector_kwargs())
    }[owner]
    kwargs = selector_kwargs()
    kwargs["public_messages"] = (message(0, owner, fact),)
    kwargs["turn_index"] = 1
    kwargs["last_spoken_turns"] = {
        **kwargs["last_spoken_turns"],
        owner: 0,
    }
    after = {
        score.agent_id: score
        for score in score_dynamic_candidates(**kwargs)
    }[owner]

    assert before.undisclosed == 1
    assert after.undisclosed == 0


def test_related_answer_mention_triggers_candidate_with_hidden_fact() -> None:
    owner = next(
        agent
        for agent, fact in ASSIGNMENT.private_information.items()
        if "East Town" in fact
    )
    other = next(agent for agent in AGENT_IDS if agent != owner)
    kwargs = selector_kwargs()
    kwargs["public_messages"] = (
        message(0, other, "East Town should be our choice."),
    )
    kwargs["turn_index"] = 1

    score = {
        item.agent_id: item
        for item in score_dynamic_candidates(**kwargs)
    }[owner]

    assert score.related_discussion == 1


def test_new_other_owner_disclosure_makes_response_due() -> None:
    candidate = "agent-a"
    owner = "agent-b"
    fact = ASSIGNMENT.private_information[owner]
    kwargs = selector_kwargs()
    kwargs["public_messages"] = (message(0, owner, fact),)
    kwargs["turn_index"] = 1

    score = {
        item.agent_id: item
        for item in score_dynamic_candidates(**kwargs)
    }[candidate]

    assert score.response_due == 1


def test_exact_tie_uses_lexical_agent_id() -> None:
    kwargs = selector_kwargs()
    kwargs["pre_stances"] = {agent: "West City" for agent in AGENT_IDS}

    selected, scores = select_dynamic_speaker(**kwargs)

    assert selected == "agent-a"
    chosen = next(score for score in scores if score.selected)
    assert chosen.tie_break_reason == "agent_id"
