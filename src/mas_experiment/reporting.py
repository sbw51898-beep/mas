from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from mas_experiment.datasets import FORMAL_PILOT_QUESTION


def _format_number(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "n/a"


def provider_request_totals(
    results: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    shared_metadata = [
        result.get("metadata", {})
        for result in results
        if "shared_initialization_api_requests"
        in result.get("metadata", {})
    ]
    if shared_metadata:
        api_requests = max(
            int(
                metadata.get(
                    "shared_initialization_api_requests",
                    0,
                )
                or 0
            )
            for metadata in shared_metadata
        )
        api_requests += sum(
            int(
                result.get("metadata", {}).get(
                    "mode_follow_up_api_requests",
                    0,
                )
                or 0
            )
            for result in results
        )
        repairs = max(
            int(
                metadata.get(
                    "shared_initialization_repair_requests",
                    0,
                )
                or 0
            )
            for metadata in shared_metadata
        )
        repairs += sum(
            int(
                result.get("metadata", {}).get(
                    "mode_follow_up_repair_requests",
                    0,
                )
                or 0
            )
            for result in results
        )
        return api_requests, repairs

    api_requests = 0
    repairs = 0
    for result in results:
        for response in result.get("responses", []):
            metadata = response.get("provider_metadata", {})
            api_requests += int(metadata.get("api_requests", 0) or 0)
            repairs += int(metadata.get("repair_requests", 0) or 0)
    return api_requests, repairs


def _private_disclosure(
    result: Mapping[str, Any],
) -> dict[str, bool]:
    text_by_agent: dict[str, str] = {}
    for message in result.get("messages", []):
        speaker = str(message.get("speaker", ""))
        text_by_agent[speaker] = (
            text_by_agent.get(speaker, "")
            + "\n"
            + str(message.get("content", ""))
        )
    disclosure: dict[str, bool] = {}
    for agent_id, private_context in (
        FORMAL_PILOT_QUESTION.private_contexts.items()
    ):
        values = re.findall(r"\b\d+\b", private_context)
        disclosure[agent_id] = all(
            value in text_by_agent.get(agent_id, "")
            for value in values
        )
    return disclosure


def build_pilot_report(
    results: Sequence[Mapping[str, Any]],
) -> str:
    api_requests, repairs = provider_request_totals(results)
    logical_slots = sum(
        len(result.get("responses", [])) for result in results
    )
    shared_ids = {
        str(
            result.get("metadata", {}).get(
                "initial_state_id",
                "",
            )
        )
        for result in results
        if result.get("metadata", {}).get("initial_state_id")
    }
    lines = [
        "# DeepSeek 多智能体正式试跑审计报告",
        "",
        "## 工程观察",
        "",
        f"- 模式记录数：{len(results)}",
        f"- 讨论阶段实际API请求：{api_requests}",
        f"- 逻辑响应位置：{logical_slots}",
        f"- 格式修复请求：{repairs}",
    ]
    if len(shared_ids) == 1:
        lines.append(
            f"- 共享初始化状态ID：{next(iter(shared_ids))}"
        )
    lines.extend(
        [
            "",
            "| 模式 | 有效响应 | pooled | majority | accuracy | "
        "majority_share | unanimity | wrong_consensus | "
        "JS分歧 | Brier |",
            "|---|---:|---|---|---:|---:|---|---|---:|---:|",
        ]
    )
    for result in results:
        metrics = result.get("metrics") or {}
        lines.append(
            "| "
            f"{result.get('mode', 'unknown')} | "
            f"{len(result.get('responses', []))} | "
            f"{metrics.get('pooled_answer', 'n/a')} | "
            f"{metrics.get('majority_answer', 'n/a')} | "
            f"{_format_number(metrics.get('accuracy'))} | "
            f"{_format_number(metrics.get('majority_share'))} | "
            f"{metrics.get('unanimity', 'n/a')} | "
            f"{metrics.get('wrong_consensus', 'n/a')} | "
            f"{_format_number(metrics.get('js_disagreement'))} | "
            f"{_format_number(metrics.get('group_brier'))} |"
        )

    lines.extend(["", "### 信念代理量", ""])
    for result in results:
        metrics = result.get("metrics") or {}
        runtime = metrics.get("runtime_belief_state") or {}
        evaluation = metrics.get("evaluation_belief_state") or {}
        lines.append(
            f"- `{result.get('mode', 'unknown')}`："
            f"运行时 mean_b={_format_number(runtime.get('mean_b'))}, "
            f"R={_format_number(runtime.get('order_parameter_r'))}, "
            f"T_proxy={_format_number(runtime.get('temperature_proxy'))}, "
            f"H_proxy={_format_number(runtime.get('entropy_proxy'))}, "
            f"F_proxy={_format_number(runtime.get('disorder_proxy'))}；"
            f"评估用 mean_b={_format_number(evaluation.get('mean_b'))}。"
        )

    lines.extend(["", "## MAST候选信号审计", ""])
    for result in results:
        disclosure = _private_disclosure(result)
        lines.append(
            f"### {result.get('mode', 'unknown')}"
        )
        lines.append(
            "- FM-2.4 信息隐瞒候选："
            + json.dumps(disclosure, ensure_ascii=False, sort_keys=True)
            + "。这是数值字符串检查，需要人工复核语义。"
        )
        lines.append(
            "- FM-2.5 输入忽视候选：需人工核查后续推理是否真正使用了"
            "其他专家公开的数据，不能仅凭关键词自动定性。"
        )
        lines.append(
            "- FM-2.6 推理-行为不匹配候选：结构化答案与最大概率项已由"
            "程序强制一致；推理文本与答案的语义一致性仍需人工复核。"
        )
        if result.get("errors"):
            lines.append(
                "- 工程错误：" + "; ".join(map(str, result["errors"]))
            )
        lines.append("")

    lines.extend(
        [
            "## 研究结论限制",
            "",
            "本报告只记录一道题的一次工程试跑。不能据此认定任何发言机制"
            "更优，不能据此建立共识与正确性的相关关系，也不能声称复现了"
            "贺文结果或证明这些代理量具有真实物理含义。",
            "",
        ]
    )
    return "\n".join(lines)
