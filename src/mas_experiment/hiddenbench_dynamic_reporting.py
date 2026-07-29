from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from mas_experiment.audit import write_sha256_manifest
from mas_experiment.hiddenbench_domain import HiddenBenchRun
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicBundlePaths,
    DynamicHiddenBenchRun,
    PilotGate,
)
from mas_experiment.hiddenbench_reporting import _assert_no_secrets


def _wrong_consensus(run: HiddenBenchRun) -> bool:
    votes = {vote.vote for vote in run.hidden_post_votes}
    return len(votes) == 1 and next(iter(votes)) != run.task.correct_answer


def _usage(run: HiddenBenchRun, key: str) -> int | float:
    return run.metrics.usage.get(key, 0)


def build_paired_dynamic_report(
    baseline_runs: dict[int, HiddenBenchRun],
    dynamic_runs: tuple[DynamicHiddenBenchRun, ...],
) -> str:
    lines = [
        "# HiddenBench 预算匹配动态发言三题试验",
        "",
        "本试验只改变发言顺序。固定轮转与动态机制均为每个 Agent 15 次、"
        "每题共 60 次公开发言；选择器不调用 LLM。",
        "",
        "选择器 LLM 调用：0",
        "",
        "Token 预算并未被强制设为相等，因此下表单独报告 Token 用量，"
        "不能把 Token 差异描述为已经控制。",
        "",
        "| ID | 条件 | Y_pre | Y_post | Gain | 多数正确 | 一致 | 错误共识 | 披露率 | 跨Agent利用率 | 输入Token | 输出Token |",
        "|---:|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|",
    ]
    dynamic_by_id = {item.run.task.id: item.run for item in dynamic_runs}
    for task_id in sorted(dynamic_by_id):
        for label, run in (
            ("固定轮转", baseline_runs[task_id]),
            ("动态顺序", dynamic_by_id[task_id]),
        ):
            metrics = run.metrics
            lines.append(
                f"| {task_id} | {label} | {metrics.y_pre_average:.3f} | "
                f"{metrics.y_post_average:.3f} | "
                f"{metrics.integration_gain:.3f} | "
                f"{metrics.post_majority_correct} | "
                f"{metrics.post_unanimous} | {_wrong_consensus(run)} | "
                f"{metrics.private_fact_disclosure_rate:.3f} | "
                f"{metrics.cross_agent_use_rate:.3f} | "
                f"{_usage(run, 'input_token_count')} | "
                f"{_usage(run, 'output_token_count')} |"
            )
        counts = Counter(
            message.agent_id
            for message in dynamic_by_id[task_id].discussion_messages
        )
        lines.extend(
            [
                "",
                f"## ID {task_id}",
                "",
                "- 动态发言次数：" + ", ".join(
                    f"{agent_id}={counts[agent_id]}"
                    for agent_id in sorted(counts)
                ),
                "- 人工复核状态：pending",
                "- 待复核分类：信息未披露、信息被忽略、正确证据被错误解释。",
                "",
            ]
        )
    lines.extend(
        [
            "## 解释边界",
            "",
            "- 三题是工程试验，不作显著性或优越性声明。",
            "- DeepSeek 模型名是服务端别名，相同名称不能证明底层权重快照完全相同。",
            "- 自动 MAST 候选只用于筛查，动态对话仍需人工逐发言编码。",
            "",
        ]
    )
    return "\n".join(lines)


def write_dynamic_pilot_bundle(
    *,
    baseline_runs: dict[int, HiddenBenchRun],
    dynamic_runs: tuple[DynamicHiddenBenchRun, ...],
    gate: PilotGate,
    output: Path,
) -> DynamicBundlePaths:
    if not gate.passed:
        raise ValueError("dynamic pilot gate did not pass")
    paths = DynamicBundlePaths(
        runs=output,
        trace=output.with_suffix(".trace.jsonl"),
        report=output.with_suffix(".md"),
        gate=output.with_suffix(".gate.json"),
        manifest=output.with_suffix(".manifest.json"),
    )
    paths.runs.parent.mkdir(parents=True, exist_ok=True)
    runs_payload = [
        item.model_dump(mode="json") for item in dynamic_runs
    ]
    trace_payload = [
        {
            "dynamic_run_id": item.run.run_id,
            **event.model_dump(mode="json"),
        }
        for item in dynamic_runs
        for event in item.selection_events
    ]
    gate_payload = gate.model_dump(mode="json")
    _assert_no_secrets(runs_payload)
    _assert_no_secrets(trace_payload)
    _assert_no_secrets(gate_payload)
    paths.runs.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in runs_payload
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths.trace.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in trace_payload
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths.report.write_text(
        build_paired_dynamic_report(baseline_runs, dynamic_runs),
        encoding="utf-8",
        newline="\n",
    )
    paths.gate.write_text(
        json.dumps(gate_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_sha256_manifest(
        (paths.runs, paths.trace, paths.report, paths.gate),
        paths.manifest,
    )
    return paths
