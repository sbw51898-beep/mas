from __future__ import annotations

import json
import shutil
import statistics
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
DATA_SOURCES = {
    "fixed": ARTIFACTS / "hiddenbench-stability-20260729.jsonl",
    "dynamic": ARTIFACTS / "hiddenbench-stability-20260729.jsonl",
    "fixed-disc": ARTIFACTS / "hiddenbench-governance-20260802.jsonl",
    "dynamic-disc": ARTIFACTS / "hiddenbench-governance-20260802.jsonl",
    "structured": ARTIFACTS / "hiddenbench-structured-20260802.jsonl",
    "single-direct": ARTIFACTS / "hiddenbench-contrast-20260803.jsonl",
    "single-reflect": ARTIFACTS / "hiddenbench-contrast-20260803.jsonl",
    "fixed-12": ARTIFACTS / "hiddenbench-contrast-20260803.jsonl",
    "fixed-4": ARTIFACTS / "hiddenbench-earlystop-20260803.jsonl",
    "fixed-8": ARTIFACTS / "hiddenbench-earlystop-20260803.jsonl",
}
AUDIT_SOURCES = {
    "fixed": ARTIFACTS / "hiddenbench-stability-20260729.ai-disclosure.jsonl",
    "dynamic": ARTIFACTS / "hiddenbench-stability-20260729.ai-disclosure.jsonl",
    "fixed-disc": ARTIFACTS / "hiddenbench-governance-20260802.ai-disclosure.jsonl",
    "dynamic-disc": ARTIFACTS / "hiddenbench-governance-20260802.ai-disclosure.jsonl",
    "structured": ARTIFACTS / "hiddenbench-structured-20260802.ai-disclosure.jsonl",
    "fixed-4": ARTIFACTS / "hiddenbench-earlystop-20260803.ai-disclosure.jsonl",
    "fixed-8": ARTIFACTS / "hiddenbench-earlystop-20260803.ai-disclosure.jsonl",
}
GPT_SUMMARY = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.gpt.summary.json"
)
SELF_SUMMARY = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.summary.json"
)
OUTPUT = (
    ROOT
    / "reports"
    / "实验总报告（自老师提要求以来）_2026-08-03.docx"
)
DESKTOP_OUTPUT = (
    Path.home()
    / "Desktop"
    / "实验总报告（自老师提要求以来）_2026-08-03.docx"
)

CONDITIONS = (
    "fixed",
    "dynamic",
    "fixed-disc",
    "dynamic-disc",
    "structured",
    "fixed-12",
    "single-direct",
    "single-reflect",
    "fixed-4",
    "fixed-8",
)
CONDITION_LABEL = {
    "fixed": "固定轮转60条",
    "dynamic": "MAF动态60条",
    "fixed-disc": "固定+强制披露",
    "dynamic-disc": "MAF动态+强制披露",
    "structured": "Structured协议12条",
    "fixed-12": "固定轮转12条",
    "single-direct": "单智能体直接作答",
    "single-reflect": "单智能体+15轮反思",
    "fixed-4": "固定轮转16条（提前停止）",
    "fixed-8": "固定轮转32条（提前停止）",
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


def _disclosure_by_key() -> dict[str, float]:
    result: dict[str, float] = {}
    for condition, path in AUDIT_SOURCES.items():
        for item in _load_jsonl(path):
            key = item["study_key"]
            result[
                f"task-{key['task_id']}:{condition}:rep-{key['repetition']}"
            ] = item["disclosure_rate"]
    return result


def _aggregate() -> dict[tuple[int, str], dict]:
    records = []
    for path in sorted(set(DATA_SOURCES.values())):
        records.extend(_load_jsonl(path))
    disclosure = _disclosure_by_key()
    rows: dict[tuple[int, str], list[dict]] = {}
    for record in records:
        key = record["key"]
        condition = key["condition"]
        run = record["run"]
        task = run["task"]
        correct = task["correct_answer"]
        post_votes = run["hidden_post_votes"]
        votes = [vote["vote"] for vote in post_votes]
        rows.setdefault((key["task_id"], condition), []).append(
            {
                "disclosure": disclosure.get(
                    f"task-{key['task_id']}:{condition}:rep-{key['repetition']}"
                ),
                "correct": (
                    sum(1 for vote in votes if vote == correct)
                    == len(votes)
                    if votes
                    else False
                ),
                "unanimous_wrong": (
                    len(votes) > 0
                    and len(set(votes)) == 1
                    and votes[0] != correct
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
        disclosures = [
            item["disclosure"]
            for item in items
            if item["disclosure"] is not None
        ]
        summaries[key] = {
            "disclosure_mean": (
                statistics.mean(disclosures) if disclosures else None
            ),
            "correct": sum(1 for item in items if item["correct"]),
            "unanimous_wrong": sum(
                1 for item in items if item["unanimous_wrong"]
            ),
            "y_post": statistics.mean(item["y_post"] for item in items),
            "y_full": statistics.mean(item["y_full"] for item in items),
        }
    return summaries


def _add_cover(document: DocumentType) -> None:
    document.add_paragraph().paragraph_format.space_after = Pt(14)
    document.add_paragraph().paragraph_format.space_after = Pt(18)
    eyebrow = document.add_paragraph()
    eyebrow.alignment = 1
    run = eyebrow.add_run("MAS知识治理·按老师要求改进实验总报告")
    _set_run_font(run, size=12, bold=True, color=BLUE)
    title = document.add_paragraph()
    title.alignment = 1
    run = title.add_run("自 2026-08-02 老师提要求以来的全部工作")
    _set_run_font(run, size=21, bold=True, color=NAVY)
    subtitle = document.add_paragraph()
    subtitle.alignment = 1
    subtitle.paragraph_format.space_before = Pt(8)
    run = subtitle.add_run(
        "对标题目 → 披露率0修复 → Structured协议复现 → 单智能体与同预算对照 → 独立盲审"
    )
    _set_run_font(run, size=12, color=DARK_GRAY)
    document.add_paragraph().paragraph_format.space_after = Pt(24)
    _add_table(
        document,
        ["项目", "内容"],
        [
            ("覆盖时段", "2026-08-02（老师提要求）至 2026-08-03"),
            ("模型", "DeepSeek V4 Flash（temperature=0，thinking=disabled）"),
            ("框架", "Microsoft Agent Framework + MAF 五因子发言选择"),
            ("题目", "HiddenBench ID 1、5、7、25（1/5/7 为论文 3 道人工题）"),
            ("运行规模", "8 条件 × 4 题 × 10 次 = 320 次运行，约 9400 次 API 请求"),
            ("配套", "AI 披露审计 160 条 + 独立盲审 144 项 + 逐轮编码 ID1/5/7"),
        ],
        [2400, 6960],
        font_size=10.5,
    )
    document.add_page_break()


def _add_requirements(document: DocumentType) -> None:
    document.add_heading("一、老师的要求与落实情况", level=1)
    _add_table(
        document,
        ["老师的要求（8月2日以来）", "落实方式", "结果"],
        [
            (
                "题目要有对标，选别人公布过结果的",
                "锁定 ID1/5/7（论文 18 题实验中的 3 道人工题）+ ID25，报告给出论文 Table 6/7 对标",
                "对标表见第二章；1/5/7 对应关系为高置信推断并已标注",
            ),
            (
                "解决披露率为 0 的问题",
                "新增“强制披露轮”：第一轮 4 条发言强制陈述私有信息",
                "ID7 披露率 0%→100%；ID5 0%→30–40%；ID1/ID25 升至 80–100%",
            ),
            (
                "复现论文 Structured 协议",
                "实现 Exchange 2 轮 + Decide 1 轮（12 条消息）",
                "ID1 9/10、ID25 9/10；ID5 0/10、ID7 2/10",
            ),
            (
                "10 次全错，不如单智能体？",
                "新增单智能体直接作答与 15 轮反思对照",
                "单智能体 5–7/40，低于任何 4 人组 20–24/40；Y_full 85–95% 才是差距所在",
            ),
            (
                "Structured 预算不同不可比",
                "新增同预算固定轮转 12 条基线",
                "fixed-12 21/40 ≈ fixed-60 20/40，预算不是混淆变量",
            ),
            (
                "确认性版本要人工盲审 84 项分歧并分层抽样",
                "144 项盲化队列由独立模型完成逐项复核（Codex，非 DeepSeek）",
                "一致率 79.5%、AI 精确率 95.1%、召回率 66.7%、修订披露率 55.7%",
            ),
            (
                "既然前几轮已达成一致，为何还要往下（提前停止）",
                "固定轮转分别截断为 16/32/60 条消息对照",
                "三者结果完全相同（各 20/40）：共识形成后继续发言无收益，可提前停止省 token",
            ),
        ],
        [2300, 3300, 3760],
        font_size=8.0,
    )
    _add_callout(
        document,
        "声明",
        "独立盲审由 Codex 完成，不是真人金标准；同一份已填签核表可交真人复核。"
        "强制披露轮与 Structured 实验的披露率尚未经独立盲审，仍为 AI 审计值。",
    )
    document.add_page_break()


def _add_benchmark(document: DocumentType) -> None:
    document.add_heading("二、与论文结果的对标", level=1)
    _add_table(
        document,
        ["论文干预（18题平均）", "GPT-4.1", "Gemini-2.5-Flash", "Gemini-Lite", "我们的 DeepSeek 参照"],
        [
            ("Baseline", "0.037", "0.173", "0.043", "固定轮转 ID1/5/7：12/30"),
            ("Reveal-All 强制披露", "0.926", "0.982", "—", "固定+披露 ID1/5/7：14/30"),
            ("Secretary 被动总结", "0.241", "0.713", "—", "—"),
            ("Structured 协议", "0.800", "0.727", "0.743", "ID1/5/7：11/30"),
        ],
        [2300, 1300, 1600, 1300, 2860],
        font_size=8.0,
    )
    _add_source_note(
        document,
        "论文数值来自 HiddenBench（arXiv:2505.11556）Table 6/7，18 题平均（3 人工 + "
        "15 随机）；论文未公布逐题结果，故我们只能做 18 题平均与 3 道人工题的参考性"
        "对照。核心分歧：论文模型“披露即可整合”（Reveal-All 0.926/0.982），"
        "DeepSeek 在 ID5/ID7 披露 100% 仍失败。",
    )
    document.add_page_break()


def _add_results(
    document: DocumentType,
    summaries: dict[tuple[int, str], dict],
) -> None:
    document.add_heading("三、8 条件 × 4 题完整结果", level=1)
    rows = []
    for task_id in (1, 5, 7, 25):
        for condition in CONDITIONS:
            summary = summaries[(task_id, condition)]
            disclosure = (
                _pct(summary["disclosure_mean"])
                if summary["disclosure_mean"] is not None
                else "—"
            )
            rows.append(
                [
                    f"{task_id} {TASKS[task_id]}",
                    CONDITION_LABEL[condition],
                    disclosure,
                    f"{summary['correct']}/10",
                    f"{summary['unanimous_wrong']}/10",
                    _pct(summary["y_post"]),
                    _pct(summary["y_full"]),
                ]
            )
    _add_table(
        document,
        ["任务", "条件", "披露率", "全对", "错误共识", "Y_post", "Y_full"],
        rows,
        [1150, 1650, 1000, 850, 950, 1050, 2710],
        font_size=7.5,
    )
    _add_source_note(
        document,
        "披露率为 AI 审计口径（单智能体条件无公共讨论，不适用披露率，记“—”）；"
        "全对 = 10 次重复中最终投票全部正确；错误共识 = 全体一致且答案错误；"
        "Y_post/Y_full 为票平均正确率。",
    )

    document.add_heading("四题合计速览", level=2)
    rows = []
    for condition in CONDITIONS:
        summary = summaries[(task_id, condition)]
        correct = sum(
            summaries[(task_id, condition)]["correct"]
            for task_id in (1, 5, 7, 25)
        )
        wrong = sum(
            summaries[(task_id, condition)]["unanimous_wrong"]
            for task_id in (1, 5, 7, 25)
        )
        rows.append(
            [CONDITION_LABEL[condition], f"{correct}/40", f"{wrong}/40"]
        )
    _add_table(
        document,
        ["条件", "全对合计", "错误共识合计"],
        rows,
        [3360, 3000, 3000],
        font_size=9.0,
    )
    document.add_page_break()


def _add_analysis(document: DocumentType) -> None:
    document.add_heading("四、核心结论", level=1)
    document.add_heading("1. 披露率可以修，且披露→正确只在部分任务成立", level=2)
    document.add_paragraph(
        "强制披露轮把披露率从 0–90% 拉到 30–100%，ID1/ID25 正确率同步升至 "
        "10/10；但 ID5/ID7 披露率 100% 仍全错。披露是必要条件，不是充分条件。"
    )
    document.add_heading("2. 失败瓶颈在模型层的整合能力", level=2)
    document.add_paragraph(
        "ID5/ID7 的单智能体全信息正确率（Y_full）为 87.5%–95%，讨论后却只有 "
        "0–20%；单智能体反思（7/40）、强制披露（24/40）、Structured（20/40）、"
        "同预算基线（21/40）都改变不了这一点。与论文 GPT-4.1/Gemini 的 "
        "72.7%–80% 对比，说明同一协议的效果强依赖底层模型。"
    )
    document.add_heading("3. 多智能体优于单智能体（同信息设定下）", level=2)
    document.add_paragraph(
        "单智能体直接作答 5/40、反思 7/40；任何 4 人组条件 20–24/40。讨论的"
        "价值在于信息汇聚，预算多少不敏感（12 条 ≈ 60 条）。"
    )
    document.add_heading("4. 必须承认的负面结果", level=2)
    document.add_paragraph(
        "MAF 动态机制在 4 题上整体未跑赢固定轮转（14/40 vs 20/40），治理收益"
        "来自强制披露轮而非动态选择；五因子权重未经调参。Structured 协议相对"
        "同预算基线无增益。这两点都不能包装成正面结论。"
    )
    document.add_heading("5. 披露率对评审者高度敏感", level=2)
    document.add_paragraph(
        "同一 144 项，DeepSeek 自审一致率 93.5%、修订披露率 36.4%；独立模型"
        "盲审一致率 79.5%、修订披露率 55.7%。AI 审计存在系统性漏报（召回率 "
        "66.7%），任何单一评审者都不能自称金标准，最终需要真人仲裁。"
    )
    document.add_heading("6. 提前停止是安全的", level=2)
    document.add_paragraph(
        "固定轮转截断到 16 条、32 条与完整 60 条的结果完全一致（均为 20/40，"
        "ID1/ID25 全对、ID5/ID7 全错）。共识在前几轮就已固化：答得对的题 4 轮"
        "就够，答错的题继续 44 条也不会翻盘。因此老师问的“达成一致为何还要"
        "往下”的答案是：不需要，可以提前停止，省下约 2/3 的发言预算。"
    )
    document.add_page_break()


def _add_next(document: DocumentType) -> None:
    document.add_heading("五、下一步", level=1)
    for step in [
        "换强模型（GPT-4.1 或 DeepSeek 更高档位）复跑同一 8 条件矩阵，把“模型问题”与“协议问题”彻底分离。",
        "对 ID5/ID7 做逐轮证据使用审计（已披露信息是否被正确引用/错误否定），定位整合失效的具体环节。",
        "真人填写 144 项盲审签核表，给出最终人工一致率、精确率、召回率与修订披露率。",
        "MAF 五因子权重做敏感性分析/消融，否则不能声称动态机制优于固定轮转。",
        "把提前停止规则接入正式协议（如连续两轮全体一致即停止），验证节省预算的同时结果不变。",
    ]:
        document.add_paragraph(f"{step}")
    _add_callout(
        document,
        "给老师的一句话",
        "老师提的要求全部有对应实验和数字：题目对标了论文、披露率 0 修好了、"
        "Structured 复现了、单智能体和预算质疑都补了对照、盲审做了独立复核。"
        "剩下两个未闭环：真人签核和强模型复验，都只需要人工/算力，不需要再改设计。",
    )


def _build_document(summaries: dict) -> DocumentType:
    document = Document()
    _configure_styles(document)
    _configure_page(document)
    _add_cover(document)
    _add_requirements(document)
    _add_benchmark(document)
    _add_results(document, summaries)
    _add_analysis(document)
    _add_next(document)
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
            summaries[(task_id, condition)]["correct"]
            for task_id in (1, 5, 7, 25)
        )
        print(condition, f"{correct}/40")


if __name__ == "__main__":
    main()
