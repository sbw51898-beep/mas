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
from docx.shared import Pt

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
REPORT_NAME = "基于MAF的多智能体正确性治理与错误链路分析_闭环补充版_2026-08-17.docx"
CLOSURE_EVIDENCE_PATH = Path("reports/data/hiddenbench-closure-evidence-20260817.json")
PRESERVED_REPORT = Path("reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx")
PRESERVED_REPORT_SHA256 = "21ac7bcbde08b17eb5f1978af35192e03af72642ae9d34fdf4c8c35e790a048f"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_preserved_report(root: Path) -> None:
    current = hashlib.sha256((root / PRESERVED_REPORT).read_bytes()).hexdigest()
    if current != PRESERVED_REPORT_SHA256:
        raise ValueError("the frozen 2026-08-17 final paper must not be overwritten")


def _title_and_abstract(
    document: DocumentType,
    evidence: dict[str, Any],
    closure: dict[str, Any],
) -> None:
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(14)
    title.paragraph_format.space_after = Pt(8)
    _font(
        title.add_run("基于 MAF 的多智能体正确性治理与错误链路分析（闭环补充版）"),
        18,
        bold=True,
        color=governance.NAVY,
    )
    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.paragraph_format.space_after = Pt(18)
    _font(meta.add_run("补充实验报告 | 2026 年 8 月 17 日"), 10.5, color=governance.MUTED)

    _heading(document, "摘要")
    totals = closure["single_agent_comparison"]["overall"]
    abstract = (
        "多智能体系统的讨论目标应是最终决策正确，而不是更快形成共识。"
        "既有 HiddenBench 复现已显示，私有信息能否及时公开、被正确理解并落实到行动，会共同影响最终结果。"
        "为回应实验中单智能体对照、错误链路可追溯性和人工复核入口尚未闭环的问题，本文只使用冻结确认性 JSONL 与原子披露审计重新提取证据。"
        f"在相同 DeepSeek 模型和三题各 10 次范围内，局部信息单智能体、全信息无讨论单智能体和 fixed-60 多智能体分别为 {totals['single_local']}、{totals['single_full_profile']} 和 {totals['fixed_60_multi_agent']}。"
        "本文进一步给出未披露、已披露但与证据矛盾、以及已披露但未落实到最终行动的三条消息级链路卡。"
        "同时生成双人真人盲审签核包和保守合并器，但未把模型复核写成人工金标准，也未把未运行的 GPT-4.1 解耦实验写成结果。"
        "因此，本补充版的贡献是把可自动复核的部分固定为可追溯证据，并把仍需真人或外部接口支持的结论边界明确保留。"
    )
    _body(document, abstract)
    keywords = document.add_paragraph()
    keywords.paragraph_format.space_after = Pt(12)
    _font(keywords.add_run("关键词："), 10.5, bold=True)
    _font(
        keywords.add_run(
            "多智能体系统；正确性治理；单智能体对照；信息披露；双人盲审；HiddenBench"
        ),
        10.5,
    )
    _callout(
        document,
        "补充版边界：",
        "已完成的是冻结数据的重算、可追溯链路和真人盲审工具；真人标签与模型—框架解耦结果仍待真实外部输入。",
        gold=True,
    )


def _closure_supplement(document: DocumentType, closure: dict[str, Any]) -> None:
    comparison = closure["single_agent_comparison"]
    _heading(document, "6.6 闭环补充：单智能体对照、错误链路与人工复核入口", level=2)
    _body(
        document,
        "本节不重新运行模型，也不改变冻结实验。所有数值来自 artifacts/hiddenbench-confirmatory-20260804.jsonl 与对应原子披露审计；其目的只是把老师追问的基线、规则、证据位置和未完成边界明确写出。",
    )

    _heading(document, "6.6.1 同模型单智能体正式对照", level=3)
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
    _table_caption(document, "表 9  冻结确认性数据中的三种同模型基线（多数正确次数）")
    _table(
        document,
        ["任务", "局部信息单 Agent", "全信息单 Agent", "fixed-60 多 Agent"],
        rows,
        [1000, 2700, 3000, 2660],
        font_size=8.1,
    )
    _body(
        document,
        "局部信息单智能体为 4/30，全信息无讨论单智能体为 20/30，fixed-60 多智能体为 17/30。这里的“全信息无讨论”不是额外新跑的一组 API 实验，而是每次 single-local 运行内部独立保存的 full_profile_votes：同一模型看到全部事实后直接投票，不经过公共讨论。它说明三题中讨论并没有自动超过信息充分时的单智能体上限。",
    )

    _heading(document, "6.6.2 普通披露规则与为何继续到 60 次发言", level=3)
    _body(
        document,
        "普通条件下不随机、不强制披露：每个 Agent 持有一条私有事实，是否在公开发言中说出、如何转述，均由模型在自然发言时生成。只有 Reveal-All 条件才由系统把私有事实机械注入公开消息。因此普通披露率描述的是模型在讨论中的信息交换行为，不是预先抽签决定的比例。",
    )
    _body(
        document,
        "fixed-60 固定为 15 轮 × 4 个 Agent。即使前几轮看似已有一致，也继续运行，是为了观察迟到证据能否纠错、关键事实是否被后续使用、立场是否变化，以及最终投票是否稳定。它是诊断协议，不是“早有共识仍继续讨论就一定更正确”的主张，也不能据此推导早停策略。",
    )

    _heading(document, "6.6.3 三条可追溯错误链路卡", level=3)
    cards = closure["causal_cards"]
    card_rows = [
        [
            "未披露",
            f"{cards[0]['run_id']}\nID2 / fixed-60 / rep-0",
            "两条关键事实未在所有者公开消息中出现：East Town 隧道内卡住补给车；大火阻断补给车和其他交通。最终四票均为 East Town。",
            "只确认输出层面事实未公开；不把它单独写成完整因果归因。",
        ],
        [
            "错误解释",
            f"{cards[1]['run_id']}\nID2 / fixed-reveal-all / rep-1",
            "消息 e0528435edaa8576 机械注入“补给车卡在隧道”；随后 b5a31c876a93aea6 说“the tunnel is clear”，最终四票 East Town。",
            "确认已公开证据与后续输出矛盾；内在推理机制仍需真人编码。",
        ],
        [
            "披露后未落实",
            f"{cards[2]['run_id']}\nID3 / fixed-60 / rep-0",
            "四条事实均被审计为已披露。d85fde011965a482 说“walking trails are closed”；随后 b8dd85f9f7bf206d 又指出 driveway 被泥石流阻断，最终仍四票 North Hill。",
            "确认最终行动没有一致使用已披露证据；需真人区分忽略与误解。",
        ],
    ]
    _table_caption(document, "表 10  冻结轨迹中的代表性错误链路卡")
    _table(
        document,
        ["候选环节", "运行位置", "事实—消息—结果", "结论边界"],
        card_rows,
        [1100, 2100, 3900, 2260],
        font_size=6.9,
    )
    _body(
        document,
        "上述三条卡分别对应“信息没有进入公共讨论”“公开证据被输出层面的相反说法覆盖”和“证据出现后没有被最终行动一致采用”。它们不是对模型内部心理状态的证明，也不能用于估计三个机制各自对错误率的独立因果贡献。",
    )

    _heading(document, "6.6.4 真人双盲审阅的可执行入口与当前状态", level=3)
    _body(
        document,
        "已生成审阅者 A/B 两份空白签核表：二者包含相同的 144 个盲化案例但顺序不同，表中不展示既有 AI 标签或规则标签。合并器会检查两位审阅者的真实姓名声明、日期、独立完成声明、每题明确“是/否”及“是”所附的消息证据。若有缺项、模型工具名或无效引句，程序拒绝计算指标。",
    )
    _body(
        document,
        "真人双盲审阅尚未完成。即便两位审阅者都完成表格，若标签存在分歧，合并器只报告人工一致率和分歧清单；AI 精确率、召回率及修订披露率仍等待真人仲裁，避免用任一位审阅者的单方标签冒充最终人工金标准。",
    )

    _heading(document, "6.6.5 模型与框架解耦的边界", level=3)
    _body(
        document,
        "GPT-4.1（或同等可验证接口）尚不可用，因此没有新增的“MAF + GPT-4.1”或“作者模拟器 + DeepSeek”运行。当前跨实现比较同时变化了模型、框架、消息组织和部分运行设置，只能描述结论方向是否复现，不能把数值差异归因给某一个单独因素。",
    )


def _conclusion(document: DocumentType) -> None:
    _heading(document, "7 总结与展望")
    _body(
        document,
        "本补充版完成了三个可自动验证的闭环：从冻结数据重算单智能体、全信息单智能体和 fixed-60 基线；把三类候选错误落实到事实、消息 ID 和最终投票；并提供不泄露既有标签的双人真人盲审签核与保守合并流程。",
    )
    _body(
        document,
        "现有证据说明，多智能体错误不仅可能来自“没说出来”，还可能发生在“说出来以后被反向解释”或“说出来但没有改变最终行动”。但这些是运行级、输出级证据，不等于已经获得全样本的机制比例或单因素因果效应。",
    )
    _body(
        document,
        "后续应优先由两名真实审阅者完成 144 项盲审并处理分歧，再在可验证接口条件下补齐模型—框架解耦。完成这两步后，才能把人工一致率、AI 精确率、召回率和修订披露率作为正式确认性结果，并进一步评估不同治理干预的稳健性。",
    )
    _callout(
        document,
        "当前最稳妥的结论：",
        "多智能体治理应把最终正确率放在首位，并按“披露—利用—解释—行动”逐环节留下可核验的证据；没有真人金标准和解耦实验的部分，应明确保留为待完成。",
        gold=True,
    )


def _build_marked_document(
    root: Path,
    evidence: dict[str, Any],
    closure: dict[str, Any],
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
    _title_and_abstract(document, evidence, closure)
    governance._introduction(document, citations)
    governance._error_phenomena_and_prior_work(document, citations)
    governance._governance_system(document, evidence, figure)
    governance._contribution_boundaries(document)
    governance._experiment_design(document, evidence)
    governance._results_and_attribution(document, evidence)
    _closure_supplement(document, closure)
    _conclusion(document)
    governance._references(document, citations)
    governance._appendices(document, evidence)
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
    references: list[dict[str, Any]] = _load_json(root / REFERENCE_PATH)
    with tempfile.TemporaryDirectory(prefix="maf-closure-supplement-") as temp_dir:
        marked = Path(temp_dir) / "marked.docx"
        citations = _build_marked_document(
            root,
            evidence,
            closure,
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
