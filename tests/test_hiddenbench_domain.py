from __future__ import annotations

import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    assign_hidden_information,
)


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
EXPECTED_SHA = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)
SHOWCASE = load_hiddenbench_task(
    DATASET,
    task_id=25,
    expected_sha256=EXPECTED_SHA,
)


def test_assignment_is_deterministic_and_one_to_one() -> None:
    first = assign_hidden_information(SHOWCASE, seed=20260728)
    random.seed(999)
    second = assign_hidden_information(SHOWCASE, seed=20260728)

    assert first == second
    assigned = tuple(first.private_information.values())
    assert len(set(assigned)) == 4
    assert set(assigned) == set(SHOWCASE.hidden_information)


def test_hidden_visible_information_never_leaks_peer_facts() -> None:
    assignment = assign_hidden_information(SHOWCASE, seed=20260728)
    visible = assignment.visible_information_for("agent-a")

    assert set(SHOWCASE.shared_information) <= set(visible)
    assert assignment.private_information["agent-a"] in visible
    peer_facts = (
        set(assignment.private_information.values())
        - {assignment.private_information["agent-a"]}
    )
    assert not peer_facts & set(visible)
    assert len(visible) == 5


def test_visible_information_order_is_stable_but_agent_specific() -> None:
    assignment = assign_hidden_information(SHOWCASE, seed=20260728)

    first = assignment.visible_information_for("agent-a")
    second = assignment.visible_information_for("agent-a")
    peer = assignment.visible_information_for("agent-b")

    assert first == second
    assert first != peer


def test_unknown_agent_is_rejected() -> None:
    assignment = assign_hidden_information(SHOWCASE, seed=20260728)

    with pytest.raises(KeyError, match="unknown HiddenBench agent"):
        assignment.visible_information_for("agent-z")


def test_task_with_three_hidden_facts_cannot_be_assigned() -> None:
    task = load_hiddenbench_task(
        DATASET,
        task_id=4,
        expected_sha256=EXPECTED_SHA,
    )

    with pytest.raises(ValueError, match="exactly four hidden facts"):
        assign_hidden_information(task, seed=20260728)


def test_assignment_rejects_duplicate_private_facts() -> None:
    repeated = SHOWCASE.hidden_information[0]

    with pytest.raises(ValidationError, match="one unique private fact"):
        HiddenBenchAssignment(
            task_id=SHOWCASE.id,
            seed=20260728,
            shared_information=SHOWCASE.shared_information,
            private_information={
                agent_id: repeated for agent_id in AGENT_IDS
            },
        )
