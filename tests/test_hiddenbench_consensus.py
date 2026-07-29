from mas_experiment.hiddenbench_consensus import (
    analyze_consensus_dynamics,
    extract_expressed_position,
)
from mas_experiment.hiddenbench_domain import AGENT_IDS, HiddenBenchMessage


ANSWERS = ("West City", "East Town", "North Hill")


def make_message(
    index: int,
    agent_id: str,
    answer: str,
) -> HiddenBenchMessage:
    return HiddenBenchMessage(
        message_id=f"message-{index}",
        round_index=index // 4 + 1,
        turn_index=index,
        agent_id=agent_id,
        content=f"I recommend {answer}.",
        visible_message_ids=(),
        system_prompt="system",
        user_prompt="user",
    )


def consensus_then_flip_messages() -> tuple[HiddenBenchMessage, ...]:
    messages: list[HiddenBenchMessage] = []
    for index in range(8):
        messages.append(
            make_message(
                index,
                AGENT_IDS[index % 4],
                "West City",
            )
        )
    for index in range(8, 12):
        messages.append(
            make_message(
                index,
                AGENT_IDS[index % 4],
                "East Town",
            )
        )
    return tuple(messages)


def test_ambiguous_multi_option_message_has_no_position() -> None:
    assert (
        extract_expressed_position(
            "West City is supplied, but East Town is safer.",
            ANSWERS,
        )
        is None
    )


def test_recommendation_cue_extracts_one_position() -> None:
    assert (
        extract_expressed_position(
            "After reviewing the facts, I recommend West City.",
            ANSWERS,
        )
        == "West City"
    )


def test_stable_consensus_and_flip_are_counted() -> None:
    result = analyze_consensus_dynamics(
        messages=consensus_then_flip_messages(),
        possible_answers=ANSWERS,
        correct_answer="West City",
        new_rule_disclosures_by_message={},
    )

    assert result.first_consensus_turn == 4
    assert result.first_stable_consensus_turn == 4
    assert result.stable_consensus_confirmed_turn == 8
    assert result.consensus_flips == 1
    assert result.first_stable_consensus_correct is True
    assert result.final_consensus_answer == "East Town"
