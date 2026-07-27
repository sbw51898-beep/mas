from __future__ import annotations

import pytest

from mas_experiment.domain import Message, Question
from mas_experiment.information import calculate_information_measures


def test_information_measures_distinguish_exposure_use_and_ignored_input() -> None:
    question = Question(
        question_id="hidden",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta"},
        correct_answer="B",
        information_keywords={
            "agent-a": ("A=90", "B=70"),
            "agent-b": ("A=60", "B=95"),
        },
    )
    messages = (
        Message(
            message_id="m1",
            speaker="agent-a",
            round_index=0,
            content="My evidence includes A=90.",
        ),
        Message(
            message_id="m2",
            speaker="agent-b",
            round_index=1,
            content="I found A=60 and B=95.",
        ),
        Message(
            message_id="m3",
            speaker="agent-a",
            round_index=1,
            content="B=95 changes my assessment, alongside A=90.",
            visible_history_ids=("m2",),
        ),
        Message(
            message_id="m4",
            speaker="agent-b",
            round_index=1,
            content="My final answer remains B.",
            visible_history_ids=("m2", "m3"),
        ),
    )

    measures = calculate_information_measures(
        question,
        messages,
        initial_message_count=1,
    )

    assert measures.information_coverage == pytest.approx(0.75)
    assert measures.cross_agent_input_use_rate == pytest.approx(1 / 3)
    assert measures.ignored_input_candidate_rate == pytest.approx(0.5)


def test_structured_keyword_matches_model_omission_of_dimension_prefix() -> None:
    question = Question(
        question_id="hidden-prefix",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta"},
        correct_answer="A",
        information_keywords={
            "agent-a": ("ACCESS_A=92",),
            "agent-b": ("MEDICAL_B=78",),
        },
    )
    messages = (
        Message(
            message_id="m1",
            speaker="agent-a",
            round_index=0,
            content="My raw score is A=92.",
        ),
        Message(
            message_id="m2",
            speaker="agent-b",
            round_index=1,
            content="My raw score is B=78.",
        ),
        Message(
            message_id="m3",
            speaker="agent-a",
            round_index=1,
            content="I used B=78 from the other specialist.",
            visible_history_ids=("m2",),
        ),
    )

    measures = calculate_information_measures(
        question,
        messages,
        initial_message_count=1,
    )

    assert measures.information_coverage == pytest.approx(0.5)
    assert measures.cross_agent_input_use_rate == pytest.approx(0.5)


def test_same_numeric_alias_from_wrong_owner_does_not_count_as_use() -> None:
    question = Question(
        question_id="collision",
        prompt="Choose.",
        options={"A": "Alpha", "B": "Beta"},
        correct_answer="A",
        information_keywords={
            "agent-a": ("THREAT_C=88",),
            "agent-b": ("CONTINUITY_C=88",),
        },
    )
    messages = (
        Message(
            message_id="m1",
            speaker="agent-a",
            round_index=1,
            content="My threat score is C=88.",
        ),
    )

    measures = calculate_information_measures(
        question,
        messages,
        initial_message_count=0,
    )

    assert measures.information_coverage == pytest.approx(0.5)
    assert measures.cross_agent_input_use_rate == pytest.approx(0.0)
