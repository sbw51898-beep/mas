from __future__ import annotations

import pytest

from mas_experiment.datasets import (
    AGENT_ROLES,
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    QUESTIONS,
    SCREENING_DIFFICULTIES,
    SCREENING_QUESTIONS,
    SCREENING_ROLES,
    screening_weighted_totals,
    supplier_weighted_totals,
)


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


def test_formal_pilot_has_one_private_dimension_per_agent() -> None:
    assert set(FORMAL_PILOT_QUESTION.private_contexts) == {
        "agent-a",
        "agent-b",
        "agent-c",
    }
    assert "95" in FORMAL_PILOT_QUESTION.private_contexts["agent-a"]
    assert "95" in FORMAL_PILOT_QUESTION.private_contexts["agent-b"]
    assert "100" in FORMAL_PILOT_QUESTION.private_contexts["agent-c"]
    assert [role.agent_id for role in FORMAL_PILOT_ROLES] == [
        "agent-a",
        "agent-b",
        "agent-c",
    ]


def test_formal_pilot_answer_requires_combining_private_dimensions() -> None:
    assert FORMAL_PILOT_QUESTION.correct_answer == "C"
    assert supplier_weighted_totals() == {
        "A": pytest.approx(76.00),
        "B": pytest.approx(78.25),
        "C": pytest.approx(86.25),
        "D": pytest.approx(75.50),
    }


def test_screening_tasks_have_three_difficulties_and_complete_metadata() -> None:
    role_ids = {role.agent_id for role in SCREENING_ROLES}

    assert len(SCREENING_QUESTIONS) == 3
    assert set(SCREENING_DIFFICULTIES.values()) == {
        "easy",
        "medium",
        "hard",
    }
    for question in SCREENING_QUESTIONS:
        assert set(question.private_contexts) == role_ids
        assert set(question.information_keywords) == role_ids
        assert set(question.dependency_keywords) == role_ids
        assert all(question.information_keywords.values())
        totals = screening_weighted_totals(question.question_id)
        winner = max(totals, key=totals.get)
        assert winner == question.correct_answer
