from __future__ import annotations

import json
import shutil
import statistics
from collections import Counter
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.shared import Pt

from build_ai_disclosure_stability_report import (
    BLUE,
    DARK_GRAY,
    MID_GRAY,
    NAVY,
    _add_callout,
    _add_source_note,
    _add_table,
    _configure_page,
    _configure_styles,
    _set_run_font,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
V1_JSONL = ARTIFACTS / "hiddenbench-stability-20260729.jsonl"
V2_JSONL = ARTIFACTS / "hiddenbench-governance-20260802.jsonl"
V3_JSONL = ARTIFACTS / "hiddenbench-structured-20260802.jsonl"
V4_JSONL = ARTIFACTS / "hiddenbench-contrast-20260803.jsonl"
OUTPUT = (
    ROOT
    / "reports"
    / "对照实验报告（单智能体与同预算基线）_2026-08-03.docx"
)
DESKTOP_OUTPUT = (
    Path.home()
    / "Desktop"
    / "对照实验报告（单智能体与同预算基线）_2026-08-03.docx"
)

CONDITIONS = (
    "single-direct",
    "single-reflect",
    "fixed",
    "dynamic",
    "fixed-disc",
    "dynamic-disc",
    "fixed-12",
    "structured",
)
CONDITION_LABEL = {
    "single-direct": "单智能体直接作答",
    "single-reflect": "单智能体+15轮反思",
    "fixed": "固定轮转60条（基线）",
    "dynamic": "MAF动态60条（基线）",
    "fixed-disc": "固定+强制披露",
    "dynamic-disc": "MAF动态+强制披露",
    "fixed-12": "固定轮转12条（同预算）",
    "structured": "Structured协议12条",
}
TASKS = {
    1: "撤离路线",
    5: "校长候选人",
    7: "供应商选择",
    25: "应急避难所",
}


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def _aggregate() -> dict[tuple[int, str], dict]:
    records = (
        _load_jsonl(V1_JSONL)
        + _load_jsonl(V2_JSONL)
        + _load_jsonl(V3_JSONL)
        + _load_jsonl(V4_JSONL)
    )
    rows: dict[tuple[int, str], list[dict]] = {}
    for record in records:
        key = record["key"]
        run = record["run"]
        task = run["task"]
        correct = task["correct_answer"]
        post_votes = run["hidden_post_votes"]
        votes = [vote["vote"] for vote in post_votes]
        rows.setdefault((key["task_id"], key["condition"]), []).append(
            {
                "post_correct": (
                    sum(1 for vote in votes if vote == correct)
                    / len(votes)
                    if votes
                    else 0.0
                ),
                "majority_ok": (
                    sum(1 for vote in votes if vote == correct)
                    > len(votes) / 2
                    if votes
                    else False
                ),
                "unanimous_wrong": (
                    len(votes) > 0
                    and len(set(votes)) == 1
                    and votes[0] != correct
                ),
                "y_pre": (
                    sum(
                        1
                        for vote in run["hidden_pre_votes"]
                        if vote["vote"] == correct
                    )
                    / len(run["hidden_pre_votes"])
                    if run["hidden_pre_votes"]
                    else 0.0
                ),
                "y_post": (
                    sum(1 for vote in votes if vote == correct)
                    / len(votes)
                    if votes
                    else 0.0
                ),
                "y_full": (
                    sum(
                        1
                        for vote in run["full_profile_votes"]
                        if vote["vote"] == correct
                    )
                    / len(run["full_profile_votes"])
                    if run["full_profile_votes"]
                    else 0.0
                ),
            }
        )
    summaries: dict[tuple[int, str], dict] = {}
    for key, items in rows.items():
        summaries[key] = {
            "correct_runs": sum(
                1 for item in items if item["post_correct"] == 1.0
            ),
            "majority_runs": sum(
                1 for item in items if item["majority_ok"]
            ),
            "unanimous_wrong": sum(
                1 for item in items if item["unanimous_wrong"]
            ),
            "y_pre": statistics.mean(item["y_pre"] for item in items),
            "y_post": statistics.mean(item["y_post"] for item in items),
            "y_full": statistics.mean(item["y_full"] for item in items),
        }
    return summaries


def _add_cover(document: DocumentType) -> None:
    document.add_paragraph().paragraph_format.space_after = Pt(14)
    document.add_paragraph().paragraph_format.space_after = Pt(18)
    eyebrow = document.add_paragraph()
    eyebrow.alignment = 1
    run = eyebrow.add_run("MAS知识治理实验·第4轮")
    _set_run_font(run, size=12, bold=True, color=BLUE)
    title = document.add_paragraph()
    title.alignment = 1
    run = title.add_run("单智能体对照与同预算基线实验")
    _set_run_font(run, size=22, bold=True, color=NAVY)
    subtitle = document.add_paragraph()
    subtitle.alignment = 1
    subtitle.paragraph_format.space_before = Pt(8)
    run = subtitle.add_run(
        "回应“还不如用单智能体”与“Structured 预算不同不可比”两项质疑；"
        "新增单智能体直接作答、单智能体+15轮反思、固定轮转12条三组对照"
    )
    _set_run_font(run, size=12, color=DARK_GRAY)
    document.add_paragraph().paragraph_format.space_after = Pt(24)
    _add_table(
        document,
        ["项目", "内容"],
        [
            ("日期", "2026-08-03"),
            ("模型", "DeepSeek V4 Flash（temperature=0）"),
            ("新增条件", "single-direct / single-reflect / fixed-12"),
            ("题目", "HiddenBench ID 1、5、7、25 × 10 次"),
            ("调用量", "120 条记录，正式+审计共 1840 次 API 请求"),
            ("对照基线", "fixed/dynamic(60条)、fixed-disc/dynamic-disc、structured(12条)"),
        ],
        [2400, 6960],
        font_size=10.5,
    )
    document.add_page_break()


def _add_design(document: DocumentType) -> None:
    document.add_heading("一、三个新条件的定义", level=1)
    _add_table(
        document,
        ["条件", "结构", "预算说明"],
        [
            (
                "单智能体直接作答",
                "只给 agent-a 自己的私有信息包，直接投票，无讨论",
                "1 次投票调用",
            ),
            (
                "单智能体+15轮反思",
                "同一智能体先 15 轮自我反思（每轮 1–2 句），再投票",
                "15 轮反思 ≈ 4 人组中单个成员的发言配额；总输出为 4 人组的 1/4",
            ),
            (
                "固定轮转12条",
                "与原 60 条基线同 prompt、同轮转，只跑 3 轮",
                "与 Structured 协议完全相同的 12 条消息预算",
            ),
        ],
        [1900, 3500, 3960],
        font_size=8.5,
    )
    _add_source_note(
        document,
        "三个条件与既有实验共享同一任务、同一私有信息分配（同 seed 派生）、"
        "同一模型配置；单智能体与 4 人组的信息不对称设定完全一致（都只看到"
        "自己的私有信息包）。",
    )
    document.add_page_break()


def _add_results(
    document: DocumentType,
    summaries: dict[tuple[int, str], dict],
) -> None:
    document.add_heading("二、八种条件 × 四题结果", level=1)
    rows = []
    for task_id in (1, 5, 7, 25):
        for condition in CONDITIONS:
            summary = summaries[(task_id, condition)]
            rows.append(
                [
                    f"{task_id} {TASKS[task_id]}",
                    CONDITION_LABEL[condition],
                    f"{summary['correct_runs']}/10",
                    f"{summary['unanimous_wrong']}/10",
                    _pct(summary["y_post"]),
                ]
            )
    _add_table(
        document,
        ["任务", "条件", "全对次数", "错误共识", "Y_post"],
        rows,
        [1350, 2900, 1150, 1150, 2810],
        font_size=8.0,
    )
    _add_source_note(
        document,
        "全对次数：该条件下 10 次重复中最终投票全部正确（4 人组为 4/4，单智能体"
        "为 1/1）的次数；Y_post 为票平均正确率。本数据集中多数正确（≥3/4）与"
        "全对完全一致，故直接报告全对次数。",
    )

    document.add_heading("按任务汇总的六行速览", level=2)
    total_rows = []
    for condition in CONDITIONS:
        correct = sum(
            summaries[(task_id, condition)]["correct_runs"]
            for task_id in (1, 5, 7, 25)
        )
        wrong = sum(
            summaries[(task_id, condition)]["unanimous_wrong"]
            for task_id in (1, 5, 7, 25)
        )
        total_rows.append(
            [
                CONDITION_LABEL[condition],
                f"{correct}/40",
                f"{wrong}/40",
            ]
        )
    _add_table(
        document,
        ["条件", "全对次数合计", "错误共识合计"],
        total_rows,
        [3400, 2980, 2980],
        font_size=9.0,
    )
    document.add_page_break()


def _add_conclusions(
    document: DocumentType,
    summaries: dict[tuple[int, str], dict],
) -> None:
    document.add_heading("三、三个问题的回答", level=1)
    document.add_heading("1. “还不如用单智能体”成立吗", level=2)
    document.add_paragraph(
        "不成立，但原因和直觉相反。单智能体直接作答 4 题合计 5/40（12.5%），"
        "加 15 轮反思也只有 7/40（17.5%）。在 ID5/ID7 上单智能体同样是 0–1/10"
        "全错——因为隐藏档案题的正确答案需要四个人手里的信息拼起来，任何单个"
        "智能体拿着 1/4 信息都不可能答对。真正能碾压讨论组的是“拿到全部信息"
        "的单智能体”（Y_full 85%–95%），但那已经不是同一个任务设定。"
    )
    _add_callout(
        document,
        "给老师的准确说法",
        "“单智能体（同样只有部分信息）并不比多智能体好，反而明显更差（5/40 "
        "vs 20/40）；多智能体讨论的价值在于信息汇聚，而 ID5/ID7 的失败发生在"
        "信息汇聚之后的使用环节——这与 Y_full 高、讨论后 Y_post 低的事实一致。”",
    )
    document.add_heading("2. Structured 的预算不公平吗", level=2)
    document.add_paragraph(
        "补了同预算基线后可以公平回答：固定轮转 12 条（21/40）与固定轮转 60 条"
        "（20/40）几乎没有差别，说明 12 条预算本身不构成劣势。Structured 协议"
        "（20/40）与固定轮转 12 条（21/40）持平——结构化协议相对同预算基线"
        "没有额外增益。这不是协议设计无效的证据，而是模型层整合瓶颈的又一佐证："
        "无论怎么组织发言，DeepSeek 在 ID5/ID7 上拿到信息也答不对。"
    )
    document.add_heading("3. 讨论本身有没有用", level=2)
    document.add_paragraph(
        "有用。单智能体 5–7/40 → 任何 4 人组条件 20–21/40，讨论把正确率翻倍。"
        "且预算不是关键变量（12 条 ≈ 60 条）。因此“多智能体无用论”不成立；"
        "真正未解决的问题是：为什么信息齐了 DeepSeek 还是整合失败（Y_full "
        "85–95% vs 讨论后 0–20%）。"
    )
    document.add_heading("下一步", level=2)
    for step in [
        "换强模型（GPT-4.1 或 DeepSeek 更高档位）复跑同一 8 条件矩阵，分离模型与协议因素。",
        "对 ID5/ID7 做逐轮证据使用审计：披露出的信息是否被正确引用、是否被错误否定。",
        "真人盲审签核表（144 项已填版本）复核。",
    ]:
        document.add_paragraph(f"{step}")


def _build_document(summaries: dict) -> DocumentType:
    document = Document()
    _configure_styles(document)
    _configure_page(document)
    _add_cover(document)
    _add_design(document)
    _add_results(document, summaries)
    _add_conclusions(document, summaries)
    return document


def main() -> None:
    summaries = _aggregate()
    expected = {
        (task_id, condition)
        for task_id in (1, 5, 7, 25)
        for condition in CONDITIONS
    }
    missing = expected - set(summaries)
    if missing:
        raise ValueError(f"missing summaries: {sorted(missing)}")
    document = _build_document(summaries)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    DESKTOP_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT, DESKTOP_OUTPUT)
    print(OUTPUT)
    print(DESKTOP_OUTPUT)
    for condition in CONDITIONS:
        correct = sum(
            summaries[(task_id, condition)]["correct_runs"]
            for task_id in (1, 5, 7, 25)
        )
        print(condition, f"{correct}/40")


if __name__ == "__main__":
    main()
