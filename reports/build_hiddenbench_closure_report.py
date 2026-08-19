"""Build a bounded closure supplement without replacing the frozen final paper."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

# Support both ``python -m reports.build_hiddenbench_closure_report`` and
# direct execution as ``python reports/build_hiddenbench_closure_report.py``.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from reports import build_correctness_governance_report as governance
from reports.build_paper_style_footnotes import _patch_true_footnotes, _short_note
from reports.build_paper_style_report import (
    EVIDENCE_PATH,
    REFERENCE_PATH,
    _body,
    _callout,
    _configure_paper,
    _font,
    _heading,
    _table,
    _table_caption,
    _validate_tables,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "基于MAF的HiddenBench多智能体正确性诊断与错误链路分析_老师问题全部修订版_2026-08-19.docx"
CLOSURE_EVIDENCE_PATH = Path("reports/data/hiddenbench-closure-evidence-20260817.json")
FROZEN_AUDIT_PATH = Path("artifacts/hiddenbench-confirmatory-20260804.audits.jsonl")
SELF_REPORT_PATH = Path("artifacts/hiddenbench-confirmatory-20260804.self-report-audits.jsonl")
PRESERVED_REPORT = Path("reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx")
PRESERVED_REPORT_SHA256 = "21ac7bcbde08b17eb5f1978af35192e03af72642ae9d34fdf4c8c35e790a048f"


# These are the exact runtime prompt templates in
# src/mas_experiment/hiddenbench_prompts.py and
# src/mas_experiment/hiddenbench_atomic_disclosure.py.  Angle-bracket fields
# identify the deterministic runtime substitutions; they are not extra
# instructions added for the report.
RUNTIME_SYSTEM_PROMPT = """<task description>

You have received the following information, notice the order of this information is
randomly shuffled, the order of facts does not indicate importance or relationship,
please reason carefully:
<randomly shuffled shared facts and this Agent's private fact>
Keep your response concise-just one or two sentences."""

RUNTIME_FIRST_TURN_PROMPT = "You are the first to speak."

RUNTIME_LATER_TURN_PROMPT = """Previous messages from other people:
<agent_id>: <public message>
It’s your turn to speak."""

RUNTIME_VOTE_PROMPT = """Previous messages from other people:
<complete public discussion; hidden_post only>
Please decide and provide your rationale in the following JSON format:
{
  "vote": "<one exact answer from: <option 1> | <option 2> | <option 3>",
  "rationale": "<a concise rationale>"
}
Return only the JSON object."""

RUNTIME_ATOMIC_AUDIT_PROMPT = """Determine whether every atomic private claim was disclosed in the public discussion.

Rules:
1. Only an owner-authored message can disclose that owner's fact.
2. A faithful paraphrase counts; a polarity reversal, contradiction, or decision-relevant omission does not.
3. For disclosed=true, cite at least one owner-authored message ID and copy one exact non-empty substring from it.
4. For disclosed=false, return an empty message-ID list and quote.
5. Return exactly one judgment for every fact ID. Do not calculate the percentage.

ATOMIC PRIVATE FACTS:
- <fact_id> | owner=<agent_id> | claim=<private claim>

PUBLIC MESSAGES:
<message_id> | <agent_id> | <message content>

Return strict JSON only in this shape:
{"facts": [{"fact_id": "atomic-fact:example", "owner_agent_id": "agent-a", "disclosed": true, "evidence_message_ids": ["message-id"], "evidence_quote": "exact substring", "reason": "short reason", "confidence": 0.95}]}"""

RUNTIME_SELF_REPORT_PROMPT = """Determine whether every atomic private claim was disclosed in the public discussion.

Rules:
1. Only an owner-authored message can disclose that owner's fact.
2. A faithful paraphrase counts; a polarity reversal, contradiction, or decision-relevant omission does not.
3. For disclosed=true, cite at least one owner-authored message ID and copy one exact non-empty substring from it.
4. For disclosed=false, return an empty message-ID list and quote.
5. Return exactly one judgment for every fact ID.
6. After judging all facts, independently count disclosed=true judgments and calculate your own count/denominator rate.
7. Do not copy a precomputed rate; calculate it from your own fact judgments.

ATOMIC PRIVATE FACTS:
- <fact_id> | owner=<agent_id> | claim=<private claim>

PUBLIC MESSAGES:
<message_id> | <agent_id> | <message content>

Return strict JSON only in this shape:
{"facts": [{"fact_id": "atomic-fact:example", "owner_agent_id": "agent-a", "disclosed": true, "evidence_message_ids": ["message-id"], "evidence_quote": "exact substring", "reason": "short reason", "confidence": 0.95}], "reported_disclosure_count": 1, "reported_disclosure_denominator": 4, "reported_disclosure_rate": 0.25}"""

RUNTIME_GLOBAL_REVEAL_PROMPT = """[SYSTEM MECHANICAL REVEAL-ALL]
The following private facts are injected verbatim by the system:
- <private fact 1>
- <private fact 2>
- <private fact 3>
- <private fact 4>"""

STRUCTURED_PROTOCOL_PROMPT = """structured-12 的公开讨论规则（项目 Prompt）：

第 1-2 轮（每轮 4 个 Agent 依次发言）：
Share 1-2 decision-relevant facts you have, and give one reason the current
front-runner may be incorrect.

第 3 轮（每个 Agent 依次发言）：
Summarize the strongest evidence and your remaining uncertainty before voting.

随后使用与 fixed-12 相同的 hidden_post 最终投票 Prompt。两种条件都发送
12 条公开消息；structured-12 只改变公开发言 Prompt，不机械注入事实，也不使用
LLM 选择器。"""

RUNTIME_DISCUSSION_PROMPT = f"""[SYSTEM PROMPT]
{RUNTIME_SYSTEM_PROMPT}

[FIRST DISCUSSION USER PROMPT]
{RUNTIME_FIRST_TURN_PROMPT}

[LATER DISCUSSION USER PROMPT]
{RUNTIME_LATER_TURN_PROMPT}"""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _self_report_summary(
    self_report_rows: list[dict[str, Any]],
    frozen_audit_rows: list[dict[str, Any]],
    closure: dict[str, Any],
) -> dict[str, Any]:
    if len(self_report_rows) != 60:
        raise ValueError("self-report audit must contain 60 ordinary runs")
    frozen_by_key: dict[tuple[str, int, int], dict[str, bool]] = {}
    for row in frozen_audit_rows:
        key = row["study_key"]
        condition = key["condition"]
        if condition not in {"fixed-60", "dynamic-60"}:
            continue
        frozen_by_key[(condition, int(key["task_id"]), int(key["repetition"]))] = {
            item["fact_id"]: bool(item["disclosed"])
            for item in row["judgments"]
        }

    by_condition: dict[str, dict[str, Any]] = {}
    for condition in ("fixed-60", "dynamic-60"):
        rows = [row for row in self_report_rows if row["key"]["condition"] == condition]
        agreement = 0
        total_facts = 0
        for row in rows:
            key = (
                condition,
                int(row["key"]["task_id"]),
                int(row["key"]["repetition"]),
            )
            frozen = frozen_by_key[key]
            self_judgments = {
                item["fact_id"]: bool(item["disclosed"])
                for item in row["facts"]
            }
            total_facts += len(frozen)
            agreement += sum(
                frozen[fact_id] == self_judgments[fact_id]
                for fact_id in frozen
            )
        frozen_rate = next(
            item["overall"]["rate"]
            for item in closure["ordinary_60_disclosure"]["by_condition"]
            if item["condition"] == condition
        )
        self_count = sum(int(row["reported_count"]) for row in rows)
        self_denominator = sum(int(row["reported_denominator"]) for row in rows)
        by_condition[condition] = {
            "runs": len(rows),
            "frozen_rate": frozen_rate,
            "self_reported_count": self_count,
            "self_reported_denominator": self_denominator,
            "self_reported_rate": self_count / self_denominator,
            "count_rate_exact_matches": sum(
                bool(row["count_match"] and row["denominator_match"] and abs(row["rate_difference"]) < 1e-9)
                for row in rows
            ),
            "fact_agreement": agreement / total_facts,
            "fact_agreement_count": agreement,
            "fact_total": total_facts,
            "by_task": [
                {
                    "task_id": task_id,
                    "self_count": sum(
                        int(row["reported_count"])
                        for row in rows
                        if int(row["key"]["task_id"]) == task_id
                    ),
                    "denominator": sum(
                        int(row["reported_denominator"])
                        for row in rows
                        if int(row["key"]["task_id"]) == task_id
                    ),
                }
                for task_id in (1, 2, 3)
            ],
        }
    example = next(
        (
            row
            for row in self_report_rows
            if row["key"]["condition"] == "fixed-60"
            and int(row["key"]["task_id"]) == 2
            and int(row["key"]["repetition"]) == 0
        ),
        self_report_rows[0],
    )
    self_report_path = SELF_REPORT_PATH if SELF_REPORT_PATH.is_absolute() else ROOT / SELF_REPORT_PATH
    return {
        "path": str(SELF_REPORT_PATH),
        "sha256": hashlib.sha256(self_report_path.read_bytes()).hexdigest(),
        "by_condition": by_condition,
        "example": {
            "key": example["key"],
            "run_id": example["run_id"],
            "reported_disclosure_count": example["reported_count"],
            "reported_disclosure_denominator": example["reported_denominator"],
            "reported_disclosure_rate": example["reported_rate"],
            "program_rate": example["program_rate"],
        },
        "overall_exact_matches": sum(
            bool(row["count_match"] and row["denominator_match"] and abs(row["rate_difference"]) < 1e-9)
            for row in self_report_rows
        ),
        "runs": len(self_report_rows),
    }


def _assert_preserved_report(root: Path) -> None:
    current = hashlib.sha256((root / PRESERVED_REPORT).read_bytes()).hexdigest()
    if current != PRESERVED_REPORT_SHA256:
        raise ValueError("the frozen 2026-08-17 final paper must not be overwritten")


def _all_paragraphs(document: DocumentType):
    for paragraph in document.paragraphs:
        yield paragraph
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield paragraph


def _replace_paragraph(
    paragraph: Any,
    text: str,
    *,
    size: float | None = None,
    bold: bool = False,
    color: Any | None = None,
) -> None:
    inherited_size = next(
        (
            run.font.size.pt
            for run in paragraph.runs
            if run.font.size is not None
        ),
        11,
    )
    paragraph.clear()
    _font(
        paragraph.add_run(text),
        size if size is not None else inherited_size,
        bold=bold,
        color=color,
    )


def _replace_first_paragraph(
    document: DocumentType,
    fragment: str,
    replacement: str,
    *,
    size: float | None = None,
    bold: bool = False,
    color: Any | None = None,
) -> None:
    for paragraph in _all_paragraphs(document):
        if fragment in paragraph.text:
            _replace_paragraph(
                paragraph,
                replacement,
                size=size,
                bold=bold,
                color=color,
            )
            return
    raise ValueError(f"paragraph fragment not found: {fragment}")


def _remove_first_paragraph(document: DocumentType, fragment: str) -> None:
    for paragraph in _all_paragraphs(document):
        if fragment in paragraph.text:
            element = paragraph._element
            element.getparent().remove(element)
            return
    raise ValueError(f"paragraph fragment not found: {fragment}")


def _table_with_header(document: DocumentType, first_header: str) -> Any:
    for table in document.tables:
        if table.rows and table.rows[0].cells[0].text.strip() == first_header:
            return table
    raise ValueError(f"table not found: {first_header}")


def _set_table_cell(cell: Any, text: str, *, font_size: float) -> None:
    cell.text = text
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_after = Pt(0)
        for run in paragraph.runs:
            _font(run, font_size)


def _replace_all_paragraphs(
    document: DocumentType,
    fragment: str,
    replacement: str,
    *,
    size: float | None = None,
    bold: bool = False,
    color: Any | None = None,
) -> int:
    matches = 0
    for paragraph in _all_paragraphs(document):
        if fragment in paragraph.text:
            _replace_paragraph(
                paragraph,
                paragraph.text.replace(fragment, replacement),
                size=size,
                bold=bold,
                color=color,
            )
            matches += 1
    return matches


def _remove_table_row(table: Any, first_cell_text: str) -> None:
    for row in table.rows:
        if row.cells[0].text.strip() == first_cell_text:
            row._tr.getparent().remove(row._tr)
            return
    raise ValueError(f"table row not found: {first_cell_text}")


def _remove_paragraph(paragraph: Any) -> None:
    element = paragraph._element
    element.getparent().remove(element)


def _insert_code_block_before(
    document: DocumentType,
    anchor: Any,
    text: str,
) -> None:
    """Insert a compact code block before an existing appendix heading."""
    for line in text.splitlines() or [""]:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.12)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "F6F8FA")
        paragraph._p.get_or_add_pPr().append(shading)
        _font(paragraph.add_run(line or " "), 7.3)
        anchor._p.addprevious(paragraph._p)


def _append_code_block(document: DocumentType, text: str, *, font_size: float = 7.0) -> None:
    """Append a compact shaded code/prompt block to the document."""
    for line in text.splitlines() or [""]:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.12)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "F6F8FA")
        paragraph._p.get_or_add_pPr().append(shading)
        _font(paragraph.add_run(line or " "), font_size)


def _replace_appendix_code_block(
    document: DocumentType,
    *,
    heading_fragment: str,
    next_heading_fragment: str,
    replacement: str,
) -> None:
    paragraphs = list(document.paragraphs)
    start = next(
        index
        for index, paragraph in enumerate(paragraphs)
        if heading_fragment in paragraph.text
    )
    end = next(
        index
        for index, paragraph in enumerate(paragraphs[start + 1 :], start + 1)
        if next_heading_fragment in paragraph.text
    )
    next_heading = paragraphs[end]
    for paragraph in paragraphs[start + 1 : end]:
        _remove_paragraph(paragraph)
    _insert_code_block_before(document, next_heading, replacement)


def _keep_completed_content_only(document: DocumentType) -> None:
    """Remove report passages that describe unexecuted follow-up work."""
    _replace_first_paragraph(
        document,
        "本项目已实现原子事实披露审计",
        "本项目已实现原子事实披露审计、多数投票、错误共识率、同公开发言预算下的固定/动态对照和运行级错误链路标注；本文据此对具有明确消息证据的运行进行链路分析。",
    )
    _replace_first_paragraph(
        document,
        "五因子动态选择器是项目代码中的 external centralized scheduler",
        "五因子动态选择器是项目代码中的 external centralized scheduler，可以读取完整私有事实分配，并非 MAF 原生群聊能力；它不读取正确答案，也不把原始私有事实直接注入 Agent prompt。因此本文将其作为中心化、内容感知的诊断调度器进行实验比较。",
    )

    mast_table = _table_with_header(document, "模式判断")
    mast_rows = (
        (
            "FM-2.4 候选（输出级证据）",
            "0d078a3c85f64262 / fixed-60 / ID2",
            "两条所有者关键事实没有进入公共消息，最终四票错误选择 East Town；该行只支持信息未披露的输出级候选。",
        ),
        (
            "证据解释矛盾（项目输出级类别）",
            "e46521e6691a10ca / fixed-reveal-all / ID2",
            "四条事实均公开，机械注入“补给车卡在隧道”后，后续消息却称“隧道畅通”，最终四票 East Town。",
        ),
        (
            "披露后未落实（项目输出级类别）",
            "bfba1db7a056ebea / fixed-60 / ID3",
            "四条事实均披露，后续消息指出 North Hill 两条访问路径受阻或需要验证，最终仍四票 North Hill。",
        ),
    )
    if len(mast_table.rows) != 4:
        raise ValueError("unexpected MAST evidence table row count")
    for row, values in zip(mast_table.rows[1:], mast_rows, strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            _set_table_cell(cell, value, font_size=7.4)
    _replace_first_paragraph(
        document,
        "现有案例支持错误可以发生在公开和解释环节",
        "三条代表性运行显示，错误可发生在信息公开、证据解释和最终行动环节；因此仅以最终披露率或共识强度评价系统会遗漏关键失效位置。只有第一条可作为 MAST FM-2.4 的输出级候选，后两条仅是本项目的输出级错误链路类别。",
    )

    term_table = _table_with_header(document, "术语")
    _remove_table_row(term_table, "模型辅助复核")

    _replace_first_paragraph(
        document,
        "B.1  讨论 Prompt",
        "B.1  冻结确认性讨论 Prompt（真实模板）",
        size=12,
        bold=True,
        color=governance.NAVY,
    )
    _replace_first_paragraph(
        document,
        "B.2  最终投票 Prompt",
        "B.2  冻结确认性最终投票 Prompt（真实模板）",
        size=12,
        bold=True,
        color=governance.NAVY,
    )
    _replace_first_paragraph(
        document,
        "B.3  原子事实披露审计 Prompt",
        "B.3  原子事实披露审计 Prompt（真实模板）",
        size=12,
        bold=True,
        color=governance.NAVY,
    )
    _replace_first_paragraph(
        document,
        "B.4  官方兼容全局 Reveal-All 模板",
        "B.4  官方 Reveal-All 时序兼容的本地注入模板（非逐字复现）",
        size=12,
        bold=True,
        color=governance.NAVY,
    )
    _replace_appendix_code_block(
        document,
        heading_fragment="B.1  冻结确认性讨论 Prompt",
        next_heading_fragment="B.2  冻结确认性最终投票 Prompt",
        replacement=RUNTIME_DISCUSSION_PROMPT,
    )
    _replace_appendix_code_block(
        document,
        heading_fragment="B.2  冻结确认性最终投票 Prompt",
        next_heading_fragment="B.3  原子事实披露审计 Prompt",
        replacement=RUNTIME_VOTE_PROMPT,
    )
    _replace_appendix_code_block(
        document,
        heading_fragment="B.3  原子事实披露审计 Prompt",
        next_heading_fragment="B.4  官方 Reveal-All 时序兼容",
        replacement=RUNTIME_ATOMIC_AUDIT_PROMPT,
    )
    _replace_appendix_code_block(
        document,
        heading_fragment="B.4  官方 Reveal-All 时序兼容",
        next_heading_fragment="附录 C",
        replacement=RUNTIME_GLOBAL_REVEAL_PROMPT,
    )

    if not _replace_all_paragraphs(
        document,
        "同预算动态发言",
        "同公开发言预算下的动态发言",
    ):
        raise ValueError("expected at least one same-budget wording")
    _replace_all_paragraphs(
        document,
        "同预算固定/动态对照",
        "同公开发言预算下的固定/动态对照",
    )
    _replace_all_paragraphs(
        document,
        "信息可得性上限",
        "信息可得性的诊断对照",
    )
    _replace_all_paragraphs(
        document,
        "信息可得性的上限",
        "信息可得性的诊断对照",
    )
    _replace_all_paragraphs(
        document,
        "官方兼容第一轮全局 Reveal-All",
        "官方 Reveal-All 时序兼容的本地条件（非逐字复现）",
    )
    _replace_all_paragraphs(
        document,
        "本地官方兼容 Reveal-All",
        "本地时序兼容 Reveal-All（非逐字复现）",
    )
    _replace_all_paragraphs(
        document,
        "官方兼容全局 Reveal-All",
        "官方 Reveal-All 时序兼容的本地条件（非逐字复现）",
    )
    _replace_all_paragraphs(
        document,
        "同预算固定/动态",
        "同公开发言预算下的固定/动态",
    )
    # The frozen data contain one private_information string per owner.  It is
    # a source fact packet, not a clause-level atomic proposition.  Keep the
    # English ``atomic-fact`` identifiers and exact runtime prompt text intact.
    _replace_all_paragraphs(document, "clause-level 原子", "clause-level 分句")
    _replace_all_paragraphs(document, "原子披露率", "来源事实包披露率")
    _replace_all_paragraphs(document, "原子事实披露审计", "来源事实包披露审计")
    _replace_all_paragraphs(document, "原子事实", "来源事实包")
    _replace_all_paragraphs(document, "AI 原子审计", "AI 来源事实包审计")
    _replace_all_paragraphs(document, "原论文与本地复现", "HiddenBench 原论文/官方实现与本地复现")
    _replace_all_paragraphs(document, "原论文“分布式信息会导致失败", "HiddenBench 原论文“分布式信息会导致失败")
    _replace_all_paragraphs(
        document,
        "原论文与本地实现同时更换了模型",
        "HiddenBench 原论文与本地实现同时更换了模型",
    )
    _replace_all_paragraphs(document, "HiddenBench HiddenBench 原论文", "HiddenBench 原论文")
    _replace_all_paragraphs(document, "形成观测-干预闭环", "形成观测-干预诊断原型")
    _replace_all_paragraphs(document, "连接成治理闭环", "连接成治理诊断原型")
    _replace_all_paragraphs(
        document,
        "诊断对照对照",
        "诊断对照",
    )
    _replace_all_paragraphs(
        document,
        "RQ3：全局信息可得性明显改善三题表现；动态和结构化干预有方向性改善，但当前样本没有统计显著证据。",
        "RQ3：全局信息条件下观察到描述性正确率提高；动态和结构化干预也呈现方向性差异，但这些条件不是同一干预的单因素检验，当前样本没有统计显著证据。",
    )
    _replace_all_paragraphs(
        document,
        "选择 ID1、ID2 和 ID3，是因为官方公开了逐题 GPT-4.1 基线和 Reveal-All 结果，可以直接和本地复现逐题对表。三题共享同一背景和候选项 West City、North Hill 与 East Town，只改变决定正确答案的私有事实链，因此能够在背景基本固定时观察错误位置差异。本文不把三题结论外推到全部 65 题。",
        "选择 ID1、ID2 和 ID3，是因为 HiddenBench 官方公开了逐题 GPT-4.1 基线和 Reveal-All 结果，可以直接与本地复现逐题对表。三题共享同一背景和候选项 West City、North Hill 与 East Town，只改变决定正确答案的私有事实链。角色上，ID1 是两种机制下的稳定正确控制案例，ID2 代表未披露导致的错误共识，ID3 代表已披露但未落实到行动的错误链路。此前探索过的 ID5、ID7 不纳入本版跨实现主比较，是因为本版优先选择有官方逐题对照的短任务；这不是对 ID5、ID7 的效果判断。本文不把三题结论外推到全部 65 题。",
    )
    source_note = (
        "实验口径分层：表 4 的 560 次运行、397 次审计和 25,928 次模型请求是各阶段历史累计量；"
        "本报告主确认性矩阵为 7 个条件 × 3 个任务 × 10 次，即 210 次运行。表 5、表 7、表 9-15 "
        "的主结果均来自这 210 次矩阵；另有 60 次 fixed/dynamic 自报审计调用，它们重新审计已有讨论轨迹，"
        "不新增 60 次讨论实验。历史快照 reports/data/hiddenbench-paper-evidence-20260805.json 与本报告闭环补充 "
        "reports/data/hiddenbench-closure-evidence-20260817.json 用途不同；正文数据由原始 JSONL 及审计文件的 "
        "SHA-256 固定。"
    )
    _replace_all_paragraphs(
        document,
        "冻结证据文件的 SHA-256 已保存在 reports/data/hiddenbench-paper-evidence-20260805.json；正文所有数量和比例均从该快照读取。",
        source_note,
    )
    for paragraph in _all_paragraphs(document):
        if paragraph.text == source_note:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            break
    _replace_all_paragraphs(
        document,
        "383ab32a67ba98e7",
        "0d078a3c85f64262",
    )
    _replace_all_paragraphs(
        document,
        "FM-2.4 已确认",
        "FM-2.4 候选（输出级证据）",
    )
    _replace_all_paragraphs(
        document,
        "FM-2.5 待人工因果编码",
        "证据解释矛盾（项目输出级类别）",
    )
    _replace_all_paragraphs(
        document,
        "FM-2.6 未确认",
        "披露后未落实（项目输出级类别）",
    )

    appendix_index = next(
        index
        for index, paragraph in enumerate(document.paragraphs)
        if paragraph.text.strip() == "附录"
    )
    previous = document.paragraphs[appendix_index - 1]
    if not previous.text.strip() and 'w:type="page"' in previous._p.xml:
        previous._element.getparent().remove(previous._element)


def _mast_fc2_definitions(document: DocumentType, citations: Any) -> None:
    _heading(document, "2.6 MAST FC2 三种模式的操作化边界", level=2)
    _body(
        document,
        "MAST 的 FC2 类模式是本文错误链路分析的对话对象。为避免把输出现象直接当成模型内部因果，本文先给出可从消息轨迹观察到的操作化口径；它们用于检索候选案例，不等同于已经完成的责任归因。"
        + citations.cite("mast"),
    )
    _table_caption(document, "表 2a  MAST FC2 模式与本文证据边界")
    _table(
        document,
        ["模式", "本文可观察操作化", "当前证据状态"],
        [
            [
                "FM-2.4",
                "关键私有事实没有进入事实所有者的公共消息，导致其他 Agent 无法在公共历史中读取该事实。",
                "可由事实—所有者—消息 ID 直接核验；本报告仅称输出级候选。",
            ],
            [
                "FM-2.5",
                "事实已经公开，但某个 Agent 对证据的回应或解释与事实相反，并在后续链路中造成错位。",
                "必须继续做 Agent 责任与时间顺序编码；本报告未把案例写成已确认的 FM-2.5。",
            ],
            [
                "FM-2.6",
                "多个 Agent 之间的协同、同步或相互响应本身产生错位，而不只是最后投票错误。",
                "需要交互级协同证据；仅凭错误共识不能确认 FM-2.6。",
            ],
        ],
        [1200, 4300, 3860],
        font_size=7.2,
    )


def _title_and_abstract(
    document: DocumentType,
    evidence: dict[str, Any],
    closure: dict[str, Any],
    self_report_summary: dict[str, Any],
) -> None:
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(14)
    title.paragraph_format.space_after = Pt(8)
    _font(
        title.add_run("基于 Microsoft Agent Framework 的 HiddenBench 多智能体正确性诊断与错误链路分析"),
        18,
        bold=True,
        color=governance.NAVY,
    )
    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.paragraph_format.space_after = Pt(18)
    _font(meta.add_run("补充实验报告 | 2026 年 8 月 19 日"), 10.5, color=governance.MUTED)

    _heading(document, "摘要")
    totals = closure["single_agent_comparison"]["overall"]
    abstract = (
        "多智能体系统的讨论目标应是最终决策正确，而不是更快形成共识。"
        "既有 HiddenBench 复现已显示，私有信息能否及时公开、被正确理解并落实到行动，会共同影响最终结果。"
        "本文使用冻结确认性 JSONL 与来源事实包披露审计重新提取单智能体基线和消息级错误链路证据。"
        f"在相同 DeepSeek 模型和三题各 10 次范围内，局部信息单智能体、全信息无讨论单智能体和 fixed-60 多智能体分别为 {totals['single_local']}、{totals['single_full_profile']} 和 {totals['fixed_60_multi_agent']}；fixed-60 与 dynamic-60 的多数正确次数分别为 17/30 与 21/30，配对精确 McNemar 检验 p=0.125，当前样本不足以证明动态机制具有统计显著优势。"
        "本文进一步给出未披露、已披露但与证据矛盾、以及已披露但未落实到最终行动的三条消息级链路卡。"
        f"补充的模型自报披露审计覆盖 60 个普通运行，60/60 次自报计数与其逐条标签汇总一致，但与冻结主审计的逐事实一致率为 fixed-60 {self_report_summary['by_condition']['fixed-60']['fact_agreement']:.1%}、dynamic-60 {self_report_summary['by_condition']['dynamic-60']['fact_agreement']:.1%}，因此披露率被作为模型辅助的敏感性指标而非人工真值。"
        "本文将这些已完成的自动化结果固定为可追溯证据，以便复查实验设置、关键消息和最终投票。"
    )
    _body(document, abstract)
    keywords = document.add_paragraph()
    keywords.paragraph_format.space_after = Pt(12)
    _font(keywords.add_run("关键词："), 10.5, bold=True)
    _font(
        keywords.add_run(
            "多智能体系统；正确性治理；单智能体对照；信息披露；HiddenBench"
        ),
        10.5,
    )
    _callout(
        document,
        "本版范围：",
        "报告只呈现冻结数据重算、消息级错误链路和已运行条件下的可复核结果。",
        gold=True,
    )


def _closure_supplement(
    document: DocumentType,
    evidence: dict[str, Any],
    closure: dict[str, Any],
    self_report_summary: dict[str, Any],
) -> None:
    comparison = closure["single_agent_comparison"]
    ordinary_disclosure = closure["ordinary_60_disclosure"]
    ai_crosscheck = closure["ai_disclosure_crosscheck"]
    stratified_disclosure = closure["correctness_stratified_disclosure"]
    repeat_stability = closure["repeat_stability"]
    disclosure_timing = closure["disclosure_timing"]
    paired_comparisons = closure["paired_comparisons"]
    public_speech_budget = closure["public_speech_budget"]
    selector_formula = closure["selector_formula"]
    _heading(document, "6.6 闭环补充：单智能体对照与错误链路", level=2)
    _body(
        document,
        "本节不重新运行模型，也不改变冻结实验。所有数值来自 artifacts/hiddenbench-confirmatory-20260804.jsonl 与对应原子披露审计，用于明确基线、规则和证据位置。",
    )
    _body(
        document,
        "这里的“闭环”是事后诊断加条件对照的治理原型：先从冻结轨迹定位公开、利用、解释或行动环节，再比较已有条件的结果。本版没有在同一运行中根据诊断结果自动触发第二轮干预，因此不把图示解释成已经完成的全自动闭环控制器。",
    )
    _callout(
        document,
        "干预状态：",
        "已运行：fixed-60、dynamic-60、fixed-12、structured-12 和 Reveal-All 诊断对照；已实现：事实级审计、投票一致性、shadow checkpoint 和错误链路提取；本版未完成：人工双盲金标准、模型—框架解耦的 2×2 实验，以及根据诊断自动触发的第二轮干预。未完成项不被写成已验证效果。",
        gold=False,
    )
    _body(
        document,
        f"样本口径分层：表 4 的历史累计量为 {evidence['totals']['local_runs']} 次运行、{evidence['totals']['audit_requests']} 次披露审计和 {evidence['totals']['model_requests']} 次模型请求；本报告主确认性矩阵是 7 个条件 × 3 个任务 × 10 次，即 210 次运行。fixed-60 与 dynamic-60 的核心比较各有 30 次运行；新增的自报披露审计覆盖 60 条已有讨论轨迹，不增加讨论运行次数。",
    )

    _heading(document, "6.6.1 同模型单智能体参考组（非等计算预算）", level=3)
    rows = [
        [
            f"ID{item['task_id']}",
            item["single_local"],
            item["single_full_profile"],
            item["fixed_60_multi_agent"],
        ]
        for item in comparison["by_task"]
    ]
    rows.append(
        [
            "合计",
            comparison["overall"]["single_local"],
            comparison["overall"]["single_full_profile"],
            comparison["overall"]["fixed_60_multi_agent"],
        ]
    )
    _table_caption(document, "表 9  冻结确认性数据中的同模型参考组（多数正确次数）")
    _table(
        document,
        ["任务", "局部信息单 Agent", "全信息单 Agent", "fixed-60 多 Agent"],
        rows,
        [1000, 2700, 3000, 2660],
        font_size=8.1,
    )
    _body(
        document,
        "局部信息单智能体为 4/30，全信息无讨论单智能体为 20/30，fixed-60 多智能体为 17/30。这里的“全信息无讨论单 Agent”是辅助参考组，不是理论上限，也不是额外新跑的一组 API 实验：它是每次 single-local 运行内部保存的 full_profile_votes，即同一模型看到全部事实后直接投票，不经过公共讨论。它与四 Agent、60 条公开发言的 fixed-60 不具备等计算预算。ID2 是最直接的警示：全信息单 Agent 为 10/10，局部信息单 Agent 为 2/10，而 fixed-60 多 Agent 为 0/10；在这一题、这一模型和这一协议下，讨论没有带来收益，反而比全信息单 Agent 更差。因此本文不把“多智能体”或“讨论次数”本身当作正确性的保证。另一方面，ID3 中全信息单 Agent 为 0/10，而 fixed-60 为 7/10，说明讨论也可能在某些题目上提供增益；两种现象同时存在，正是需要逐题、逐链路分析的原因。",
    )

    _heading(document, "6.6.2 普通披露规则与为何继续到 60 次发言", level=3)
    _body(
        document,
        "普通条件下不随机、不强制披露：pair seed 只随机化事实归属和事实顺序，发言顺序由 fixed/dynamic 协议决定；普通 Prompt 没有要求 Agent 必须公开私有事实，因此这里测的是自然信息交换压力下的自发披露，而不是“收到披露指令后能否照做”。每个 Agent 是否在公开发言中说出、如何转述，均由模型在自然发言时生成。只有 Reveal-All 条件才由系统把私有事实机械注入公开消息。因此普通披露率不是预先抽签决定的比例。",
    )
    _body(
        document,
        "隐藏不是主张现实决策应故意瞒信息，而是模拟多个 Agent 分别掌握不同数据库权限、工具输出或专业证据的分布式信息场景；Reveal-All 是诊断“信息能否取得”的对照，而非现实建议。",
    )
    _body(
        document,
        "Reveal-All 的分母和时序在本文中分开报告：官方 HiddenBench 的逐题 Reveal-All 聚合为 30/30；本地 fixed-reveal-all 是逐步讨论、全量事实可在过程中进入公共消息的时序兼容条件，三题多数正确为 26/30；普通 fixed-60 与 dynamic-60 则是不机械注入私有事实的自然披露条件。表 6 的 30/30 与 26/30 不是同一运行矩阵，不能直接当成同一条件的重复结果。",
    )
    _body(
        document,
        "fixed-60 固定为 15 轮 × 4 个 Agent。这里没有把“前几轮看似一致”当作已被数据确认的早期共识现象；继续运行是诊断协议设计，用来观察迟到证据能否纠错、关键事实是否被后续使用、立场是否变化，以及最终投票是否稳定。它不是“早有共识仍继续讨论就一定更正确”的主张，也不能据此推导早停策略。",
    )

    _heading(document, "普通 60 次发言条件下的私有事实包披露率", level=3)
    disclosure_rows = []
    for item in ordinary_disclosure["by_condition"]:
        by_task = item["by_task"]
        if [row["task_id"] for row in by_task] != [1, 2, 3]:
            raise ValueError("ordinary disclosure task order drifted")
        overall = item["overall"]
        disclosure_rows.append(
            [
                item["condition"],
                *[
                    f"{row['disclosed']}/{row['total']}（{row['rate']:.1%}）"
                    for row in by_task
                ],
                f"{overall['disclosed']}/{overall['total']}（{overall['rate']:.1%}）",
            ]
        )
    _table_caption(document, "表 10  普通 60 次发言条件下的私有事实包披露率（owner-only，模型辅助审计）")
    _table(
        document,
        ["机制", "ID1", "ID2", "ID3", "三题合计"],
        disclosure_rows,
        [1700, 1900, 1900, 1900, 1960],
        font_size=7.5,
    )
    _body(
        document,
        "本报告将每个 Agent 的一条 private_information 字符串视为一个来源事实包；当前冻结数据没有把包内并列分句拆成 clause-level 原子。因此表 10 是来源包级覆盖率，不是逐分句真值率。主指标 D_owner 只统计事实所有者自己的公开消息对整条事实作忠实、决策相关的转述；反向、矛盾或遗漏关键分句均不计。它不是“任意 Agent 在公共消息中提到该事实”的群体知晓率；本版明确选择 owner-only 口径，D_group 需要另设不限制 owner 的敏感性审计。每题重复 10 次、每次 4 个事实包，因此每题分母为 40，三题合计分母为 120。若某一次运行四个事实包都没有合格证据，0/4=0.0% 是有效边界结果，不是漏检、缺失值或分母为零。普通 fixed-60 与 dynamic-60 的主口径 D_owner 分别为 90/120（75.0%）和 87/120（72.5%）；该数值不应被解释成群体知晓率。",
    )
    fixed_crosscheck = ai_crosscheck["by_condition"][0]["overall"]
    dynamic_crosscheck = ai_crosscheck["by_condition"][1]["overall"]
    _body(
        document,
        f"冻结主审计的 disclosure_rate 位于 artifacts/hiddenbench-confirmatory-20260804.audits.jsonl；B.3 Prompt 要求模型只返回逐条 disclosed=true/false、证据消息 ID 和原文片段，并明确写着“Do not calculate the percentage”，所以冻结主指标是“AI逐条证据判断 + 程序确定性汇总”。为回应老师关于“让 AI 自己报百分比”的要求，本版另做了 60 个普通 fixed/dynamic 运行的补充自报审计：新 Prompt 要求模型同时返回 reported_disclosure_count、reported_disclosure_denominator 和 reported_disclosure_rate，并由程序再次复算。补充审计中 60/60 条运行的模型自报计数、分母和百分比均与其逐条标签一致；但与冻结主审计逐事实一致率为 fixed-60 {self_report_summary['by_condition']['fixed-60']['fact_agreement']:.1%}（{self_report_summary['by_condition']['fixed-60']['fact_agreement_count']}/{self_report_summary['by_condition']['fixed-60']['fact_total']}），dynamic-60 {self_report_summary['by_condition']['dynamic-60']['fact_agreement']:.1%}（{self_report_summary['by_condition']['dynamic-60']['fact_agreement_count']}/{self_report_summary['by_condition']['dynamic-60']['fact_total']}）。这说明百分比会受审计调用影响，主表 10 的 D_owner 仍是冻结主口径，补充自报结果作为敏感性分析，不作为人工金标准。审计和讨论都使用 deepseek-v4-flash；独立调用不等于独立模型，因此仍不能单独证明信息已被正确解释或用于最终投票。",
    )
    self_report_rows = []
    for condition in ("fixed-60", "dynamic-60"):
        item = self_report_summary["by_condition"][condition]
        self_report_rows.append(
            [
                condition,
                f"{item['frozen_rate']:.1%}",
                f"{item['self_reported_count']}/{item['self_reported_denominator']}（{item['self_reported_rate']:.1%}）",
                f"{item['count_rate_exact_matches']}/{item['runs']}",
                f"{item['fact_agreement_count']}/{item['fact_total']}（{item['fact_agreement']:.1%}）",
            ]
        )
    _table_caption(document, "表 10a  模型自报披露率与冻结主审计的敏感性对照")
    _table(
        document,
        ["机制", "冻结主 D_owner", "补充自报计数/分母", "自报字段与标签一致", "逐事实与冻结审计一致"],
        self_report_rows,
        [1400, 1400, 2200, 1600, 2760],
        font_size=7.1,
    )
    _body(
        document,
        "表 10a 的补充审计只回答“模型能否从自己的逐条判断中正确汇总出百分比”，不能回答“模型判断本身是否正确”。由于补充调用与冻结审计不是同一次请求，二者存在事实级分歧；因此报告同时保留冻结主口径、模型自报口径和一致率，不把任一模型辅助审计结果冒充人工真值。",
    )
    timing_rows = []
    for item in disclosure_timing["by_condition"]:
        overall_total = 120
        timing_rows.append(
            [
                item["condition"],
                f"{item['disclosed_facts']}",
                f"{item['first_round_count']}/{overall_total}（{item['first_round_count'] / overall_total:.1%}）",
                f"{item['first_round_count']}/{item['disclosed_facts']}（{item['first_round_count'] / item['disclosed_facts']:.1%}）",
                f"{item['mean_first_disclosure_round']:.2f}",
                f"{item['median_first_disclosure_round']:.1f}",
            ]
        )
    _table_caption(document, "表 11  已披露事实的首次披露轮次与完整分母口径")
    _table(
        document,
        ["机制", "已披露事实数", "第 1 轮/全部事实", "第 1 轮/已披露", "平均轮次", "中位数"],
        timing_rows,
        [1450, 1300, 2050, 2050, 1300, 1210],
        font_size=7.2,
    )
    _body(
        document,
        "该时序表同时给出两个分母：条件分母只在已披露事实中计算，完整分母则回到每种机制的 120 条原子事实。fixed-60 第 1 轮披露为 85/120=70.8%；在已披露事实内部为 85/90=94.4%，平均 1.20 轮。dynamic-60 第 1 轮披露为 72/120=60.0%；在已披露事实内部为 72/87=82.8%，平均 1.77 轮。未披露事实不能被解释成“第 60 次才披露”，当前结果仍只是覆盖率和首次出现轮次的描述，尚未建立披露时机与最终正确率之间的因果关系。",
    )
    _body(
        document,
        "dynamic-60 的披露率略低但正确数更高（21/30 对 17/30），说明“说出多少事实”不等于“是否在关键时机正确解释并用于投票”。这只是描述性现象，不构成机制因果归因；披露标签仍是模型辅助审计而非人工金标准。",
    )
    stratified_by_condition = {
        item["condition"]: item
        for item in stratified_disclosure["by_condition"]
    }
    fixed_strat = stratified_by_condition["fixed-60"]
    dynamic_strat = stratified_by_condition["dynamic-60"]
    _body(
        document,
        f"按最终多数投票是否正确分层，fixed-60 的正确运行 {fixed_strat['correct_runs']} 次，平均 D_owner 为 {fixed_strat['correct_mean_disclosure_rate']:.1%}；错误运行 {fixed_strat['incorrect_runs']} 次，平均为 {fixed_strat['incorrect_mean_disclosure_rate']:.1%}。dynamic-60 的正确运行 {dynamic_strat['correct_runs']} 次，平均为 {dynamic_strat['correct_mean_disclosure_rate']:.1%}；错误运行 {dynamic_strat['incorrect_runs']} 次，平均为 {dynamic_strat['incorrect_mean_disclosure_rate']:.1%}。两种机制中正确与错误运行的披露率都有重叠，因此当前数据不支持把披露率单独当作正确率的充分预测量；它更适合作为后续检查“披露后是否被利用和解释”的入口。",
    )

    _heading(document, "6.6.3 逐题重复稳定性", level=3)
    stability_rows = []
    for item in repeat_stability["by_condition"]:
        by_task = item["by_task"]
        stability_rows.append(
            [
                item["condition"],
                *[
                    f"{row['correct_runs']}/{row['total_runs']}（{row['rate']:.1%}）"
                    for row in by_task
                ],
                f"{item['overall']['correct_runs']}/{item['overall']['total_runs']}（{item['overall']['rate']:.1%}）",
            ]
        )
    _table_caption(document, "表 12  逐题重复稳定性（每题 10 次，多数投票正确记为 C）")
    _table(
        document,
        ["机制", "ID1", "ID2", "ID3", "三题合计"],
        stability_rows,
        [1700, 1900, 1900, 1900, 1960],
        font_size=7.5,
    )
    _body(
        document,
        "逐题结果不是“动态机制普遍稳定提升”：fixed-60：ID1 10/10、ID2 0/10、ID3 7/10；dynamic-60：ID1 10/10、ID2 2/10、ID3 9/10。ID1 在两种机制下都稳定正确，ID2 在两种机制下都以错误为主，ID3 则存在少量重复间波动。Wilson 95% 区间也很宽：fixed-60 的 ID3 为 39.7%–89.2%，dynamic-60 的 ID2 为 5.7%–51.0%；因此三题合计的 17/30 与 21/30 主要是题目差异和有限重复共同形成的描述性结果，不能外推为所有任务上的稳健优势。",
    )
    _body(
        document,
        "多数正确的判定规则是严格多数：4 个 Agent 中至少 3 票与正确答案一致才记为正确；2∶2 平票记为错误，不进行事后随机打破。冻结轨迹中出现的 2∶2 终局因此被保留为错误结果，而不是被隐藏或改判。",
    )

    _heading(document, "6.6.4 成对比较与 McNemar 检验口径", level=3)
    pair_rows = []
    for item in paired_comparisons["result"]:
        pair_rows.append(
            [
                f"{item['condition_a']} vs {item['condition_b']}",
                str(item["pairs"]),
                f"{item['same_pair_seed']}/{item['pairs']}",
                f"{item['same_assignment_fingerprint']}/{item['pairs']}",
                f"{item['a_only']}/{item['b_only']}",
                str(item["discordant"]),
            ]
        )
    _table_caption(document, "表 13  成对输入与不一致结果计数")
    _table(
        document,
        ["比较", "匹配对数", "相同 pair_seed", "相同事实分配", "A/B 独有正确", "discordant"],
        pair_rows,
        [2500, 1100, 1500, 1700, 1600, 960],
        font_size=7.0,
    )
    _body(
        document,
        "每一对按 task_id + repetition 匹配，并核验相同 pair_seed 与 assignment_fingerprint；例如 fixed-60 vs dynamic-60 为 30/30 对齐，A 独有正确 0 次、B 独有正确 4 次、discordant=4。表 7 的 p 值是基于 discordant 对的双侧精确 McNemar 检验（等价于二项检验），不是独立样本检验。配对输入相同并不意味着 DeepSeek 收到同步 generation seed；因此该检验控制了任务和事实分配，不能消除后端生成随机性。",
    )

    _heading(document, "6.6.5 structured-12 的定义与可复查 Prompt", level=3)
    _body(
        document,
        "fixed-12 与 structured-12 都发送 12 条公开消息、使用相同任务、模型、事实分配和最终投票口径。fixed-12 是 3 轮普通轮转；structured-12 是 2 轮事实交换加 1 轮证据总结，每轮仍由 4 个 Agent 依次发言。structured-12 不机械注入私有事实，也不使用 LLM 选择器，因此表 7 的比较对象是公开发言 Prompt 结构，而不是总计算预算完全相同的实验。",
    )
    _append_code_block(document, STRUCTURED_PROTOCOL_PROMPT, font_size=6.5)

    _heading(document, "6.6.6 固定与动态的预算口径", level=3)
    fixed_budget, dynamic_budget = public_speech_budget["by_condition"]
    budget_rows = [
        [
            fixed_budget["condition"],
            "60（每个 Agent 15）",
            str(fixed_budget["logical_response_slots_per_run"]),
            "60（15 轮 × 4 个 shadow vote；不进入公共历史）",
            "132 次中 29 次；133 次中 1 次（JSON 修复）",
        ],
        [
            dynamic_budget["condition"],
            "60（每个 Agent 15）",
            str(dynamic_budget["logical_response_slots_per_run"]),
            "0",
            "72 次中 30 次",
        ],
    ]
    _table_caption(document, "表 14  fixed-60 与 dynamic-60 的公开发言和总调用口径")
    _table(
        document,
        ["条件", "公开发言", "逻辑模型响应槽/运行", "额外非公开调用", "实际 API 请求分布"],
        budget_rows,
        [1300, 1800, 1900, 2550, 1810],
        font_size=6.8,
    )
    _body(
        document,
        "本比较匹配的是同公开发言预算，而非总模型调用数或 token 预算：两种条件均为 60 条公开发言、每个 Agent 15 条。fixed-60 的 132 个逻辑模型响应槽包含 4 个前测投票、60 条公开发言、15 轮 × 4 个 shadow vote、4 个后测投票和 4 个全信息投票；dynamic-60 的 72 个逻辑模型响应槽不含 shadow vote。shadow vote 仅用于离线诊断，不进入公共历史、不反馈给后续生成。动态选择器自身为 0 次 LLM 调用。因此 fixed-60 与 dynamic-60 不是等计算预算实验，21/30 对 17/30 的方向不能被解释为纯粹的调度器因果效果；本比较只回答在相同公开发言次数下，协议方向是否值得继续研究。",
    )

    _heading(document, "6.6.7 动态选择器的权限边界", level=3)
    _body(
        document,
        "选择器的实际打分公式为：" + selector_formula["score_formula"] + "。五个量均归一化到 [0,1]，权重和为 1；它们分别表示当前立场分歧、本人事实未披露比例、与未披露事实相关的新讨论、需要回应的新跨 Agent 证据，以及距上次发言的等待程度。若总分相同，依次按剩余配额、原始等待轮数和 agent_id 做确定性平局处理。",
    )
    _body(
        document,
        "0.30、0.30、0.15、0.15、0.10 是运行前固定的可解释规则权重，不是根据这三道题的结果调出来的参数；本版没有做五因子消融、权重敏感性或样本外验证。因此 dynamic-60 只应被视为带特权信息的探索性诊断调度器，不能被表述为已经优化完成的公平基线或因果干预。",
    )
    _append_code_block(
        document,
        "d_i = disagreement; u_i = undisclosed; r_i = related_discussion; q_i = response_due; w_i = waiting\n"
        "tie-break: weighted_total ↓, remaining_quota ↓, raw_waiting ↓, agent_id ↑",
        font_size=7.2,
    )
    _body(
        document,
        "五因子选择器是中心化、内容感知且带特权信息的诊断调度器：它可读取完整私有事实分配，计算未披露、相关讨论、回应到期等分数；它不读取正确答案，也不把原始私有事实直接注入 Agent prompt。它因此不是普通去中心化 MAS 的公平基线，更接近一个知道“哪些信息还没被说出”的 oracle-like 调度器；结果只说明这种受限机制在本地条件下值得比较。",
    )

    _heading(document, "6.6.8 三条可追溯错误链路卡", level=3)
    cards = closure["causal_cards"]
    card_rows = [
        [
            "FM-2.4 候选（输出级证据）",
            f"{cards[0]['run_id']}\nID2 / fixed-60 / rep-0",
            "两条关键事实未在所有者公开消息中出现：East Town 隧道内卡住补给车；大火阻断补给车和其他交通。最终四票均为 East Town。",
            "只确认输出层面事实未公开；可作为 FM-2.4 候选，不把它写成内部因果机制。",
        ],
        [
            "错误解释",
            f"{cards[1]['run_id']}\nID2 / fixed-reveal-all / rep-1",
            "消息 e0528435edaa8576 机械注入“补给车卡在隧道”；随后 b5a31c876a93aea6 说“the tunnel is clear”，最终四票 East Town。",
            "确认已公开证据与后续输出存在直接矛盾。",
        ],
        [
            "披露后未落实",
            f"{cards[2]['run_id']}\nID3 / fixed-60 / rep-0",
            "四条事实均被审计为已披露。d85fde011965a482 说“walking trails are closed”；随后 b8dd85f9f7bf206d 又指出 driveway 被泥石流阻断，最终仍四票 North Hill。",
            "确认最终行动没有一致使用已披露证据。",
        ],
    ]
    _table_caption(document, "表 15  冻结轨迹中的代表性错误链路卡")
    _table(
        document,
        ["候选环节", "运行位置", "事实—消息—结果", "结论边界"],
        card_rows,
        [1100, 2100, 3900, 2260],
        font_size=6.9,
    )
    _body(
        document,
        "三条卡不是按最终结果挑选的宣传性案例，而是按冻结提取器中的固定检索规则选出的首个匹配运行：第一条要求 task2/fixed-60 中出现错误多数且至少一条事实未披露；第二条要求 task2/fixed-reveal-all 中全披露、最终错误且出现直接矛盾；第三条要求 task3/fixed-60 中全披露、最终错误且晚到消息仍指出路径受阻或需验证。只有第一行作为 MAST FM-2.4 的输出级证据候选。FM-2.5 还需要把“哪个 Agent 的行为导致了错位”与后续责任归因稳定对应；FM-2.6 还需要证明协同关系或信息同步本身，而不是只看到错误结果。因此后两行只能称为本项目的输出级错误链路类别，不能直接写成 MAST FM-2.5 或 FM-2.6，也不是对模型内部心理状态的证明。三条卡均不能用于估计各机制对错误率的独立因果贡献。",
    )


def _report_boundaries_and_prompts(
    document: DocumentType,
    closure: dict[str, Any],
    self_report_summary: dict[str, Any],
) -> None:
    _heading(document, "6.7 跨实现对标与 Prompt 可复查性", level=2)
    _body(
        document,
        "官方 HiddenBench 代码使用作者自写 Python simulator 和 GPT-4.1；本地使用 MAF 的 Agent.run() 作为模型调用执行适配层，并由项目代码实现群聊轮转、历史拼接、投票、Reveal 和审计。因此本地结果是跨实现的方向性验证，不是严格逐字、逐协议复现，也不能把差异单独归因于模型或框架。",
    )
    _body(document, "复现元数据：")
    _append_code_block(
        document,
        "run commit = 80f621b223c2a7f0f88434a083c5cf5268d52b51\n"
        "frozen code commit = 1aa577992d3abb3c83e5aeb7ce5475de7100e7af\n"
        "atomic-audit code commit = e1b32d3c217960bc331c0c751217011e92dd9d2b\n"
        "agent-framework-core >= 1.12.1, < 2\n"
        "agent-framework-orchestrations >= 1.0.1, < 2\n"
        "agent-framework-openai >= 1.11.0, < 2",
        font_size=6.6,
    )
    _body(
        document,
        "冻结运行没有记录解析后的精确包版本，因此本报告不声称已完成版本级归因。运行配置固定为 deepseek-v4-flash、temperature=0、thinking=disabled；DeepSeek 未接收同步 generation seed，因此这里只能保证任务、事实分配和协议输入的配对。本稿交付包将报告、生成脚本、自报审计 JSONL、闭环证据快照和 SHA-256 清单统一放入 reports/data/hiddenbench-teacher-review-20260819.manifest.json；旧版 Release 不包含 2026-08-19 新增的自报审计文件，新提交的固定 commit 以该清单为入口。",
    )
    _body(
        document,
        "披露率的证据边界也需要单独说明：本版没有把模型辅助标签冒充人工金标准，披露率只用于比较信息是否进入公共消息。若要把披露率升级为正式标注指标，还需要独立人工标注者按同一规则复核并报告一致率、精确率和召回率；因此本文的主要结论仍以冻结运行的最终正确率、投票和可追溯消息证据为主。",
    )
    comparison_rows = [
        ["执行", "作者自写 simulator", "MAF Agent.run 调用层 + 项目自写协议"],
        ["模型", "GPT-4.1", "deepseek-v4-flash"],
        ["讨论首轮", "注入初始投票和理由", "不注入初始票"],
        ["后续历史", "各 Agent 自己历史 + 他人最近消息", "完整公共历史显式拼接到 user prompt"],
        ["最终投票可见范围", "默认最后一轮消息", "完整公共讨论"],
        ["API 参数", "官方结果的原始参数见数据集", "temperature=0；thinking=disabled；generation seed 未传递"],
        ["样本量", "隐藏基线每题 30；Reveal-All 每题 10", "各本地条件每题 10"],
    ]
    _table_caption(document, "表 16  官方与本地实现的主要协议差异")
    _table(
        document,
        ["项目", "官方 HiddenBench", "本地条件"],
        comparison_rows,
        [1600, 3600, 4160],
        font_size=7.2,
    )
    _body(
        document,
        "方向上，两边都观察到部分信息条件下会失败，而完整信息可得后表现提高；但逐题数值不同：官方隐藏基线 ID1/ID2/ID3 为 11/30、4/30、6/30，本地 fixed-60 为 10/10、0/10、7/10；官方 Reveal-All 为 10/10、9/10、10/10，本地“官方 Reveal-All 时序兼容的本地条件（非逐字复现）”为 10/10、10/10、10/10。ID2 本地更差，ID1、ID3 本地更好。模型、消息组织、投票范围和样本量同时变化，因此这里只报告方向与差异，不作单因素归因。",
    )
    _body(
        document,
        "三题各重复 10 次的 n=30 是运行级样本，不是 30 个相互独立的任务；三题还共享同一撤离背景。因此 Wilson 区间和配对检验只能支持这三题上的探索性稳定性描述，不能外推到 HiddenBench 全部 65 题或一般 MAS。",
    )

    source_hashes = closure["source_sha256"]
    _body(document, "冻结原始证据的 SHA-256：")
    _append_code_block(
        document,
        "confirmatory JSONL = "
        f"{source_hashes['artifacts/hiddenbench-confirmatory-20260804.jsonl']}\n"
        "atomic-disclosure audits = "
        f"{source_hashes['artifacts/hiddenbench-confirmatory-20260804.audits.jsonl']}",
        font_size=6.6,
    )
    _body(document, "补充模型自报审计 JSONL 的 SHA-256：")
    _append_code_block(
        document,
        f"{self_report_summary['sha256']}\n{self_report_summary['path']}",
        font_size=6.6,
    )
    _body(
        document,
        "这些哈希对应本报告所有百分比、配对计数和案例卡的输入；交付时以 reports/data/hiddenbench-teacher-review-20260819.manifest.json 作为证据入口，报告修订本与生成脚本、自报审计和证据快照固定在同一提交中。",
    )

    example = closure["prompt_example"]
    _heading(document, "6.7.1 ID2 / fixed-60 / rep-0 的真实填充示例", level=3)
    _body(
        document,
        f"下面不是抽象模板，而是冻结运行 {example['run_id']} 的实际审计输入与输出摘要。该运行共有 {example['public_message_count']} 条公共消息；为控制篇幅，表 18 展示送入 B.3 审计 Prompt 的前四条消息，完整 60 条消息仍保存在原始 JSONL。审计模型逐条返回 disclosed=true/false，再由程序汇总为 {example['audit_disclosure_rate']:.1%}。",
    )
    fact_rows = [
        [fact["fact_id"], fact["owner_agent_id"], fact["claim"]]
        for fact in example["private_facts"]
    ]
    _table_caption(document, "表 17  真实运行中的四条私有事实（审计输入）")
    _table(
        document,
        ["fact_id", "owner", "claim"],
        fact_rows,
        [2500, 1200, 5660],
        font_size=6.8,
    )
    message_rows = [
        [message["message_id"], message["agent_id"], message["content"]]
        for message in example["public_messages_excerpt"]
    ]
    _table_caption(document, "表 18  真实公共消息输入位置（前 4/60 条）")
    _table(
        document,
        ["message_id", "agent", "public message"],
        message_rows,
        [1900, 1000, 6460],
        font_size=6.8,
    )
    judgment_rows = [
        [
            judgment["fact_id"],
            "true" if judgment["disclosed"] else "false",
            ", ".join(judgment["evidence_message_ids"]) or "—",
            judgment["evidence_quote"] or "—",
            judgment["reason"],
        ]
        for judgment in example["judgments"]
    ]
    _table_caption(document, "表 19  AI 原子审计真实输出（逐条判断）")
    _table(
        document,
        ["fact_id", "disclosed", "evidence_message_ids", "evidence_quote", "reason"],
        judgment_rows,
        [1900, 850, 1800, 1900, 2910],
        font_size=6.3,
    )
    _body(
        document,
        "这个例子中，agent-a 与 agent-c 的事实被判定为 disclosed=true，agent-b 与 agent-d 的事实被判定为 disclosed=false；因此程序计算 2/4=50.0%。这说明“AI 自己输出百分比”并不是本实验的原始输入：AI 输出的是可追溯的逐条标签和证据，百分比由程序确定性汇总。",
    )
    _body(
        document,
        '实际 JSON 输出的关键字段示例为：{"fact_id": "atomic-fact:fdb95995b31ce89325cc", "disclosed": false, "evidence_message_ids": [], "evidence_quote": ""}。',
    )

    turn = example["discussion_turn"]
    _heading(document, "6.7.2 真实 Agent 讨论 Prompt 与输出", level=3)
    _body(
        document,
        f"B.1/B.2 展示的是模板结构；下面补充同一冻结运行 {example['run_id']} 中 agent-b 第 1 轮的完整实际调用。它与 B.3 审计 Prompt 不同：前者是 Agent 生成公开发言，后者是审计模型逐条判断披露。",
    )
    _table_caption(document, "表 20  真实 Agent 调用元数据")
    _table(
        document,
        ["字段", "实际值"],
        [
            ["message_id", turn["message_id"]],
            ["round / agent", f"{turn['round_index']} / {turn['agent_id']}"],
            ["model", turn["model"]],
            ["temperature / thinking", f"{turn['temperature']} / {turn['thinking']}"],
        ],
        [2500, 6860],
        font_size=7.0,
    )
    _body(document, "实际 SYSTEM prompt：", bold_lead="SYSTEM prompt：")
    _append_code_block(document, turn["system_prompt"], font_size=6.5)
    _body(document, "实际 USER prompt：", bold_lead="USER prompt：")
    _append_code_block(document, turn["user_prompt"], font_size=6.5)
    _body(document, "模型实际公开输出：", bold_lead="模型实际公开输出：")
    _append_code_block(document, turn["actual_output"], font_size=6.8)

    _heading(document, "6.7.3 补充模型自报披露率 Prompt", level=3)
    _body(
        document,
        "该 Prompt 不替换冻结主审计，只用于回应“让 AI 自己说披露百分比”的要求。每次请求同时保存逐条证据判断、模型自报计数/分母/百分比，以及程序复算值；若二者不一致，则该运行标记为不一致。",
    )
    _append_code_block(document, RUNTIME_SELF_REPORT_PROMPT, font_size=6.3)
    example = self_report_summary["example"]
    _body(
        document,
        f"真实自报字段示例：运行 {example['run_id']}（{example['key']['condition']} / ID{example['key']['task_id']} / rep-{example['key']['repetition']}）：",
    )
    _append_code_block(
        document,
        f"reported_disclosure_count = {example['reported_disclosure_count']}\n"
        f"reported_disclosure_denominator = {example['reported_disclosure_denominator']}\n"
        f"reported_disclosure_rate = {example['reported_disclosure_rate']:.1%}\n"
        f"program_recomputed_rate = {example['program_rate']:.1%}",
        font_size=6.8,
    )
    _body(
        document,
        "单智能体参考组的 Prompt 口径也固定：局部信息单 Agent 使用同一任务系统 Prompt、共享事实和一条私有事实，直接调用最终投票 Prompt，公共讨论为空；全信息单 Agent 使用同一系统 Prompt，但把四条私有事实全部放入上下文，仍直接调用最终投票 Prompt，公共讨论为空。两者各自只做一次无讨论投票，不应与四 Agent、60 条公开发言的多智能体条件混称为等预算基线。",
    )

def _conclusion(document: DocumentType) -> None:
    _heading(document, "7 总结")
    _body(
        document,
        "本报告从冻结数据重算局部信息单智能体、全信息无讨论单智能体和 fixed-60 多智能体基线，并将三类代表性错误落实到事实、消息 ID 和最终投票。fixed-60 与 dynamic-60 在相同 60 条公开发言下分别为 17/30 与 21/30，但 p=0.125，且动态选择器拥有私有事实可见权、总调用数也不同，因此这只是探索性方向，不是已证实的治理增益。",
    )
    _body(
        document,
        "现有运行显示，多智能体错误不仅可能来自“没说出来”，还可能发生在“说出来以后被反向解释”或“说出来但没有改变最终行动”。这三类问题分别对应信息公开、证据解释和最终行动环节。",
    )
    _body(
        document,
        "需要特别保留的边界是：本文的来源事实包披露率来自模型辅助审计，补充自报审计证明了模型能从自己的逐条判断中汇总百分比，但没有替代人工金标准；HiddenBench 原论文与本地实现同时更换了模型、框架和消息协议，当前结果也不能完成模型与框架的单因素归因。后续若要把披露率作为正式测量指标，应先完成独立人工双盲复核，并补充 clause-level 与 group-level 敏感性分析；在这些工作完成前，本文应被理解为正确性诊断与治理框架原型，而不是已经闭环验证的部署系统。",
    )
    _callout(
        document,
        "本报告结论：",
        "多智能体治理应把最终正确率放在首位，并按“披露—利用—解释—行动”逐环节留下可核验的证据。",
        gold=True,
    )


def _build_marked_document(
    root: Path,
    evidence: dict[str, Any],
    closure: dict[str, Any],
    self_report_summary: dict[str, Any],
    references: list[dict[str, Any]],
    output: Path,
) -> governance.CitationTracker:
    figure = root / governance.GOVERNANCE_FIGURE
    if not figure.exists():
        raise FileNotFoundError(figure)
    citations = governance.CitationTracker(references)
    document = Document()
    _configure_paper(document)
    governance._configure_identity(document)
    _title_and_abstract(document, evidence, closure, self_report_summary)
    governance._introduction(document, citations)
    governance._error_phenomena_and_prior_work(document, citations)
    _mast_fc2_definitions(document, citations)
    governance._governance_system(document, evidence, figure)
    governance._contribution_boundaries(document)
    governance._experiment_design(document, evidence)
    governance._results_and_attribution(document, evidence)
    _closure_supplement(document, evidence, closure, self_report_summary)
    _report_boundaries_and_prompts(document, closure, self_report_summary)
    _conclusion(document)
    governance._references(document, citations)
    governance._appendices(document, evidence)
    _keep_completed_content_only(document)
    _validate_tables(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    return citations


def build_hiddenbench_closure_report(
    root: Path,
    output: Path,
    desktop_output: Path | None,
) -> Path:
    """Create the supplement and leave the frozen 2026-08-17 paper untouched."""
    root = root.resolve()
    output = output if output.is_absolute() else root / output
    desktop_output = (
        desktop_output
        if desktop_output is None or desktop_output.is_absolute()
        else root / desktop_output
    )
    governance._assert_preserved(root)
    _assert_preserved_report(root)
    evidence = _load_json(root / EVIDENCE_PATH)
    closure = _load_json(root / CLOSURE_EVIDENCE_PATH)
    self_report_rows = _load_jsonl(root / SELF_REPORT_PATH)
    frozen_audit_rows = _load_jsonl(root / FROZEN_AUDIT_PATH)
    self_report_summary = _self_report_summary(
        self_report_rows,
        frozen_audit_rows,
        closure,
    )
    references: list[dict[str, Any]] = _load_json(root / REFERENCE_PATH)
    with tempfile.TemporaryDirectory(prefix="maf-closure-supplement-") as temp_dir:
        marked = Path(temp_dir) / "marked.docx"
        citations = _build_marked_document(
            root,
            evidence,
            closure,
            self_report_summary,
            references,
            marked,
        )
        _patch_true_footnotes(
            marked,
            output,
            [_short_note(item) for item in citations.ordered_references()],
        )
    if desktop_output is not None:
        desktop_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, desktop_output)
    governance._assert_preserved(root)
    _assert_preserved_report(root)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the HiddenBench correctness-governance closure supplement."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("reports") / REPORT_NAME)
    parser.add_argument("--desktop-output", type=Path)
    args = parser.parse_args()
    built = build_hiddenbench_closure_report(
        args.root,
        args.output,
        args.desktop_output,
    )
    print(built)


if __name__ == "__main__":
    main()
