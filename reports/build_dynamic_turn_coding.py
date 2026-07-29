from __future__ import annotations

import csv
import json
from pathlib import Path

from mas_experiment.audit import write_sha256_manifest


ROOT = Path(__file__).resolve().parents[1]
RUNS_PATH = ROOT / "artifacts" / "hiddenbench-dynamic-pilot-20260729.jsonl"
CSV_PATH = (
    ROOT
    / "reports"
    / "HiddenBench_动态机制逐发言编码_ID1_ID5_ID7_2026-07-29.csv"
)
MD_PATH = (
    ROOT
    / "reports"
    / "HiddenBench_动态机制逐发言编码_ID1_ID5_ID7_2026-07-29.md"
)
PAIRED_REPORT = (
    ROOT / "artifacts" / "hiddenbench-dynamic-pilot-20260729.md"
)
MANIFEST_PATH = (
    ROOT / "artifacts" / "hiddenbench-dynamic-pilot-20260729.manifest.json"
)


def classify(task_id: int, turn: int) -> tuple[int, int, int, str, str]:
    if task_id == 1:
        if turn == 0:
            return (
                1,
                0,
                1,
                "轻微信息缺口 + 局部解释矛盾",
                "火灾被说成阻断全部交通，但同时判断西城桥可通；结论正确，定位仍含歧义。",
            )
        if turn == 1:
            return (
                1,
                0,
                2,
                "正确证据被错误解释",
                "agent-a 披露补给车卡在东城隧道，却将其弱化为“有风险但仍可通行”，短暂建议东城。",
            )
        if turn == 2:
            return (
                1,
                0,
                0,
                "信息逐步披露",
                "agent-c 披露步道关闭并选择西城；此时只剩北山泥石流尚未公开。",
            )
        if turn == 3:
            return (
                0,
                0,
                0,
                "关键事实完成汇总",
                "agent-d 披露北山泥石流；四名智能体的路线阻断信息已经进入公共对话。",
            )
        return (
            0,
            0,
            0,
            "正确证据被持续整合",
            "西城桥可通、东城隧道被堵和北山泥石流持续进入结论，没有再删除关键反证。",
        )
    if task_id == 5:
        if turn == 0:
            return (
                2,
                0,
                1,
                "信息未披露为主",
                "未披露 Stevens 募资前离任、酗酒及 Roberts 的关键优势；仍泛称 Stevens 募资经历最强。",
            )
        return (
            2,
            0,
            2,
            "信息未披露 + 正确证据被错误解释",
            "关键私有事实始终未进入公共讨论；把 Jones 参与董事会和资本项目反复改写成募资成功。",
        )
    if task_id == 7:
        if turn == 0:
            return (
                2,
                0,
                2,
                "信息未披露 + 选择性解释",
                "只突出 Cape 的 a、c、j，未汇总 Starlight 的分散优势，也未呈现 Cape 的失败项。",
            )
        if turn == 1:
            return (
                1,
                0,
                0,
                "关键反证已披露",
                "agent-b 明确指出 Cape 在 b、f、g、h 上失败，并提出 Starlight 的 i、j 优势和正确结论。",
            )
        if turn == 2:
            return (
                1,
                2,
                2,
                "信息被忽略 + 选择性解释",
                "紧接着忽略 Cape 的四项失败，重新宣称 Cape 满足关键指标；Starlight 其余优势仍未汇总。",
            )
        return (
            1,
            2,
            2,
            "信息被忽略 + 正确证据被错误解释",
            "第1轮已经披露的 Cape 失败项和 Starlight 正确建议被持续删除，所有智能体复读 Cape 结论。",
        )
    raise ValueError(f"unexpected task ID: {task_id}")


def main() -> None:
    runs = [
        json.loads(line)
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows = []
    for item in runs:
        run = item["run"]
        task_id = run["task"]["id"]
        for message in run["discussion_messages"]:
            missing, ignored, misread, primary, rationale = classify(
                task_id,
                message["turn_index"],
            )
            rows.append(
                {
                    "task_id": task_id,
                    "turn_index": message["turn_index"],
                    "reporting_block": message["round_index"],
                    "agent_id": message["agent_id"],
                    "information_not_disclosed": missing,
                    "information_ignored": ignored,
                    "evidence_misinterpreted": misread,
                    "primary_mechanism": primary,
                    "coding_rationale": rationale,
                    "message_id": message["message_id"],
                    "original_message": message["content"],
                }
            )
    assert len(rows) == 180
    assert {
        (row["task_id"], row["turn_index"]) for row in rows
    } == {(task_id, turn) for task_id in (1, 5, 7) for turn in range(60)}
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    text = """# HiddenBench 动态发言机制逐发言人工编码

编码对象：ID 1、5、7，共 180 次公开发言。严重度采用 `0/1/2`：
无可观察证据、局部或次要、清楚且实质影响结论。

## 结论

| ID | 固定轮转结果 | 动态结果 | 人工机制判断 |
|---:|---|---|---|
| 1 | 全体错误选择 East Town | 全体正确选择 West City | 前4次发言完成关键路线信息汇总；第1次短暂误读随后被纠正，错误共识被阻止。 |
| 5 | 全体错误选择 Stevens | 全体错误选择 Jones | 治理没有促成关键人物信息披露，只改变了错误答案；主因仍是信息未披露。 |
| 7 | 全体错误选择 Cape | 全体错误选择 Cape | agent-b 第2次发言给出正确反证，但紧接着被忽略；动态顺序没有阻止证据删除和模板化复读。 |

## 关键观察

- ID 1 表明动态顺序可能加快互补事实汇总，但单案例不能证明普遍有效。
- ID 5 表明同样的60次预算并不保证产生更多实质信息；重复发言可能只是重复错误锚点。
- ID 7 是典型的“披露不等于利用”：自动披露率为1，正确反证仍在后续被集体删除。
- 三题只支持描述性比较，不作显著性或优越性声明。

完整180行编码、原始消息和 message ID 见配套 CSV。
"""
    MD_PATH.write_text(text, encoding="utf-8", newline="\n")
    paired = PAIRED_REPORT.read_text(encoding="utf-8")
    findings = (
        "错误共识被阻止；前4次发言完成路线事实汇总，最终全体正确选择 West City。",
        "仍为错误共识，但答案由 Stevens 变为 Jones；关键人物信息继续未披露。",
        "错误共识未改变；agent-b 已给出正确反证，但后续被忽略并转回 Cape。",
    )
    for finding in findings:
        paired = paired.replace(
            "- 人工复核状态：pending",
            f"- 人工复核状态：completed\n- 人工结论：{finding}",
            1,
        )
    PAIRED_REPORT.write_text(paired, encoding="utf-8", newline="\n")
    artifact_base = ROOT / "artifacts" / "hiddenbench-dynamic-pilot-20260729"
    write_sha256_manifest(
        (
            artifact_base.with_suffix(".jsonl"),
            artifact_base.with_suffix(".trace.jsonl"),
            PAIRED_REPORT,
            artifact_base.with_suffix(".gate.json"),
            CSV_PATH,
            MD_PATH,
        ),
        MANIFEST_PATH,
    )
    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {MD_PATH}")
    print("Rows: 180")


if __name__ == "__main__":
    main()
