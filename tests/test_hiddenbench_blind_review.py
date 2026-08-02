from __future__ import annotations

from pathlib import Path

import pytest

from mas_experiment.hiddenbench_blind_review import (
    BlindReviewCase,
    BlindReviewMessage,
    ReviewJudgment,
    append_artifact_label,
    build_blind_queue_row,
    compute_weighted_review_metrics,
    load_json_object,
    parse_human_disclosed,
    select_blind_review_sample,
    validate_review_judgment_evidence,
)


def _case(
    name: str,
    *,
    ai: bool,
    rule: bool,
    task_id: int = 1,
    condition: str = "fixed",
) -> BlindReviewCase:
    return BlindReviewCase(
        blind_id=name,
        study_key=f"task-{task_id}:{condition}:rep-0",
        task_id=task_id,
        condition=condition,
        fact_id=f"private-fact:{name}",
        owner_agent_id="agent-a",
        fact=f"fact {name}",
        owner_messages=(),
        ai_disclosed=ai,
        rule_disclosed=rule,
    )


def test_sample_keeps_all_disagreements_and_stratifies_agreements() -> None:
    population = (
        _case("d1", ai=True, rule=False),
        _case("d2", ai=False, rule=True),
        _case("p1", ai=True, rule=True, task_id=1),
        _case("p2", ai=True, rule=True, task_id=5),
        _case("p3", ai=True, rule=True, task_id=7),
        _case("n1", ai=False, rule=False, task_id=1),
        _case("n2", ai=False, rule=False, task_id=5),
        _case("n3", ai=False, rule=False, task_id=7),
    )

    selected = select_blind_review_sample(
        population,
        agreement_sample_per_ai_label=3,
        seed=20260730,
    )

    assert {item.blind_id for item in selected if item.ai_disclosed != item.rule_disclosed} == {
        "d1",
        "d2",
    }
    assert sum(item.ai_disclosed and item.ai_disclosed == item.rule_disclosed for item in selected) == 3
    assert sum((not item.ai_disclosed) and item.ai_disclosed == item.rule_disclosed for item in selected) == 3
    assert selected == select_blind_review_sample(
        population,
        agreement_sample_per_ai_label=3,
        seed=20260730,
    )


def test_blind_payload_does_not_expose_prior_labels() -> None:
    case = _case("blind", ai=True, rule=False)

    payload = case.blind_payload()

    assert "ai_disclosed" not in payload
    assert "rule_disclosed" not in payload
    assert payload["blind_id"] == "blind"


def test_weighted_metrics_expand_sampled_agreement_strata() -> None:
    population = (
        _case("d1", ai=True, rule=False),
        _case("d2", ai=False, rule=True),
        *tuple(_case(f"p{i}", ai=True, rule=True) for i in range(4)),
        *tuple(_case(f"n{i}", ai=False, rule=False) for i in range(4)),
    )
    reviewed = (
        ReviewJudgment(blind_id="d1", disclosed=False),
        ReviewJudgment(blind_id="d2", disclosed=True),
        ReviewJudgment(blind_id="p0", disclosed=True),
        ReviewJudgment(blind_id="p1", disclosed=False),
        ReviewJudgment(blind_id="n0", disclosed=False),
        ReviewJudgment(blind_id="n1", disclosed=True),
    )

    metrics = compute_weighted_review_metrics(population, reviewed)

    assert metrics.estimated_tp == 2
    assert metrics.estimated_fp == 3
    assert metrics.estimated_tn == 2
    assert metrics.estimated_fn == 3
    assert metrics.ai_human_agreement == 0.4
    assert metrics.ai_precision == 0.4
    assert metrics.ai_recall == 0.4
    assert metrics.revised_disclosure_rate == 0.5


def test_review_evidence_must_be_owner_authored_and_exact() -> None:
    case = BlindReviewCase(
        blind_id="evidence",
        study_key="task-1:fixed:rep-0",
        task_id=1,
        condition="fixed",
        fact_id="private-fact:agent-a",
        owner_agent_id="agent-a",
        fact="The road is closed.",
        owner_messages=(
            BlindReviewMessage(
                message_id="m1",
                turn_index=0,
                content="The road is closed because of flooding.",
            ),
        ),
        ai_disclosed=True,
        rule_disclosed=True,
    )
    valid = ReviewJudgment(
        blind_id="evidence",
        disclosed=True,
        evidence_message_ids=("m1",),
        evidence_quote="The road is closed",
    )

    validate_review_judgment_evidence(case, valid)

    with pytest.raises(ValueError, match="exact substring"):
        validate_review_judgment_evidence(
            case,
            valid.model_copy(update={"evidence_quote": "road may be open"}),
        )
    with pytest.raises(ValueError, match="must be empty"):
        validate_review_judgment_evidence(
            case,
            ReviewJudgment(
                blind_id="evidence",
                disclosed=False,
                evidence_message_ids=("m1",),
                evidence_quote="The road is closed",
            ),
        )


def test_queue_row_serializes_owner_messages_without_extra_fields() -> None:
    case = BlindReviewCase(
        blind_id="queue",
        study_key="task-1:fixed:rep-0",
        task_id=1,
        condition="fixed",
        fact_id="private-fact:agent-a",
        owner_agent_id="agent-a",
        fact="The road is closed.",
        owner_messages=(
            BlindReviewMessage(
                message_id="m1",
                turn_index=0,
                content="The road is closed.",
            ),
        ),
        ai_disclosed=True,
        rule_disclosed=False,
    )

    row = build_blind_queue_row(case)

    assert "owner_messages" not in row
    assert row["owner_messages_json"].startswith("[")
    assert row["human_disclosed"] == ""


def test_artifact_label_is_appended_without_dropping_existing_label() -> None:
    base = Path("hiddenbench-stability-20260729.blind-review")

    assert append_artifact_label(base, "queue.csv") == Path(
        "hiddenbench-stability-20260729.blind-review.queue.csv"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    (("true", True), ("是", True), ("1", True), ("false", False), ("否", False), ("0", False)),
)
def test_human_disclosed_parser_accepts_explicit_binary_labels(
    raw: str,
    expected: bool,
) -> None:
    assert parse_human_disclosed(raw) is expected


def test_human_disclosed_parser_rejects_blank_or_ambiguous_labels() -> None:
    with pytest.raises(ValueError, match="explicit"):
        parse_human_disclosed("")
    with pytest.raises(ValueError, match="explicit"):
        parse_human_disclosed("maybe")


def test_load_json_object_requires_an_object(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text('{"status": "ok"}', encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[1, 2]", encoding="utf-8")

    assert load_json_object(valid) == {"status": "ok"}
    with pytest.raises(ValueError, match="object"):
        load_json_object(invalid)
