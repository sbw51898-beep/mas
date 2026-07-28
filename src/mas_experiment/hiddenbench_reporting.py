from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from mas_experiment.audit import write_sha256_manifest
from mas_experiment.hiddenbench_domain import HiddenBenchRun, HiddenBenchVote


HIDDENBENCH_PAPER_URL = "https://arxiv.org/abs/2505.11556"
HIDDENBENCH_DATA_URL = (
    "https://huggingface.co/datasets/YuxuanLi1225/HiddenBench"
)
MAST_PAPER_URL = "https://arxiv.org/abs/2503.13657"
MAST_CODE_URL = (
    "https://github.com/multi-agent-systems-failure-taxonomy/MAST"
)
OFFICIAL_DATASET_SHA256 = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)
ReportKind = Literal["showcase", "screening"]

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|authorization|access[_-]?token|secret)",
    flags=re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~-]{12,}|"
    r"\bsk-[A-Za-z0-9_-]{16,})",
    flags=re.IGNORECASE,
)


class SecretLeakError(ValueError):
    """Raised before an export can persist secret-like material."""


def _assert_no_secrets(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                raise SecretLeakError(
                    f"sensitive field detected at {path}.{key_text}"
                )
            _assert_no_secrets(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_secrets(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        raise SecretLeakError(
            f"secret-like value detected at {path}"
        )


def _code_block(text: str, language: str = "text") -> str:
    longest = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def _render_vote(vote: HiddenBenchVote) -> str:
    return "\n".join(
        [
            f"### {vote.agent_id}",
            "",
            f"- Vote: `{vote.vote}`",
            f"- Rationale: {vote.rationale}",
            f"- API requests: "
            f"{vote.provider_metadata.get('api_requests', 0)}",
            f"- Repair requests: "
            f"{vote.provider_metadata.get('repair_requests', 0)}",
            "",
            "System prompt:",
            "",
            _code_block(vote.system_prompt),
            "",
            "User prompt:",
            "",
            _code_block(vote.user_prompt),
            "",
            "Raw response:",
            "",
            _code_block(vote.raw_text, "json"),
        ]
    )


def build_showcase_report(run: HiddenBenchRun) -> str:
    task = run.task
    lines = [
        f"# HiddenBench ID {task.id} 的 MAF 完整复现实验档案",
        "",
        "## 1. 公开依据与实验边界",
        "",
        (
            "- HiddenBench 论文：Yuxuan Li, Aoi Naito, Hirokazu "
            "Shirado, *Systematic Failures in Collective Reasoning "
            f"under Distributed Information in Multi-Agent LLMs*，"
            f"{HIDDENBENCH_PAPER_URL}"
        ),
        f"- 官方数据：{HIDDENBENCH_DATA_URL}",
        f"- MAST 论文：{MAST_PAPER_URL}",
        f"- MAST 代码与标签说明：{MAST_CODE_URL}",
        "",
        (
            "本档案是 Microsoft Agent Framework + DeepSeek 的单题、"
            "单种子模型迁移试跑，不等同于论文 65 题、多模型、每题"
            "多次 session 的总体实验，也不能据此宣称复现论文总体"
            "正确率。"
        ),
        "",
        "## 2. 题目与标准答案",
        "",
        f"- Task ID: `{task.id}`",
        f"- Name: `{task.name}`",
        f"- Correct answer: `{task.correct_answer}`",
        "",
        task.description,
        "",
        "### 共享信息",
        "",
    ]
    lines.extend(
        f"{index}. {item}"
        for index, item in enumerate(task.shared_information, start=1)
    )
    lines.extend(
        [
            "",
            "### 官方候选答案",
            "",
            *(
                f"- {answer}" for answer in task.possible_answers
            ),
            "",
            "## 3. 私有信息分配矩阵",
            "",
            "| Agent | 只分配给该 Agent 的信息 |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| {agent_id} | {_escape_table(fact)} |"
        for agent_id, fact in run.assignment.private_information.items()
    )
    lines.extend(
        [
            "",
            (
                "同一分配用于 Hidden pre 和 Hidden post。每名 Agent 的"
                " system prompt 只包含全部共享信息和本人的一条私有"
                "信息；Full Profile 才包含全部四条私有信息。"
            ),
            "",
            "## 4. 讨论前投票（Hidden Profile）",
            "",
        ]
    )
    for vote in run.hidden_pre_votes:
        lines.extend([_render_vote(vote), ""])

    lines.extend(["## 5. 15 轮完整公开讨论", ""])
    for round_index in range(1, 16):
        lines.extend([f"### Round {round_index:02d}", ""])
        for message in (
            item
            for item in run.discussion_messages
            if item.round_index == round_index
        ):
            visible_ids = ", ".join(message.visible_message_ids) or "(none)"
            lines.extend(
                [
                    (
                        f"#### Turn {message.turn_index:02d} · "
                        f"{message.agent_id}"
                    ),
                    "",
                    f"- Message ID: `{message.message_id}`",
                    f"- Visible message IDs: `{visible_ids}`",
                    "",
                    "System prompt:",
                    "",
                    _code_block(message.system_prompt),
                    "",
                    "User prompt:",
                    "",
                    _code_block(message.user_prompt),
                    "",
                    "Model output:",
                    "",
                    _code_block(message.content),
                    "",
                ]
            )

    lines.extend(["## 6. 讨论后投票（Hidden Profile）", ""])
    for vote in run.hidden_post_votes:
        lines.extend([_render_vote(vote), ""])

    lines.extend(["## 7. Full Profile 独立投票", ""])
    for vote in run.full_profile_votes:
        lines.extend([_render_vote(vote), ""])

    metrics = run.metrics
    lines.extend(
        [
            "## 8. 指标",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Y_pre_average | {metrics.y_pre_average:.3f} |",
            f"| Y_post_average | {metrics.y_post_average:.3f} |",
            f"| Y_full_average | {metrics.y_full_average:.3f} |",
            f"| integration_gain | {metrics.integration_gain:.3f} |",
            f"| full_profile_gap | {metrics.full_profile_gap:.3f} |",
            (
                "| private_fact_disclosure_rate | "
                f"{metrics.private_fact_disclosure_rate:.3f} |"
            ),
            (
                "| cross_agent_use_rate | "
                f"{metrics.cross_agent_use_rate:.3f} |"
            ),
            f"| post_majority_correct | {metrics.post_majority_correct} |",
            f"| post_unanimous | {metrics.post_unanimous} |",
            f"| consensus_round | {metrics.consensus_round} |",
            f"| API requests | {metrics.api_requests} |",
            f"| Repair requests | {metrics.repair_requests} |",
            "",
            (
                "`consensus_round` 留空，因为讨论发言不是结构化投票，"
                "不从自然语言强行推断共识轮次。"
            ),
            "",
            "## 9. MAST 自动候选（必须人工复核）",
            "",
            (
                "以下 FM-2.4、FM-2.5、FM-2.6 记录由透明词法规则生成，"
                "只是候选证据，不是已经确认的失败标签。"
            ),
            "",
        ]
    )
    if not run.mast_candidates:
        lines.append("- 未生成候选。")
    for index, candidate in enumerate(run.mast_candidates, start=1):
        lines.extend(
            [
                f"### Candidate {index}: {candidate.failure_mode}",
                "",
                f"- Agent: `{candidate.agent_id}`",
                f"- Owner: `{candidate.owner_agent_id}`",
                f"- Fact: {candidate.fact}",
                f"- Rule: `{candidate.rule_version}`",
                f"- Manual review required: "
                f"`{candidate.requires_manual_review}`",
                f"- Message IDs: "
                f"`{', '.join(candidate.evidence_message_ids)}`",
                "",
                *(
                    f"> {_escape_table(text)}"
                    for text in candidate.evidence_text
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## 10. 审计信息",
            "",
            f"- Run ID: `{run.run_id}`",
            f"- Configuration fingerprint: "
            f"`{run.configuration_fingerprint}`",
            f"- Code commit: `{run.code_commit}`",
            f"- Dataset SHA-256: `{OFFICIAL_DATASET_SHA256}`",
            f"- Provider metadata: "
            f"`{json.dumps(run.provider_metadata, ensure_ascii=False, sort_keys=True)}`",
            f"- Usage: "
            f"`{json.dumps(metrics.usage, ensure_ascii=False, sort_keys=True)}`",
            "",
        ]
    )
    return "\n".join(lines)


def build_screening_report(runs: Sequence[HiddenBenchRun]) -> str:
    if not runs:
        raise ValueError("screening report requires at least one run")
    lines = [
        "# HiddenBench MAF 十题筛选实验",
        "",
        (
            "论文公开参照为 65 题、多模型、多 session：Hidden Profile "
            "讨论后平均正确率 30.1%，Full Profile 80.7%。当前结果是"
            f" {len(runs)} 题、单种子、MAF + DeepSeek 的筛选实验，"
            "样本、模型和重复次数不同，不能做统计等价或显著性声明。"
        ),
        "",
        "| ID | Task | Y_pre | Y_post | Y_full | Gain | Full gap |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        metrics = run.metrics
        lines.append(
            f"| {run.task.id} | {_escape_table(run.task.name)} | "
            f"{metrics.y_pre_average:.3f} | "
            f"{metrics.y_post_average:.3f} | "
            f"{metrics.y_full_average:.3f} | "
            f"{metrics.integration_gain:.3f} | "
            f"{metrics.full_profile_gap:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 均值",
            "",
            f"- Y_pre_average: "
            f"{mean(run.metrics.y_pre_average for run in runs):.3f}",
            f"- Y_post_average: "
            f"{mean(run.metrics.y_post_average for run in runs):.3f}",
            f"- Y_full_average: "
            f"{mean(run.metrics.y_full_average for run in runs):.3f}",
            f"- Integration gain: "
            f"{mean(run.metrics.integration_gain for run in runs):.3f}",
            f"- Full profile gap: "
            f"{mean(run.metrics.full_profile_gap for run in runs):.3f}",
            f"- Total API requests: "
            f"{sum(run.metrics.api_requests for run in runs)}",
            f"- Total repair requests: "
            f"{sum(run.metrics.repair_requests for run in runs)}",
            "",
            "## 来源",
            "",
            f"- HiddenBench: {HIDDENBENCH_PAPER_URL}",
            f"- Official dataset: {HIDDENBENCH_DATA_URL}",
            f"- MAST: {MAST_PAPER_URL}",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        text,
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def write_hiddenbench_jsonl(
    runs: Sequence[HiddenBenchRun],
    destination: Path,
) -> Path:
    payload = [run.model_dump(mode="json") for run in runs]
    _assert_no_secrets(payload)
    serialized = "\n".join(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in payload
    )
    _atomic_write_text(destination, f"{serialized}\n")
    return destination


def write_hiddenbench_bundle(
    runs: Sequence[HiddenBenchRun],
    output: Path,
    *,
    report_kind: ReportKind,
) -> tuple[Path, Path, Path]:
    if not runs:
        raise ValueError("HiddenBench bundle requires at least one run")
    payload = [run.model_dump(mode="json") for run in runs]
    _assert_no_secrets(payload)
    report = (
        build_showcase_report(runs[0])
        if report_kind == "showcase"
        else build_screening_report(runs)
    )
    _assert_no_secrets(report)

    report_path = output.with_suffix(".md")
    manifest_path = output.with_suffix(".manifest.json")
    write_hiddenbench_jsonl(runs, output)
    _atomic_write_text(report_path, f"{report.rstrip()}\n")
    write_sha256_manifest(
        (output, report_path),
        manifest_path,
    )
    return output, report_path, manifest_path
