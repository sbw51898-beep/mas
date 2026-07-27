from __future__ import annotations

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS


def test_dataset_has_ten_answerable_four_option_questions() -> None:
    assert len(QUESTIONS) == 10
    assert all(tuple(question.options) == ("A", "B", "C", "D") for question in QUESTIONS)
    assert all(question.correct_answer in question.options for question in QUESTIONS)


def test_dataset_has_three_stable_agent_ids() -> None:
    assert [role.agent_id for role in AGENT_ROLES] == [
        "agent-a",
        "agent-b",
        "agent-c",
    ]
    assert all(role.system_prompt.strip() for role in AGENT_ROLES)
