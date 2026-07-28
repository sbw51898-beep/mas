from __future__ import annotations

from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
    HiddenBenchRawRun,
    HiddenBenchVote,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_metrics import (
    compute_hiddenbench_metrics,
    fact_content_terms,
    lexical_fact_match,
    score_hiddenbench_run,
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


def make_votes(
    values: tuple[str, str, str, str],
    condition: str,
    *,
    rationales: tuple[str, str, str, str] | None = None,
) -> tuple[HiddenBenchVote, ...]:
    reasons = rationales or tuple(
        f"Evidence favors {value}." for value in values
    )
    return tuple(
        HiddenBenchVote(
            agent_id=agent_id,
            condition=condition,
            vote=value,
            rationale=reason,
            raw_text="raw",
            system_prompt="system",
            user_prompt="user",
        )
        for agent_id, value, reason in zip(
            AGENT_IDS,
            values,
            reasons,
            strict=True,
        )
    )


def make_message(
    *,
    index: int,
    agent_id: str,
    content: str,
) -> HiddenBenchMessage:
    return HiddenBenchMessage(
        message_id=f"m-{index}",
        round_index=index // 4 + 1,
        turn_index=index,
        agent_id=agent_id,
        content=content,
        visible_message_ids=(),
        system_prompt="system",
        user_prompt="user",
    )


PRE = make_votes(
    (
        "Station Alpha",
        "Station Delta",
        "Station Alpha",
        "Station Bravo",
    ),
    "hidden_pre",
)
POST = make_votes(
    (
        "Station Delta",
        "Station Delta",
        "Station Delta",
        "Station Alpha",
    ),
    "hidden_post",
)
FULL = make_votes(
    (
        "Station Delta",
        "Station Delta",
        "Station Delta",
        "Station Delta",
    ),
    "full_profile",
)


def test_main_metrics_match_hand_calculation() -> None:
    metrics, _ = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        (),
        POST,
        FULL,
    )

    assert metrics.y_pre_average == pytest.approx(0.25)
    assert metrics.y_post_average == pytest.approx(0.75)
    assert metrics.y_full_average == pytest.approx(1.0)
    assert metrics.integration_gain == pytest.approx(0.5)
    assert metrics.full_profile_gap == pytest.approx(-0.25)
    assert metrics.post_majority_correct is True
    assert metrics.post_unanimous is False
    assert metrics.full_unanimous is True
    assert metrics.consensus_round is None


def test_tied_vote_is_not_a_majority() -> None:
    tied = make_votes(
        (
            "Station Delta",
            "Station Delta",
            "Station Alpha",
            "Station Alpha",
        ),
        "hidden_post",
    )

    metrics, _ = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        (),
        tied,
        FULL,
    )

    assert metrics.post_majority_correct is False


def test_lexical_match_requires_six_terms_and_55_percent_coverage() -> None:
    fact = TASK.hidden_information[0]
    terms = fact_content_terms(fact)

    assert lexical_fact_match(fact, fact)
    assert not lexical_fact_match(fact, " ".join(terms[:5]))


def test_disclosure_and_later_cross_agent_use_are_fact_level() -> None:
    fact = TASK.hidden_information[0]
    owner = next(
        agent_id
        for agent_id, private_fact in ASSIGNMENT.private_information.items()
        if private_fact == fact
    )
    peer = next(agent_id for agent_id in AGENT_IDS if agent_id != owner)
    messages = (
        make_message(index=0, agent_id=owner, content=fact),
        make_message(index=1, agent_id=peer, content=fact),
    )

    metrics, candidates = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        messages,
        POST,
        FULL,
    )

    assert metrics.private_fact_disclosure_rate == pytest.approx(0.25)
    assert metrics.cross_agent_use_rate == pytest.approx(0.25)
    assert not any(
        candidate.failure_mode == "FM-2.4"
        and candidate.fact == fact
        for candidate in candidates
    )


def test_peer_guess_before_disclosure_is_not_cross_agent_use() -> None:
    fact = TASK.hidden_information[0]
    owner = next(
        agent_id
        for agent_id, private_fact in ASSIGNMENT.private_information.items()
        if private_fact == fact
    )
    peer = next(agent_id for agent_id in AGENT_IDS if agent_id != owner)
    messages = (
        make_message(index=0, agent_id=peer, content=fact),
        make_message(index=1, agent_id=owner, content=fact),
    )

    metrics, _ = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        messages,
        POST,
        FULL,
    )

    assert metrics.private_fact_disclosure_rate == pytest.approx(0.25)
    assert metrics.cross_agent_use_rate == pytest.approx(0.0)


def test_undisclosed_facts_create_manual_fm24_candidates() -> None:
    _, candidates = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        (),
        POST,
        FULL,
    )
    fm24 = [
        candidate
        for candidate in candidates
        if candidate.failure_mode == "FM-2.4"
    ]

    assert len(fm24) == 4
    assert all(candidate.requires_manual_review for candidate in fm24)
    assert {candidate.fact for candidate in fm24} == set(
        TASK.hidden_information
    )


def test_single_conflicting_answer_in_rationale_creates_fm26_candidate() -> None:
    conflicting_post = make_votes(
        (
            "Station Delta",
            "Station Delta",
            "Station Delta",
            "Station Delta",
        ),
        "hidden_post",
        rationales=(
            "Station Alpha is the best choice.",
            "Evidence supports the safe option.",
            "Evidence supports the safe option.",
            "Evidence supports the safe option.",
        ),
    )

    _, candidates = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        (),
        conflicting_post,
        FULL,
    )

    assert any(
        candidate.failure_mode == "FM-2.6"
        and candidate.agent_id == "agent-a"
        and "Station Alpha" in candidate.evidence_text[0]
        for candidate in candidates
    )


def test_negated_alternative_does_not_create_fm26_candidate() -> None:
    post = make_votes(
        (
            "Station Delta",
            "Station Delta",
            "Station Delta",
            "Station Delta",
        ),
        "hidden_post",
        rationales=(
            "Station Alpha is not acceptable.",
            "Evidence supports the safe option.",
            "Evidence supports the safe option.",
            "Evidence supports the safe option.",
        ),
    )

    _, candidates = compute_hiddenbench_metrics(
        TASK,
        ASSIGNMENT,
        PRE,
        (),
        post,
        FULL,
    )

    assert not any(
        candidate.failure_mode == "FM-2.6"
        and candidate.agent_id == "agent-a"
        for candidate in candidates
    )


def test_score_raw_run_copies_audit_fields_and_provider_totals() -> None:
    raw = HiddenBenchRawRun(
        run_id="run-1",
        task=TASK,
        assignment=ASSIGNMENT,
        hidden_pre_votes=PRE,
        discussion_messages=(),
        hidden_post_votes=POST,
        full_profile_votes=FULL,
        provider_metadata={
            "api_requests": 72,
            "repair_requests": 1,
            "usage": {"input_token_count": 100},
        },
        configuration_fingerprint="f" * 64,
        code_commit="a" * 40,
    )

    scored = score_hiddenbench_run(raw)

    assert scored.run_id == "run-1"
    assert scored.configuration_fingerprint == "f" * 64
    assert scored.metrics.api_requests == 72
    assert scored.metrics.repair_requests == 1
    assert scored.metrics.usage["input_token_count"] == 100
