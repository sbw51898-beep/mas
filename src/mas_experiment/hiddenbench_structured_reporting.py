from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mas_experiment.hiddenbench_ai_disclosure import DisclosureAudit
from mas_experiment.hiddenbench_structured_protocol import (
    StructuredRunRecord,
    StructuredStudyConfig,
)
from mas_experiment.hiddenbench_structured_study import StructuredGate


class StructuredBundlePaths(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: Path
    audits: Path
    summary: Path
    report: Path
    gate: Path
    manifest: Path


def _disclosure_by_key(
    audits: tuple[DisclosureAudit, ...],
) -> dict[str, float]:
    return {
        audit.study_key.value: audit.disclosure_rate
        for audit in audits
    }


def _write_summary(
    path: Path,
    config: StructuredStudyConfig,
    records: tuple[StructuredRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
) -> None:
    disclosure = _disclosure_by_key(audits)
    rows = []
    for task_id in config.task_ids:
        task_records = [
            record
            for record in records
            if record.key.task_id == task_id
        ]
        disclosures = [
            disclosure[record.key.value]
            for record in task_records
            if record.key.value in disclosure
        ]
        correct = Counter(
            record.run.task.correct_answer
            for record in task_records
        )
        distribution = Counter()
        unanimous_wrong = 0
        for record in task_records:
            votes = [
                vote.vote
                for vote in record.run.hidden_post_votes
            ]
            distribution.update(votes)
            if (
                len(votes) == 4
                and len(set(votes)) == 1
                and votes[0] != record.run.task.correct_answer
            ):
                unanimous_wrong += 1
        rows.append(
            {
                "task_id": task_id,
                "condition": "structured",
                "repetitions": len(task_records),
                "ai_disclosure_mean": (
                    sum(disclosures) / len(disclosures)
                    if disclosures
                    else ""
                ),
                "post_majority_correct_count": sum(
                    1
                    for record in task_records
                    if all(
                        vote.vote == record.run.task.correct_answer
                        for vote in record.run.hidden_post_votes
                    )
                ),
                "post_unanimous_count": sum(
                    1
                    for record in task_records
                    if len(
                        {
                            vote.vote
                            for vote in record.run.hidden_post_votes
                        }
                    )
                    == 1
                ),
                "wrong_consensus_count": unanimous_wrong,
                "final_answer_distribution": json.dumps(
                    dict(distribution),
                    ensure_ascii=False,
                ),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_report_md(
    path: Path,
    config: StructuredStudyConfig,
    records: tuple[StructuredRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    gate: StructuredGate,
) -> None:
    disclosure = _disclosure_by_key(audits)
    lines = [
        "# HiddenBench Structured Protocol Study",
        "",
        f"- date: 2026-08-02",
        f"- model: {config.provider.model} "
        f"(temperature={config.provider.temperature}, "
        f"thinking={config.provider.thinking})",
        f"- tasks: {', '.join(str(task_id) for task_id in config.task_ids)}",
        f"- repetitions: {config.repetitions}",
        f"- records: {len(records)}",
        f"- audits: {len(audits)}",
        f"- gate passed: {gate.passed}",
        "",
        "## Per-task results",
        "",
        "| task | disclosure | post-correct | unanimous-wrong |",
        "|---|---|---|---|",
    ]
    for task_id in config.task_ids:
        task_records = [
            record
            for record in records
            if record.key.task_id == task_id
        ]
        disclosures = [
            disclosure[record.key.value]
            for record in task_records
            if record.key.value in disclosure
        ]
        correct = sum(
            1
            for record in task_records
            if all(
                vote.vote == record.run.task.correct_answer
                for vote in record.run.hidden_post_votes
            )
        )
        unanimous_wrong = sum(
            1
            for record in task_records
            if (
                len(
                    {
                        vote.vote
                        for vote in record.run.hidden_post_votes
                    }
                )
                == 1
                and record.run.hidden_post_votes[0].vote
                != record.run.task.correct_answer
            )
        )
        lines.append(
            f"| {task_id} | "
            f"{sum(disclosures) / len(disclosures):.1%} | "
            f"{correct}/10 | {unanimous_wrong}/10 |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(
    path: Path,
    config: StructuredStudyConfig,
    files: tuple[tuple[Path, str], ...],
) -> None:
    entries = []
    for file_path, description in files:
        if file_path.exists():
            payload = file_path.read_bytes()
            entries.append(
                {
                    "filename": file_path.name,
                    "description": description,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    manifest = {
        "configuration_version": config.configuration_version,
        "generated_at": "2026-08-02",
        "model": config.provider.model,
        "files": entries,
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_structured_bundle(
    *,
    config: StructuredStudyConfig,
    records: tuple[StructuredRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    gate: StructuredGate,
    output: Path,
) -> StructuredBundlePaths:
    audit_path = output.with_suffix(".ai-disclosure.jsonl")
    summary_path = output.with_suffix(".summary.csv")
    report_path = output.with_suffix(".md")
    gate_path = output.with_suffix(".gate.json")
    manifest_path = output.with_suffix(".manifest.json")
    _write_summary(summary_path, config, records, audits)
    _write_report_md(report_path, config, records, audits, gate)
    gate_path.write_text(
        gate.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    _write_manifest(
        manifest_path,
        config,
        (
            (output, "Structured protocol run records"),
            (audit_path, "AI disclosure audits"),
            (summary_path, "Per-task summary"),
            (report_path, "Markdown report"),
            (gate_path, "Integrity gate"),
        ),
    )
    return StructuredBundlePaths(
        runs=output,
        audits=audit_path,
        summary=summary_path,
        report=report_path,
        gate=gate_path,
        manifest=manifest_path,
    )
