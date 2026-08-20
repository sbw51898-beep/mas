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
V1_JSONL = ROOT / "artifacts" / "hiddenbench-stability-20260729.jsonl"
V1_AUDIT = (
    ROOT / "artifacts" / "hiddenbench-stability-20260729.ai-disclosure.jsonl"
)
V2_JSONL = ROOT / "artifacts" / "hiddenbench-governance-20260802.jsonl"
V2_AUDIT = (
    ROOT / "artifacts" / "hiddenbench-governance-20260802.ai-disclosure.jsonl"
)
V3_JSONL = ROOT / "artifacts" / "hiddenbench-structured-20260802.jsonl"
V3_AUDIT = (
    ROOT / "artifacts" / "hiddenbench-structured-20260802.ai-disclosure.jsonl"
)
OUTPUT = (
    ROOT
    / "reports"
    / "整合治理（Structured协议）实验报告_2026-08-02.docx"
)
DESKTOP_OUTPUT = (
    Path.home()
    / "Desktop"
    / "整合治理（Structured协议）实验报告_2026-08-02.docx"
)

CONDITIONS = ("fixed", "dynamic", "fixed-disc", "dynamic-disc", "structured")
CONDITION_LABEL = {
    "fixed": "固定轮转（基线）",
    "dynamic": "MAF动态（基线）",
    "fixed-disc": "固定+强制披露",
    "dynamic-disc": "MAF动态+强制披露",
    "structured": "Structured协议",
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


def _correct_fraction(votes: list[dict], correct: str) -> float:
    if not votes:
        return 0.0
    return sum(1 for vote in votes if vote["vote"] == correct) / len(votes)


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def _aggregate() -> dict[tuple[int, str], dict]:
    records = (
        _load_jsonl(V1_JSONL)
        + _load_jsonl(V2_JSONL)
        + _load_jsonl(V3_JSONL)
    )
    audits = (
        _load_jsonl(V1_AUDIT)
        + _load_jsonl(V2_AUDIT)
        + _load_jsonl(V3_AUDIT)
    )
    audit_by_key = {}
    for audit in audits:
        key = audit["study_key"]
        audit_by_key[
            f"task-{key['task_id']}:{key['condition']}:rep-{key['repetition']}"
        ] = audit

    rows: dict[tuple[int, str], list[dict]] = {}
    for record in records:
        key = record["key"]
        run = record["run"]
        task = run["task"]
        audit = audit_by_key.get(
            f"task-{key['task_id']}:{key['condition']}:rep-{key['repetition']}"
        )
        post_votes = run["hidden_post_votes"]
        votes = [vote["vote"] for vote in post_votes]
        rows.setdefault((key["task_id"], key["condition"]), []).append(
            {
                "disclosure": (
                    audit["disclosure_rate"]
                    if audit is not None
                    else float("nan")
                ),
                "post_correct": _correct_fraction(
                    post_votes,
                    task["correct_answer"],
                ),
                "unanimous_wrong": (
                    len(votes) == 4
                    and len(set(votes)) == 1
                    and votes[0] != task["correct_answer"]
                ),
                "distribution": Counter(votes),
                "y_pre": _correct_fraction(
                    run["hidden_pre_votes"],
                    task["correct_answer"],
                ),
                "y_post": _correct_fraction(
                    post_votes,
                    task["correct_answer"],
                ),
                "y_full": _correct_fraction(
                    run["full_profile_votes"],
                    task["correct_answer"],
                ),
            }
        )
    summaries: dict[tuple[int, str], dict] = {}
    for key, items in rows.items():
        summaries[key] = {
            "disclosure_mean": statistics.mean(
                item["disclosure"] for item in items
            ),
            "post_majority_correct": sum(
                1 for item in items if item["post_correct"] == 1.0
            ),
            "unanimous": sum(
                1 for item in items if item["unanimous_wrong"]
            ),
            "distribution": dict(
                sum((item["distribution"] for item in items), Counter())
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
    run = eyebrow.add_run("MAS知识治理实验·第3轮")
    _set_run_font(run, size=12, bold=True, color=BLUE)
    title = document.add_paragraph()
    title.alignment = 1
    run = title.add_run("整合治理：论文 Structured 协议复现")
    _set_run_font(run, size=22, bold=True, color=NAVY)
    subtitle = document.add_paragraph()
    subtitle.alignment = 1
    subtitle.paragraph_format.space_before = Pt(8)
    run = subtitle.add_run(
        "Exchange-then-Decide 协议在 DeepSeek 上对照披露治理，"
        "检验 ID5/ID7 的失败是否可被“整合环节”修复"
    )
    _set_run_font(run, size=12, color=DARK_GRAY)
    document.add_paragraph().paragraph_format.space_after = Pt(24)
    _add_table(
        document,
        ["项目", "内容"],
        [
            ("日期", "2026-08-02"),
            ("模型", "DeepSeek V4 Flash（temperature=0）"),
            ("协议", "论文 Structured：Exchange 2 轮 + Decide 1 轮，共 12 条消息"),
            ("题目", "HiddenBench ID 1、5、7、25"),
            ("重复", "4 题 × 10 次 = 40 次运行"),
            ("调用量", "正式 1000 次 API 请求（含 40 条披露审计）"),
        ],
        [2400, 6960],
        font_size=10.5,
    )
    document.add_page_break()


def _add_summary(
    document: DocumentType,
    summaries: dict[tuple[int, str], dict],
) -> None:
    document.add_heading("一、结论先行", level=1)
    document.add_paragraph(
        "Structured 协议（论文 2505.11556 的 Exchange-then-Decide）在"
        "DeepSeek 上复现的结果是：ID1 9/10、ID25 9/10，与披露治理接近；"
        "但 ID5 0/10、ID7 2/10，仍然失败。也就是说，两个针对“整合”设计的"
        "机制（强制披露、结构化交换-决策）都没能让 DeepSeek 在 ID5/ID7 上"
        "达到单智能体全信息水平（Y_full=87.5%–90%）。"
    )
    _add_callout(
        document,
        "核心发现",
        "ID5/ID7 的失败对 DeepSeek 是“信息给了也不会用”：Y_full 高（90%/87.5%），"
        "但无论 60 条自由讨论、强制披露还是 12 条结构化协议，讨论后正确率都"
        "停留在 0–20%。而论文用 GPT-4.1/Gemini 时，同样的结构化协议平均达到"
        "80%/73%。这指向模型级的推理与信息整合能力差异，而不是治理协议本身"
        "设计错误。",
    )
    document.add_page_break()


def _add_protocol(document: DocumentType) -> None:
    document.add_heading("二、协议与提示词", level=1)
    document.add_paragraph(
        "按论文原文实现：Exchange 阶段 2 轮，每轮 4 名智能体依次发言，"
        "每人分享 1–2 条决策相关信息，并给出当前领先选项可能错误的一个理由；"
        "Decide 阶段 1 轮，每人总结最强证据与剩余不确定性，然后投票。"
        "总消息 12 条，远小于基线的 60 条，是论文强调的“轻量协议”。"
    )
    document.add_paragraph("Exchange 阶段提示词（第 2 轮起）：")
    prompt = document.add_paragraph()
    run = prompt.add_run(
        'Previous messages from other people:\n{messages}\n'
        "Share 1-2 decision-relevant facts you have, and give one reason "
        "the current front-runner may be incorrect."
    )
    _set_run_font(run, size=9.5, color=DARK_GRAY)
    document.add_paragraph("Decide 阶段提示词：")
    prompt = document.add_paragraph()
    run = prompt.add_run(
        'Previous messages from other people:\n{messages}\n'
        "Summarize the strongest evidence and your remaining uncertainty "
        "before voting."
    )
    _set_run_font(run, size=9.5, color=DARK_GRAY)
    _add_source_note(
        document,
        "系统提示词与基线一致（Hidden Profile：每人只看到自己的私有信息包），"
        "协议不向智能体揭示信息不对称的存在，与论文设定一致。",
    )
    document.add_page_break()


def _add_results(
    document: DocumentType,
    summaries: dict[tuple[int, str], dict],
) -> None:
    document.add_heading("三、五种机制 × 四题结果", level=1)
    rows = []
    for task_id in (1, 5, 7, 25):
        for condition in CONDITIONS:
            summary = summaries[(task_id, condition)]
            rows.append(
                [
                    f"{task_id} {TASKS[task_id]}",
                    CONDITION_LABEL[condition],
                    _pct(summary["disclosure_mean"]),
                    f"{summary['post_majority_correct']}/10",
                    f"{summary['unanimous']}/10",
                    _pct(summary["y_post"]),
                    _pct(summary["y_full"]),
                ]
            )
    _add_table(
        document,
        [
            "任务",
            "机制",
            "披露率",
            "多数正确",
            "错误共识",
            "Y_post",
            "Y_full",
        ],
        rows,
        [1250, 1650, 950, 950, 950, 1300, 2310],
        font_size=8.0,
    )
    _add_source_note(
        document,
        "Y_post=讨论后 4 票平均正确率；Y_full=每人拿到全部信息后单独投票正确率"
        "（单智能体上限）。Structured 协议的披露率低于强制披露轮，因为 Exchange"
        "只要求分享 1–2 条事实而非全部私有信息——这是论文协议的原始设定。",
    )
    document.add_paragraph(
        "三种治理机制都没有在 ID5/ID7 上带来实质提升；ID1/ID25 在披露治理"
        "下达到 10/10，Structured 下为 9/10。基线固定轮转在 ID1 已是 10/10，"
        "因此 ID1 没有提升空间。"
    )
    document.add_page_break()


def _add_paper_comparison(document: DocumentType) -> None:
    document.add_heading("四、与论文 Structured 结果的对标", level=1)
    _add_table(
        document,
        ["来源", "模型", "协议", "平均正确率", "说明"],
        [
            (
                "论文 Table 7",
                "GPT-4.1",
                "Structured",
                "80.0%",
                "18 题平均（3 人工 + 15 随机）",
            ),
            (
                "论文 Table 7",
                "Gemini-2.5-Flash",
                "Structured",
                "72.7%",
                "18 题平均",
            ),
            (
                "论文 Table 7",
                "Gemini-2.5-Flash-Lite",
                "Structured",
                "74.3%",
                "18 题平均",
            ),
            (
                "本实验",
                "DeepSeek V4 Flash",
                "Structured",
                "50.0%",
                "ID1/5/7/25 平均（20/40）",
            ),
            (
                "本实验",
                "DeepSeek V4 Flash",
                "Structured",
                "36.7%",
                "仅论文 3 道人工题 ID1/5/7（11/30）",
            ),
        ],
        [1100, 1800, 1450, 1150, 3860],
        font_size=8.5,
    )
    _add_source_note(
        document,
        "论文数值来自 HiddenBench（arXiv:2505.11556）Table 7；我们的 3 道人工题"
        "即论文 18 题中的 ID 1/5/7，但论文只公布 18 题平均，未公布逐题数值，"
        "因此两边不能直接相减，只能做同题不同模型的参考性对照。",
    )
    document.add_paragraph(
        "需要注意：论文的 80% 是 18 题平均，其中包含 15 道随机抽样的较简单题；"
        "我们只跑 4 题且其中 3 题是人工设计的“隐藏档案”难题，平均分被 ID5/ID7"
        "拖低是预期内的。真正值得对照的是方向：论文结构化协议相对其基线提升"
        "巨大（0.037→0.800），而我们的结构化协议相对 DeepSeek 基线（0.4 平均）"
        "几乎无提升（0.367 平均）。同一协议、不同模型，效果完全不同。"
    )
    document.add_page_break()


def _add_conclusion(document: DocumentType) -> None:
    document.add_heading("五、结论与下一步", level=1)
    for point in [
        "披露治理（第 2 轮）已证明：披露率可以修，且 ID1/ID25 上披露→正确。",
        "Structured 协议（第 3 轮）证明：在 ID5/ID7 上，即使按论文的整合协议走，DeepSeek 仍失败。",
        "两个任务的 Y_full=87.5%–90%，说明失败不是题目无解，而是讨论过程无法把已公开的信息转化为正确投票。",
        "与论文的模型差异（GPT-4.1/Gemini 结构化后 72.7%–80%）说明：同一治理协议的效果强烈依赖底层模型。",
    ]:
        document.add_paragraph(f"• {point}")
    document.add_heading("下一步", level=2)
    for step in [
        "换模型复验：用更强模型（GPT-4.1 或 DeepSeek 更高档位）跑 ID5/ID7 的三种治理机制，直接回答“协议 vs 模型”哪个是主因。",
        "失败归因：对 ID5/ID7 的逐轮发言做错误共识编码（信息未披露 / 披露被忽略 / 证据被错误解释），定位整合失效的具体环节。",
        "投票前强制自我质询：在 Decide 阶段要求智能体列出“反对自己当前选择的证据”，直接对抗过早共识。",
        "人工盲审 84 项 AI—规则分歧，先给披露率一个金标准。",
    ]:
        document.add_paragraph(f"{step}")
    _add_callout(
        document,
        "给老师的一句话",
        "对标和披露率 0 的问题都已解决并有数据；现在卡在模型层：DeepSeek 把信息"
        "摆到面前也不会用。下一步最有信息量的是同协议换模型，把“协议问题”和"
        "“模型问题”分开。",
    )


def _build_document(summaries: dict) -> DocumentType:
    document = Document()
    _configure_styles(document)
    _configure_page(document)
    _add_cover(document)
    _add_summary(document, summaries)
    _add_protocol(document)
    _add_results(document, summaries)
    _add_paper_comparison(document)
    _add_conclusion(document)
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
    for task_id in (1, 5, 7, 25):
        for condition in CONDITIONS:
            row = summaries[(task_id, condition)]
            print(
                task_id,
                condition,
                f"disc={_pct(row['disclosure_mean'])}",
                f"correct={row['post_majority_correct']}/10",
                f"y_post={_pct(row['y_post'])}",
                f"y_full={_pct(row['y_full'])}",
            )


if __name__ == "__main__":
    main()
