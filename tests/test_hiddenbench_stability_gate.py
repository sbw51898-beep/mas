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
    derive_pair_seed,
    load_stability_config,
)
from mas_experiment.hiddenbench_stability_gate import (
    build_stability_gate,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_stability_config(
    ROOT / "configs/hiddenbench-ai-disclosure-stability.json"
)


def load_base_run() -> HiddenBenchRun:
    path = ROOT / "artifacts/hiddenbench-screening-20260728-v2.jsonl"
    with path.open(encoding="utf-8") as stream:
        return HiddenBenchRun.model_validate_json(next(stream))


def complete_matrix() -> tuple[
    tuple[StudyRunRecord, ...],
    tuple[DisclosureAudit, ...],
]:
    base = load_base_run()
    records: list[StudyRunRecord] = []
    audits: list[DisclosureAudit] = []
    for task_id in CONFIG.task_ids:
        for repetition in range(CONFIG.repetitions):
            seed = derive_pair_seed(
                CONFIG.base_seed,
                task_id=task_id,
                repetition=repetition,
            )
            task = base.task.model_copy(update={"id": task_id})
            assignment = base.assignment.model_copy(
                update={"task_id": task_id, "seed": seed}
            )
            run = base.model_copy(
                update={
                    "run_id": f"run-{task_id}-{repetition}",
                    "task": task,
                    "assignment": assignment,
                    "provider_metadata": {
                        **base.provider_metadata,
                        "selector_llm_calls": 0,
                    },
                }
            )
            fingerprint = assignment_fingerprint(run)
            for condition in CONFIG.conditions:
                key = StudyKey(
                    task_id=task_id,
                    condition=condition,
                    repetition=repetition,
                )
                records.append(
                    StudyRunRecord.model_construct(
                        key=key,
                        pair_seed=seed,
                        assignment_fingerprint=fingerprint,
                        run=run,
                        baseline_run_id=(
                            run.run_id if condition == "dynamic" else None
                        ),
                        selection_events=(),
                    )
                )
                judgments = tuple(
                    FactDisclosureJudgment(
                        fact_id=f"private-fact:{owner}",
                        owner_agent_id=owner,
                        disclosed=False,
                        evidence_message_ids=(),
                        evidence_quote="",
                        reason="No disclosure.",
                        confidence=0.9,
                    )
                    for owner in run.assignment.private_information
                )
                audits.append(
                    DisclosureAudit(
                        study_key=key,
                        judge_model=CONFIG.judge_model,
                        judge_prompt_version=CONFIG.judge_prompt_version,
                        judgments=judgments,
                        disclosure_rate=0,
                        provider_metadata={"attempts": 1},
                    )
                )
    return tuple(records), tuple(audits)


COMPLETE_RECORDS, COMPLETE_AUDITS = complete_matrix()


def test_complete_gate_passes() -> None:
    gate = build_stability_gate(
        CONFIG,
        COMPLETE_RECORDS,
        COMPLETE_AUDITS,
        dataset_path=ROOT / "data/hiddenbench/benchmark.json",
    )

    assert gate.passed
    assert all(gate.checks.values())


def test_gate_fails_missing_audit_or_budget_mismatch() -> None:
    first = COMPLETE_RECORDS[0]
    short_run = first.run.model_copy(
        update={
            "discussion_messages": first.run.discussion_messages[:-1]
        }
    )
    bad_records = (
        StudyRunRecord.model_construct(
            **{
                **first.__dict__,
                "run": short_run,
            }
        ),
        *COMPLETE_RECORDS[1:],
    )

    gate = build_stability_gate(
        CONFIG,
        bad_records,
        COMPLETE_AUDITS[:-1],
        dataset_path=ROOT / "data/hiddenbench/benchmark.json",
    )

    assert not gate.passed
    assert not gate.checks["complete_ai_audits"]
    assert not gate.checks["equal_speech_budgets"]
