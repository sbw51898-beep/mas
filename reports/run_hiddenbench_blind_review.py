from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from mas_experiment.audit import write_sha256_manifest
from mas_experiment.hiddenbench_ai_disclosure import DisclosureAudit
from mas_experiment.hiddenbench_blind_review import (
    BlindReviewCase,
    BlindReviewMessage,
    ReviewJudgment,
    append_artifact_label,
    build_blind_queue_row,
    compute_weighted_review_metrics,
    make_blind_id,
    parse_human_disclosed,
    select_blind_review_sample,
    validate_review_judgment_evidence,
)
from mas_experiment.hiddenbench_stability_domain import StudyRunRecord
from mas_experiment.hiddenbench_stability_reporting import (
    build_fact_comparisons,
)
from mas_experiment.maf_adapter import MAFPromptProvider
from mas_experiment.providers import DeepSeekSettings


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"
RUNS_PATH = ARTIFACTS / "hiddenbench-stability-20260729.jsonl"
AUDITS_PATH = (
    ARTIFACTS / "hiddenbench-stability-20260729.ai-disclosure.jsonl"
)
PREFIX = ARTIFACTS / "hiddenbench-stability-20260729.blind-review"
QUEUE_CSV = append_artifact_label(PREFIX, "queue.csv")
SELECTED_JSONL = append_artifact_label(PREFIX, "selected.jsonl")
JUDGMENTS_JSONL = append_artifact_label(PREFIX, "judgments.jsonl")
RAW_JSONL = append_artifact_label(PREFIX, "raw.jsonl")
SUMMARY_JSON = append_artifact_label(PREFIX, "summary.json")
MANIFEST_JSON = append_artifact_label(PREFIX, "manifest.json")
REPORT_MD = REPORTS / "HiddenBench_确认性盲审分析_2026-07-30.md"
SEED = 20260730
AGREEMENT_SAMPLE_PER_AI_LABEL = 30
BATCH_SIZE = 6
MAX_CONCURRENCY = 4
REVIEWER_ID = "deepseek-v4-flash-blind-readjudication-v2"


def _load_jsonl(path: Path, model: type[Any]) -> tuple[Any, ...]:
    return tuple(
        model.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _build_population() -> tuple[BlindReviewCase, ...]:
    records = _load_jsonl(RUNS_PATH, StudyRunRecord)
    audits = _load_jsonl(AUDITS_PATH, DisclosureAudit)
    audit_by_key = {item.study_key.value: item for item in audits}
    population: list[BlindReviewCase] = []
    for record in records:
        audit = audit_by_key[record.key.value]
        comparisons = build_fact_comparisons(record, audit)
        by_fact = {item.fact_id: item for item in comparisons}
        for owner_agent_id, fact in (
            record.run.assignment.private_information.items()
        ):
            fact_id = f"private-fact:{owner_agent_id}"
            comparison = by_fact[fact_id]
            owner_messages = tuple(
                BlindReviewMessage(
                    message_id=message.message_id,
                    turn_index=message.turn_index,
                    content=message.content,
                )
                for message in record.run.discussion_messages
                if message.agent_id == owner_agent_id
            )
            population.append(
                BlindReviewCase(
                    blind_id=make_blind_id(
                        seed=SEED,
                        study_key=record.key.value,
                        fact_id=fact_id,
                    ),
                    study_key=record.key.value,
                    task_id=record.key.task_id,
                    condition=record.key.condition,
                    fact_id=fact_id,
                    owner_agent_id=owner_agent_id,
                    fact=fact,
                    owner_messages=owner_messages,
                    ai_disclosed=comparison.ai_disclosed,
                    rule_disclosed=comparison.rule_disclosed,
                )
            )
    if len(population) != 320:
        raise ValueError(f"expected 320 cases, found {len(population)}")
    return tuple(population)


def _write_queue(selected: tuple[BlindReviewCase, ...]) -> None:
    with QUEUE_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "blind_id",
                "fact",
                "owner_agent_id",
                "owner_messages_json",
                "human_disclosed",
                "human_evidence_message_ids",
                "human_evidence_quote",
                "human_reason",
                "human_reviewer_id",
            ),
        )
        writer.writeheader()
        for item in selected:
            writer.writerow(build_blind_queue_row(item))
    SELECTED_JSONL.write_text(
        "\n".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
            for item in selected
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _review_prompt(cases: tuple[BlindReviewCase, ...]) -> str:
    payload = [item.blind_payload() for item in cases]
    shape = {
        "cases": [
            {
                "blind_id": "BR-...",
                "disclosed": True,
                "evidence_message_ids": ["message-id"],
                "evidence_quote": "exact substring",
                "reason": "short reason",
                "confidence": 0.95,
            }
        ]
    }
    return (
        "Independently judge whether each listed private information package "
        "was disclosed by its owner in the owner's public messages. You are "
        "blind to all earlier labels.\n\n"
        "Rules:\n"
        "1. Count disclosed only if the owner states the fact or a faithful "
        "paraphrase preserving the decision-relevant claim.\n"
        "2. Do not count a polarity reversal, contradiction, mere topic "
        "mention, or materially weakened claim.\n"
        "3. A partial statement counts only if it preserves the part needed "
        "for the decision.\n"
        "4. Do not require every source, timing, cause, or supporting detail "
        "when the core decision-relevant state is preserved. For example, "
        "'walking trails are closed' preserves a longer fact that also gives "
        "the closure date and fallen-tree cause; 'confirmed toxin "
        "contamination at Alpha' preserves a longer fact that also gives the "
        "ventilation pathway and test source; and 'confirmed safe inspection' "
        "preserves detailed safe-water, backup-light, and no-contamination "
        "findings. In contrast, a generic 'ventilation issue' does not "
        "preserve toxin contamination, and generic 'power issues' may "
        "materially weaken a fact that the station has no power.\n"
        "5. For a dense multi-item package, count a partial disclosure only "
        "when the stated subset is sufficient to support the owner's task "
        "choice; do not require a verbatim inventory.\n"
        "6. For disclosed=true, cite owner message IDs and copy one exact "
        "substring from a cited message.\n"
        "7. For disclosed=false, return an empty ID list and empty quote.\n"
        "8. Judge every case exactly once. Do not infer missing content.\n\n"
        f"CASES:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Return strict JSON only in this shape:\n"
        f"{json.dumps(shape, ensure_ascii=False)}"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("review response has no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("review response must be an object")
    return value


def _parse_batch(
    cases: tuple[BlindReviewCase, ...],
    text: str,
) -> tuple[ReviewJudgment, ...]:
    payload = _parse_json_object(text)
    if set(payload) != {"cases"} or not isinstance(payload["cases"], list):
        raise ValueError("review response must contain only a cases list")
    judgments = tuple(
        ReviewJudgment.model_validate(
            {**item, "reviewer_id": REVIEWER_ID}
        )
        for item in payload["cases"]
    )
    by_id = {item.blind_id: item for item in judgments}
    expected = {item.blind_id for item in cases}
    if len(by_id) != len(judgments) or set(by_id) != expected:
        raise ValueError("review response case IDs are incomplete or duplicated")
    for case in cases:
        validate_review_judgment_evidence(case, by_id[case.blind_id])
    return tuple(by_id[item.blind_id] for item in cases)


def _load_human_queue(
    selected: tuple[BlindReviewCase, ...],
) -> tuple[ReviewJudgment, ...]:
    case_by_id = {item.blind_id: item for item in selected}
    with QUEUE_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(selected):
        raise ValueError(
            f"human queue has {len(rows)} rows; expected {len(selected)}"
        )
    judgments: list[ReviewJudgment] = []
    for row in rows:
        blind_id = row["blind_id"].strip()
        if blind_id not in case_by_id:
            raise ValueError(f"unknown human queue blind ID: {blind_id}")
        reviewer_id = row["human_reviewer_id"].strip()
        if not reviewer_id:
            raise ValueError(f"{blind_id} is missing human_reviewer_id")
        judgment = ReviewJudgment(
            blind_id=blind_id,
            disclosed=parse_human_disclosed(row["human_disclosed"]),
            evidence_message_ids=tuple(
                item.strip()
                for item in row[
                    "human_evidence_message_ids"
                ].split("|")
                if item.strip()
            ),
            evidence_quote=row["human_evidence_quote"],
            reason=row["human_reason"],
            reviewer_id=reviewer_id,
        )
        validate_review_judgment_evidence(case_by_id[blind_id], judgment)
        judgments.append(judgment)
    if len({item.blind_id for item in judgments}) != len(selected):
        raise ValueError("human queue contains duplicate or missing blind IDs")
    return tuple(judgments)


async def _review_batch(
    provider: MAFPromptProvider,
    cases: tuple[BlindReviewCase, ...],
    semaphore: asyncio.Semaphore,
) -> tuple[tuple[ReviewJudgment, ...], dict[str, Any]]:
    prompt = _review_prompt(cases)
    async with semaphore:
        completion = await provider.complete(
            agent_id="blind-disclosure-reviewer",
            system_prompt=(
                "You are a strict independent evidence reviewer. Return JSON "
                "only, use only owner-authored evidence, and never invent a "
                "quote."
            ),
            user_prompt=prompt,
            seed=SEED,
            json_response=True,
        )
    try:
        judgments = _parse_batch(cases, completion.text)
        repair_metadata = None
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        async with semaphore:
            repair = await provider.complete(
                agent_id="blind-disclosure-reviewer",
                system_prompt=(
                    "Repair a blinded evidence review. Return strict JSON only."
                ),
                user_prompt=(
                    f"{prompt}\n\nThe previous response failed validation: "
                    f"{error}\nReturn a corrected complete object."
                ),
                seed=SEED + 1,
                json_response=True,
            )
        judgments = _parse_batch(cases, repair.text)
        repair_metadata = repair.provider_metadata
    return judgments, {
        "blind_ids": [item.blind_id for item in cases],
        "provider_metadata": completion.provider_metadata,
        "repair_provider_metadata": repair_metadata,
    }


async def _adjudicate(
    selected: tuple[BlindReviewCase, ...],
) -> tuple[tuple[ReviewJudgment, ...], tuple[dict[str, Any], ...]]:
    provider = MAFPromptProvider(DeepSeekSettings.from_env())
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    batches = tuple(
        selected[index : index + BATCH_SIZE]
        for index in range(0, len(selected), BATCH_SIZE)
    )
    results = await asyncio.gather(
        *(
            _review_batch(provider, batch, semaphore)
            for batch in batches
        )
    )
    judgments = tuple(
        item
        for batch, _ in results
        for item in batch
    )
    raw = tuple(metadata for _, metadata in results)
    return judgments, raw


def _write_outputs(
    population: tuple[BlindReviewCase, ...],
    selected: tuple[BlindReviewCase, ...],
    judgments: tuple[ReviewJudgment, ...],
    raw: tuple[dict[str, Any], ...],
    *,
    status: str,
    reviewer_id: str,
    human_signoff_required: bool,
) -> None:
    metrics = compute_weighted_review_metrics(population, judgments)
    by_id = {item.blind_id: item for item in population}
    reviewed_rows = []
    for judgment in judgments:
        case = by_id[judgment.blind_id]
        reviewed_rows.append(
            {
                **judgment.model_dump(mode="json"),
                "study_key": case.study_key,
                "task_id": case.task_id,
                "condition": case.condition,
                "fact_id": case.fact_id,
                "fact": case.fact,
                "ai_disclosed": case.ai_disclosed,
                "rule_disclosed": case.rule_disclosed,
                "ai_rule_agrees": (
                    case.ai_disclosed == case.rule_disclosed
                ),
            }
        )
    JUDGMENTS_JSONL.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in reviewed_rows
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    RAW_JSONL.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in raw
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    disagreement_rows = [
        row for row in reviewed_rows if not row["ai_rule_agrees"]
    ]
    agreement_rows = [
        row for row in reviewed_rows if row["ai_rule_agrees"]
    ]
    summary = {
        "status": status,
        "reviewer_id": reviewer_id,
        "sampling_seed": SEED,
        "population_size": len(population),
        "ai_rule_disagreements_reviewed": len(disagreement_rows),
        "agreement_sample_reviewed": len(agreement_rows),
        "agreement_sample_by_ai_label": dict(
            Counter(
                "disclosed" if row["ai_disclosed"] else "undisclosed"
                for row in agreement_rows
            )
        ),
        "reviewed_by_task_condition": dict(
            Counter(
                f"task-{row['task_id']}:{row['condition']}"
                for row in reviewed_rows
            )
        ),
        "metrics": metrics.model_dump(mode="json"),
        "unweighted_review_counts": {
            "ai_matches_reviewer": sum(
                row["ai_disclosed"] == row["disclosed"]
                for row in reviewed_rows
            ),
            "rule_matches_reviewer": sum(
                row["rule_disclosed"] == row["disclosed"]
                for row in reviewed_rows
            ),
            "reviewed": len(reviewed_rows),
        },
        "human_signoff_required": human_signoff_required,
        "human_queue": str(QUEUE_CSV.relative_to(ROOT)),
    }
    SUMMARY_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_markdown(summary)
    write_sha256_manifest(
        (
            QUEUE_CSV,
            SELECTED_JSONL,
            JUDGMENTS_JSONL,
            RAW_JSONL,
            SUMMARY_JSON,
            REPORT_MD,
        ),
        MANIFEST_JSON,
    )


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _write_markdown(summary: dict[str, Any]) -> None:
    metrics = summary["metrics"]
    REPORT_MD.write_text(
        "\n".join(
            (
                (
                    "# HiddenBench 披露判断确认性盲审"
                    if not summary["human_signoff_required"]
                    else "# HiddenBench 披露判断确认性盲审（模型辅助预审）"
                ),
                "",
                "## 审计范围",
                "",
                f"- 总体：{summary['population_size']} 项 Agent 级信息包判断。",
                "- 全量复核：84 项 AI—透明规则分歧。",
                "- 分层抽样：其余 236 项一致判断中，按 AI 已披露/未披露、"
                "任务和机制分层各抽 30 项，共 60 项。",
                f"- 盲审总数：{metrics['reviewed_size']} 项；抽样种子：{SEED}。",
                "",
                "## 加权结果",
                "",
                f"- 独立复核与 AI 一致率：{_pct(metrics['ai_human_agreement'])}",
                f"- AI 精确率：{_pct(metrics['ai_precision'])}",
                f"- AI 召回率：{_pct(metrics['ai_recall'])}",
                f"- 修订后的总体披露率：{_pct(metrics['revised_disclosure_rate'])}",
                "",
                "以上指标对84项分歧赋权1；对一致样本按其所在"
                "AI标签×任务×机制层的总体数/样本数加权，估计范围回到320项。",
                "",
                "## 审阅者与结论边界",
                "",
                (
                    "本轮标签来自已填写并通过证据校验的真人盲审签核表，"
                    "可将上述指标报告为人工一致率、AI精确率、召回率和"
                    "修订披露率。"
                    if not summary["human_signoff_required"]
                    else
                    "本轮逐项标签由独立盲化的 DeepSeek V4 Flash 复核生成，"
                    "没有向复核提示展示原 AI 标签或透明规则标签。它属于模型辅助"
                    "预审，不是真人人工金标准，因此不能在对外材料中写成“人工一致率”。"
                    "已同时生成不含既有标签的人工签核表；真人完成或修改该表后，"
                    "运行 --from-human-queue 即可使用相同加权公式重算最终人工指标。"
                ),
                "",
                "## 复核入口",
                "",
                f"- 盲化人工签核表：`{QUEUE_CSV.relative_to(ROOT)}`",
                f"- 模型辅助逐项判断：`{JUDGMENTS_JSONL.relative_to(ROOT)}`",
                f"- 加权摘要：`{SUMMARY_JSON.relative_to(ROOT)}`",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="only create the blinded queue and selected-case snapshot",
    )
    parser.add_argument(
        "--from-human-queue",
        action="store_true",
        help="validate a completed human queue and recompute final metrics",
    )
    args = parser.parse_args()
    population = _build_population()
    selected = select_blind_review_sample(
        population,
        agreement_sample_per_ai_label=AGREEMENT_SAMPLE_PER_AI_LABEL,
        seed=SEED,
    )
    if args.from_human_queue:
        judgments = _load_human_queue(selected)
        reviewer_ids = sorted({item.reviewer_id for item in judgments})
        _write_outputs(
            population,
            selected,
            judgments,
            (),
            status="completed_human_blind_review",
            reviewer_id="|".join(reviewer_ids),
            human_signoff_required=False,
        )
        print(SUMMARY_JSON.read_text(encoding="utf-8"))
        return

    _write_queue(selected)
    print(
        json.dumps(
            {
                "population": len(population),
                "selected": len(selected),
                "disagreements": sum(
                    item.ai_disclosed != item.rule_disclosed
                    for item in selected
                ),
                "queue": str(QUEUE_CSV),
            },
            ensure_ascii=False,
        )
    )
    if args.prepare_only:
        return
    judgments, raw = asyncio.run(_adjudicate(selected))
    _write_outputs(
        population,
        selected,
        judgments,
        raw,
        status="model_assisted_blind_review_not_human_ground_truth",
        reviewer_id=REVIEWER_ID,
        human_signoff_required=True,
    )
    print(SUMMARY_JSON.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
