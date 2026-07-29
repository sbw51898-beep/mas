from __future__ import annotations

from pathlib import Path

from mas_experiment.hiddenbench_ai_disclosure import (
    DisclosureAudit,
    FactDisclosureJudgment,
)
from mas_experiment.hiddenbench_domain import HiddenBenchRun
from mas_experiment.hiddenbench_stability_domain import (
    StudyKey,
    StudyRunRecord,
    assignment_fingerprint,
    load_stability_config,
)
from mas_experiment.hiddenbench_stability_gate import StabilityGate
from mas_experiment.hiddenbench_stability_reporting import (
    build_fact_comparisons,
    summarize_stability,
    write_stability_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_stability_config(
    ROOT / "configs/hiddenbench-ai-disclosure-stability.json"
)


def fixture_record_and_audit() -> tuple[
    StudyRunRecord,
    DisclosureAudit,
]:
    path = ROOT / "artifacts/hiddenbench-screening-20260728-v2.jsonl"
    with path.open(encoding="utf-8") as stream:
        base = HiddenBenchRun.model_validate_json(next(stream))
    messages = tuple(
        message.model_copy(
            update={
                "content": f"I recommend {base.task.possible_answers[0]}."
            }
        )
        for message in base.discussion_messages
    )
    run = base.model_copy(update={"discussion_messages": messages})
    key = StudyKey(task_id=1, condition="fixed", repetition=0)
    record = StudyRunRecord.model_construct(
        key=key,
        pair_seed=run.assignment.seed,
        assignment_fingerprint=assignment_fingerprint(run),
        run=run,
        baseline_run_id=None,
        selection_events=(),
    )
    judgments = []
    for index, owner in enumerate(
        run.assignment.private_information
    ):
        disclosed = index == 1
        owner_message = next(
            message
            for message in messages
            if message.agent_id == owner
        )
        judgments.append(
            FactDisclosureJudgment(
                fact_id=f"private-fact:{owner}",
                owner_agent_id=owner,
                disclosed=disclosed,
                evidence_message_ids=(
                    (owner_message.message_id,)
                    if disclosed
                    else ()
                ),
                evidence_quote=(
                    owner_message.content if disclosed else ""
                ),
                reason="AI fixture judgment.",
                confidence=0.9,
            )
        )
    audit = DisclosureAudit(
        study_key=key,
        judge_model=CONFIG.judge_model,
        judge_prompt_version=CONFIG.judge_prompt_version,
        judgments=tuple(judgments),
        disclosure_rate=0.25,
        provider_metadata={"attempts": 1},
    )
    return record, audit


def test_fact_comparison_exposes_disagreement() -> None:
    record, audit = fixture_record_and_audit()

    rows = build_fact_comparisons(record, audit)
    row = next(item for item in rows if item.ai_disclosed)

    assert row.ai_disclosed is True
    assert row.rule_disclosed is False
    assert row.requires_manual_review is True


def test_summary_contains_stability_and_boundary_language(
    tmp_path: Path,
) -> None:
    record, audit = fixture_record_and_audit()
    gate = StabilityGate(checks={"test_fixture": True}, passed=True)

    paths = write_stability_bundle(
        config=CONFIG,
        records=(record,),
        audits=(audit,),
        gate=gate,
        output=tmp_path / "study.jsonl",
    )
    report = paths.report.read_text(encoding="utf-8")

    assert "10 repetitions" in report
    assert "wrong consensus" in report
    assert "AI-rule agreement" in report
    assert "Paired fixed-minus-dynamic differences" in report
    assert "does not establish general superiority" in report
    assert paths.manifest.is_file()

    summary = summarize_stability((record,), (audit,))[0]
    assert summary.mean_first_stable_consensus_turn is not None
    assert summary.mean_consensus_flips >= 0
    assert summary.mean_post_stable_messages >= 0
