from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean, pstdev

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.audit import write_sha256_manifest
from mas_experiment.hiddenbench_ai_disclosure import DisclosureAudit
from mas_experiment.hiddenbench_consensus import (
    analyze_consensus_dynamics,
)
from mas_experiment.hiddenbench_metrics import (
    rule_disclosure_evidence,
)
from mas_experiment.hiddenbench_reporting import _assert_no_secrets
from mas_experiment.hiddenbench_stability_domain import (
    StabilityStudyConfig,
    StudyCondition,
    StudyKey,
    StudyRunRecord,
)
from mas_experiment.hiddenbench_stability_gate import StabilityGate


class FactComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_key: StudyKey
    fact_id: str
    owner_agent_id: str
    fact: str
    ai_disclosed: bool
    rule_disclosed: bool
    agrees: bool
    requires_manual_review: bool
    ai_evidence_message_ids: tuple[str, ...]
    rule_evidence_message_ids: tuple[str, ...]


class StabilitySummaryRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: StudyCondition
    repetitions: int = Field(ge=1)
    ai_disclosure_mean: float
    ai_disclosure_std: float
    rule_disclosure_mean: float
    post_majority_correct_count: int
    post_unanimous_count: int
    wrong_consensus_count: int
    stable_consensus_count: int
    mean_first_consensus_turn: float | None
    mean_first_stable_consensus_turn: float | None
    mean_consensus_flips: float
    mean_post_stable_messages: float
    mean_repeated_confirmations: float
    ai_rule_agreement: float
    final_answer_distribution: dict[str, int]


class StabilityBundlePaths(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    runs: Path
    trace: Path
    ai_disclosure: Path
    disagreements: Path
    summary: Path
    report: Path
    gate: Path
    manifest: Path


def build_fact_comparisons(
    record: StudyRunRecord,
    audit: DisclosureAudit,
) -> tuple[FactComparison, ...]:
    if audit.study_key != record.key:
        raise ValueError("audit key does not match study record")
    rule = rule_disclosure_evidence(record.run)
    ai_by_fact = {
        item.fact_id: item for item in audit.judgments
    }
    rows: list[FactComparison] = []
    for owner, fact in record.run.assignment.private_information.items():
        fact_id = f"private-fact:{owner}"
        ai = ai_by_fact[fact_id]
        rule_item = rule[fact]
        agrees = ai.disclosed == rule_item.disclosed
        rows.append(
            FactComparison(
                study_key=record.key,
                fact_id=fact_id,
                owner_agent_id=owner,
                fact=fact,
                ai_disclosed=ai.disclosed,
                rule_disclosed=rule_item.disclosed,
                agrees=agrees,
                requires_manual_review=not agrees,
                ai_evidence_message_ids=ai.evidence_message_ids,
                rule_evidence_message_ids=(
                    rule_item.evidence_message_ids
                ),
            )
        )
    return tuple(rows)


def _wrong_consensus(record: StudyRunRecord) -> bool:
    answers = {
        vote.vote for vote in record.run.hidden_post_votes
    }
    return (
        len(answers) == 1
        and next(iter(answers)) != record.run.task.correct_answer
    )


def _final_answer(record: StudyRunRecord) -> str:
    counts = Counter(
        vote.vote for vote in record.run.hidden_post_votes
    )
    highest = max(counts.values())
    winners = sorted(
        answer
        for answer, count in counts.items()
        if count == highest
    )
    return winners[0] if len(winners) == 1 else "NO_MAJORITY"


def _consensus(record: StudyRunRecord):
    rule = rule_disclosure_evidence(record.run)
    new_by_message: dict[str, tuple[str, ...]] = {}
    for owner, fact in record.run.assignment.private_information.items():
        item = rule[fact]
        if item.evidence_message_ids:
            message_id = item.evidence_message_ids[0]
            prior = new_by_message.get(message_id, ())
            new_by_message[message_id] = (
                *prior,
                f"private-fact:{owner}",
            )
    return analyze_consensus_dynamics(
        messages=record.run.discussion_messages,
        possible_answers=record.run.task.possible_answers,
        correct_answer=record.run.task.correct_answer,
        new_rule_disclosures_by_message=new_by_message,
    )


def summarize_stability(
    records: tuple[StudyRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
) -> tuple[StabilitySummaryRow, ...]:
    audit_by_key = {
        audit.study_key.value: audit for audit in audits
    }
    groups: dict[
        tuple[int, StudyCondition],
        list[StudyRunRecord],
    ] = {}
    for record in records:
        groups.setdefault(
            (record.key.task_id, record.key.condition),
            [],
        ).append(record)

    summaries: list[StabilitySummaryRow] = []
    for (task_id, condition), group in sorted(
        groups.items(),
        key=lambda item: (
            item[0][0],
            0 if item[0][1] == "fixed" else 1,
        ),
    ):
        ordered = sorted(group, key=lambda item: item.key.repetition)
        group_audits = [
            audit_by_key[item.key.value] for item in ordered
        ]
        comparisons = [
            comparison
            for record, audit in zip(
                ordered,
                group_audits,
                strict=True,
            )
            for comparison in build_fact_comparisons(record, audit)
        ]
        consensus = [_consensus(item) for item in ordered]
        first_turns = [
            item.first_consensus_turn
            for item in consensus
            if item.first_consensus_turn is not None
        ]
        stable_turns = [
            item.first_stable_consensus_turn
            for item in consensus
            if item.first_stable_consensus_turn is not None
        ]
        ai_rates = [
            audit.disclosure_rate for audit in group_audits
        ]
        rule_rates = [
            record.run.metrics.private_fact_disclosure_rate
            for record in ordered
        ]
        summaries.append(
            StabilitySummaryRow(
                task_id=task_id,
                condition=condition,
                repetitions=len(ordered),
                ai_disclosure_mean=mean(ai_rates),
                ai_disclosure_std=(
                    pstdev(ai_rates) if len(ai_rates) > 1 else 0.0
                ),
                rule_disclosure_mean=mean(rule_rates),
                post_majority_correct_count=sum(
                    record.run.metrics.post_majority_correct
                    for record in ordered
                ),
                post_unanimous_count=sum(
                    record.run.metrics.post_unanimous
                    for record in ordered
                ),
                wrong_consensus_count=sum(
                    _wrong_consensus(record) for record in ordered
                ),
                stable_consensus_count=sum(
                    item.first_stable_consensus_turn is not None
                    for item in consensus
                ),
                mean_first_consensus_turn=(
                    mean(first_turns) if first_turns else None
                ),
                mean_first_stable_consensus_turn=(
                    mean(stable_turns) if stable_turns else None
                ),
                mean_consensus_flips=mean(
                    item.consensus_flips for item in consensus
                ),
                mean_post_stable_messages=mean(
                    item.post_stable_message_count
                    for item in consensus
                ),
                mean_repeated_confirmations=mean(
                    item.repeated_confirmation_count
                    for item in consensus
                ),
                ai_rule_agreement=(
                    sum(item.agrees for item in comparisons)
                    / len(comparisons)
                ),
                final_answer_distribution=dict(
                    sorted(
                        Counter(
                            _final_answer(record)
                            for record in ordered
                        ).items()
                    )
                ),
            )
        )
    return tuple(summaries)


def _write_csv(
    path: Path,
    rows: list[dict[str, object]],
    fieldnames: list[str],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_report(
    config: StabilityStudyConfig,
    summaries: tuple[StabilitySummaryRow, ...],
    comparisons: tuple[FactComparison, ...],
) -> str:
    lines = [
        "# HiddenBench AI Disclosure and Stability Study",
        "",
        (
            f"Design: {len(config.task_ids)} representative tasks, "
            f"2 speaking conditions, and {config.repetitions} "
            "repetitions per task-condition."
        ),
        "",
        (
            "Both conditions use 60 public speeches and exactly 15 speeches "
            "per agent. The dynamic selector makes zero LLM calls."
        ),
        "",
        "## Stability summary",
        "",
        (
            "| Task | Condition | N | AI disclosure mean | AI disclosure "
            "SD | Majority correct | Unanimous | wrong consensus | "
            "Stable consensus | AI-rule agreement |"
        ),
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row.task_id} | {row.condition} | {row.repetitions} | "
            f"{row.ai_disclosure_mean:.3f} | "
            f"{row.ai_disclosure_std:.3f} | "
            f"{row.post_majority_correct_count}/{row.repetitions} | "
            f"{row.post_unanimous_count}/{row.repetitions} | "
            f"{row.wrong_consensus_count}/{row.repetitions} | "
            f"{row.stable_consensus_count}/{row.repetitions} | "
            f"{row.ai_rule_agreement:.3f} |"
        )
    disagreements = sum(
        item.requires_manual_review for item in comparisons
    )
    by_task_condition = {
        (row.task_id, row.condition): row for row in summaries
    }
    lines.extend(
        [
            "",
            "## Paired fixed-minus-dynamic differences",
            "",
            (
                "| Task | Majority-correct rate difference | "
                "Wrong-consensus rate difference | "
                "AI disclosure mean difference |"
            ),
            "|---:|---:|---:|---:|",
        ]
    )
    paired_rows = 0
    for task_id in config.task_ids:
        fixed = by_task_condition.get((task_id, "fixed"))
        dynamic = by_task_condition.get((task_id, "dynamic"))
        if fixed is None or dynamic is None:
            continue
        paired_rows += 1
        lines.append(
            f"| {task_id} | "
            f"{fixed.post_majority_correct_count / fixed.repetitions - dynamic.post_majority_correct_count / dynamic.repetitions:+.3f} | "
            f"{fixed.wrong_consensus_count / fixed.repetitions - dynamic.wrong_consensus_count / dynamic.repetitions:+.3f} | "
            f"{fixed.ai_disclosure_mean - dynamic.ai_disclosure_mean:+.3f} |"
        )
    if paired_rows == 0:
        lines.append(
            "| — | No complete paired task in this smoke bundle | — | — |"
        )
    lines.extend(
        [
            "",
            "## AI-rule agreement",
            "",
            (
                f"The AI auditor and lexical-semantic-v2 disagreed on "
                f"{disagreements} fact-level judgments. Every disagreement "
                "is exported with both evidence trails for manual review."
            ),
            "",
            "## Interpretation boundary",
            "",
            (
                "This representative repeated study is descriptive. It "
                "does not establish general superiority of either speaking "
                "mechanism, and it is not a same-model reproduction of the "
                "original HiddenBench paper."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_stability_bundle(
    *,
    config: StabilityStudyConfig,
    records: tuple[StudyRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    gate: StabilityGate,
    output: Path,
) -> StabilityBundlePaths:
    if not gate.passed:
        raise ValueError("stability study gate did not pass")
    paths = StabilityBundlePaths(
        runs=output,
        trace=output.with_suffix(".trace.jsonl"),
        ai_disclosure=output.with_suffix(".ai-disclosure.jsonl"),
        disagreements=output.with_suffix(".disagreements.csv"),
        summary=output.with_suffix(".summary.csv"),
        report=output.with_suffix(".md"),
        gate=output.with_suffix(".gate.json"),
        manifest=output.with_suffix(".manifest.json"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered_records = tuple(
        sorted(
            records,
            key=lambda item: (
                config.task_ids.index(item.key.task_id),
                item.key.repetition,
                config.conditions.index(item.key.condition),
            ),
        )
    )
    audit_by_key = {
        audit.study_key.value: audit for audit in audits
    }
    ordered_audits = tuple(
        audit_by_key[record.key.value]
        for record in ordered_records
    )
    comparisons = tuple(
        item
        for record, audit in zip(
            ordered_records,
            ordered_audits,
            strict=True,
        )
        for item in build_fact_comparisons(record, audit)
    )
    summaries = summarize_stability(
        ordered_records,
        ordered_audits,
    )

    runs_payload = [
        record.model_dump(mode="json")
        for record in ordered_records
    ]
    audits_payload = [
        audit.model_dump(mode="json")
        for audit in ordered_audits
    ]
    trace_payload = [
        {
            "study_key": record.key.value,
            "message": message.model_dump(mode="json"),
        }
        for record in ordered_records
        for message in record.run.discussion_messages
    ] + [
        {
            "study_key": record.key.value,
            "selector_event": event.model_dump(mode="json"),
        }
        for record in ordered_records
        for event in record.selection_events
    ]
    gate_payload = gate.model_dump(mode="json")
    for payload in (
        runs_payload,
        audits_payload,
        trace_payload,
        gate_payload,
    ):
        _assert_no_secrets(payload)

    paths.runs.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in runs_payload
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths.trace.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in trace_payload
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths.ai_disclosure.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in audits_payload
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    disagreement_rows = [
        {
            **item.model_dump(mode="json"),
            "study_key": item.study_key.value,
            "ai_evidence_message_ids": "|".join(
                item.ai_evidence_message_ids
            ),
            "rule_evidence_message_ids": "|".join(
                item.rule_evidence_message_ids
            ),
        }
        for item in comparisons
        if item.requires_manual_review
    ]
    comparison_fields = [
        "study_key",
        "fact_id",
        "owner_agent_id",
        "fact",
        "ai_disclosed",
        "rule_disclosed",
        "agrees",
        "requires_manual_review",
        "ai_evidence_message_ids",
        "rule_evidence_message_ids",
    ]
    _write_csv(
        paths.disagreements,
        disagreement_rows,
        comparison_fields,
    )
    summary_rows = [
        {
            **item.model_dump(mode="json"),
            "final_answer_distribution": json.dumps(
                item.final_answer_distribution,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        for item in summaries
    ]
    summary_fields = list(
        StabilitySummaryRow.model_fields.keys()
    )
    _write_csv(paths.summary, summary_rows, summary_fields)
    paths.report.write_text(
        _build_report(config, summaries, comparisons),
        encoding="utf-8",
        newline="\n",
    )
    paths.gate.write_text(
        json.dumps(
            gate_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_sha256_manifest(
        (
            paths.runs,
            paths.trace,
            paths.ai_disclosure,
            paths.disagreements,
            paths.summary,
            paths.report,
            paths.gate,
        ),
        paths.manifest,
    )
    return paths
