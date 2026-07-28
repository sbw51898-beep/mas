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


@pytest.mark.parametrize(
    ("fact", "message"),
    (
        (
            "Repair teams confirm that solar panels at Station Charlie are "
            "offline due to windstorm damage. The backup batteries are "
            "depleted and the station has no power.",
            "Given the power outage at Station Charlie, I would rule it out.",
        ),
        (
            "Community hotline reported that Station Alpha's ventilation "
            "system was unintentionally exposed to outdoor air after "
            "yesterday's accident. Test results show elevated toxin levels "
            "inside.",
            "Station Alpha is unsafe due to elevated toxin levels from "
            "ventilation exposure.",
        ),
        (
            "Maintenance crew at Station Delta inspected all major systems "
            "this morning and confirmed water is safe, backup lights work, "
            "and no signs of contamination were found.",
            "Station Delta's systems have been confirmed safe, so I support "
            "Delta.",
        ),
        (
            "Field agent at Bravo reports air sensors detected low but "
            "abnormal readings, suggesting possible chemical contamination "
            "near Station Bravo.",
            "There is potential contamination near Station Bravo, so Bravo "
            "should be excluded.",
        ),
    ),
)
def test_compressed_paraphrases_count_as_private_fact_disclosure(
    fact: str,
    message: str,
) -> None:
    assert lexical_fact_match(fact, message)


@pytest.mark.parametrize(
    ("fact", "message"),
    (
        (
            "Repair teams confirm that solar panels at Station Charlie are "
            "offline due to windstorm damage. The backup batteries are "
            "depleted and the station has no power.",
            "Station Charlie is on higher ground and has solar power.",
        ),
        (
            "Maintenance crew at Station Delta inspected all major systems "
            "this morning and confirmed water is safe, backup lights work, "
            "and no signs of contamination were found.",
            "Station Delta may be contaminated and should be avoided.",
        ),
    ),
)
def test_entity_mention_or_reversed_claim_is_not_disclosure(
    fact: str,
    message: str,
) -> None:
    assert not lexical_fact_match(fact, message)


def test_atomic_bullet_fact_can_be_disclosed_without_repeating_bundle() -> None:
    fact = """Stevens' information:
- Comments indicate thatStevens discourages innovative ideas
Roberts' information:
- Increased faculty diversity
Jones' information:
- Jones is a strategic thinker
- There is tension between the provost and Jones"""

    assert lexical_fact_match(
        fact,
        "Jones is a strategic thinker despite tension with the provost.",
    )
    assert lexical_fact_match(
        fact,
        "Stevens remains concerning because he discourages innovation.",
    )
    assert not lexical_fact_match(
        fact,
        "Jones is my recommendation because the group supports Jones.",
    )


def test_structured_criterion_requires_matching_entity_value_and_polarity() -> None:
    fact = """Franklin Enterprises:
- (a) N
- (c) N
Starlight Incorporated:
- (e) Y"""

    assert lexical_fact_match(
        fact,
        "Franklin Enterprises fails criteria (a) and (c).",
    )
    assert not lexical_fact_match(
        fact,
        "Franklin Enterprises meets criterion (a).",
    )


def test_same_words_in_different_claim_do_not_count_as_disclosure() -> None:
    fact = (
        "A cable cut near Data Center Charlie was fully repaired, and the "
        "center passed an extra security audit."
    )
    message = (
        "Data Center Charlie is safest because Alpha faces a power cut and "
        "Charlie has physical security."
    )

    assert not lexical_fact_match(fact, message)


def test_single_letter_entity_anchor_must_match_entity_type_and_value() -> None:
    fact = (
        "Hospital A's mountain road has been cleared and independently "
        "confirmed safe."
    )
    message = (
        "Hospital B is a safe choice because its mountain road is clear."
    )

    assert not lexical_fact_match(fact, message)


@pytest.mark.parametrize(
    ("fact", "message"),
    (
        (
            "Construction near Data Center Alpha creates a risk of power cuts.",
            "The imminent power cut risk at Alpha makes Charlie safer.",
        ),
        (
            "Restaurant C's cold menu remains available from a backup prep area.",
            "C's cold menu may not satisfy everyone's preferences.",
        ),
    ),
)
def test_unambiguous_short_entity_references_are_supported(
    fact: str,
    message: str,
) -> None:
    assert lexical_fact_match(fact, message)


@pytest.mark.parametrize(
    ("fact", "message"),
    (
        (
            "Stevens tends to discourage new, innovative ideas.",
            "I remain concerned about Stevens discouraging innovation.",
        ),
        (
            "The health department warned of a norovirus outbreak among "
            "cooks at Restaurant A.",
            "Restaurant A has a norovirus outbreak.",
        ),
        (
            "Option B's chief engineer will resign immediately after an "
            "acquisition.",
            "Option B risks losing its chief engineer after acquisition.",
        ),
        (
            "Station Delta has safe water, working backup lights, and no "
            "signs of contamination.",
            "Station Delta has safe water and backup lights and avoids all "
            "contamination risks.",
        ),
    ),
)
def test_domain_paraphrases_preserve_claim_polarity(
    fact: str,
    message: str,
) -> None:
    assert lexical_fact_match(fact, message)


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
