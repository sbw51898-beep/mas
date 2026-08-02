from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import statistics
from collections import Counter
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.document import Document as DocumentType
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
SUMMARY_CSV = ARTIFACTS / "hiddenbench-stability-20260729.summary.csv"
RUNS_JSONL = ARTIFACTS / "hiddenbench-stability-20260729.jsonl"
AUDIT_JSONL = ARTIFACTS / "hiddenbench-stability-20260729.ai-disclosure.jsonl"
DISAGREEMENTS_CSV = (
    ARTIFACTS / "hiddenbench-stability-20260729.disagreements.csv"
)
BLIND_REVIEW_SUMMARY = (
    ARTIFACTS
    / "hiddenbench-stability-20260729.blind-review.summary.json"
)
BLIND_REVIEW_V1_SUMMARY = (
    ARTIFACTS
    / "hiddenbench-stability-20260729.blind-review.v1.summary.json"
)
BLIND_REVIEW_GPT_SUMMARY = (
    ARTIFACTS
    / "hiddenbench-stability-20260729.blind-review.gpt.summary.json"
)
GATE_JSON = ARTIFACTS / "hiddenbench-stability-20260729.gate.json"
MANIFEST_JSON = ARTIFACTS / "hiddenbench-stability-20260729.manifest.json"

OUTPUT = (
    ROOT
    / "reports"
    / "AI披露率与四题重复稳定性实验报告_2026-07-30.docx"
)
DESKTOP_OUTPUT = (
    Path.home()
    / "Desktop"
    / "AI披露率与四题重复稳定性实验报告_2026-07-30.docx"
)
WORK = ROOT / ".tmp" / "ai-disclosure-stability-report"

TASKS = {
    1: {
        "short": "撤离路线",
        "name": "evacuation_west_city",
        "question": "在三条受灾路线中选择仍可通行的撤离方向",
        "answer": "West City",
    },
    5: {
        "short": "校长候选人",
        "name": "baker_2010",
        "question": "根据分散在四名成员手中的履历证据选择候选人",
        "answer": "Roberts",
    },
    7: {
        "short": "供应商选择",
        "name": "graetz_et_al_1998",
        "question": "综合多项RFP标准选择满足条件的供应商",
        "answer": "Starlight Incorporated",
    },
    25: {
        "short": "应急避难所",
        "name": "select_emergency_shelter",
        "question": "综合污染、供电和道路状态选择安全避难所",
        "answer": "Station Delta",
    },
}

CONDITION_LABEL = {"fixed": "固定轮转", "dynamic": "动态发言"}

NAVY = "17365D"
BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
LIGHT_BLUE = "EAF2F8"
PALE_BLUE = "F4F8FC"
LIGHT_GRAY = "F2F4F7"
MID_GRAY = "6B7280"
DARK_GRAY = "333333"
WHITE = "FFFFFF"
GREEN = "2E7D32"
ORANGE = "D97706"

FONT_ASCII = "Calibri"
FONT_EAST_ASIA = "Microsoft YaHei"

REPO_COMMIT = "f12aa02ef89eda1a46c74a7fc15cd98c73caf47c"
REPO_COMMIT_URL = (
    "https://github.com/sbw51898-beep/mas/commit/"
    f"{REPO_COMMIT}"
)
REPO_TREE_URL = (
    "https://github.com/sbw51898-beep/mas/tree/"
    f"{REPO_COMMIT}"
)
RUN_COMMIT = "723fb179596d6e0ed94a08a866a1c3b9e01b7d5c"
RUN_COMMIT_URL = (
    "https://github.com/sbw51898-beep/mas/commit/"
    f"{RUN_COMMIT}"
)
HIDDENBENCH_CODE_COMMIT = "3be6ca16973e4fb751ffc0dfb7eb11f2d28335d1"
HIDDENBENCH_CODE_URL = (
    "https://github.com/Yassellee/HiddenBench_ICML/commit/"
    f"{HIDDENBENCH_CODE_COMMIT}"
)
HIDDENBENCH_PAPER_URL = "https://arxiv.org/abs/2505.11556"
HIDDENBENCH_DATA_URL = (
    "https://huggingface.co/datasets/YuxuanLi1225/HiddenBench"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def _pearson(xs: list[float], ys: list[float]) -> float:
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    )
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs)
        * sum((y - mean_y) ** 2 for y in ys)
    )
    return numerator / denominator


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive total")
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z**2 / (4 * total**2)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _exact_mcnemar_p(fixed_wins: int, dynamic_wins: int) -> float:
    discordant = fixed_wins + dynamic_wins
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(fixed_wins, dynamic_wins) + 1)
    ) / (2**discordant)
    return min(1.0, 2 * tail)


def _verify_inputs() -> dict:
    required = [
        SUMMARY_CSV,
        RUNS_JSONL,
        AUDIT_JSONL,
        DISAGREEMENTS_CSV,
        GATE_JSON,
        MANIFEST_JSON,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    gate = json.loads(GATE_JSON.read_text(encoding="utf-8"))
    if not gate.get("passed"):
        raise ValueError("Formal stability gate did not pass")
    if len(gate.get("checks", {})) != 13:
        raise ValueError("Expected 13 formal gate checks")

    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = ARTIFACTS / item["path"]
        if path.stat().st_size != item["bytes"]:
            raise ValueError(f"Byte-size mismatch: {path.name}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")
    return {"gate": gate, "manifest": manifest}


def _analyze() -> dict:
    verification = _verify_inputs()
    summary_rows = _load_csv(SUMMARY_CSV)
    if len(summary_rows) != 8:
        raise ValueError("Expected eight task-condition summary rows")

    summaries: dict[tuple[int, str], dict] = {}
    for row in summary_rows:
        task_id = int(row["task_id"])
        condition = row["condition"]
        converted = {
            "task_id": task_id,
            "condition": condition,
            "repetitions": int(row["repetitions"]),
            "ai_disclosure_mean": float(row["ai_disclosure_mean"]),
            "ai_disclosure_std": float(row["ai_disclosure_std"]),
            "rule_disclosure_mean": float(row["rule_disclosure_mean"]),
            "post_majority_correct_count": int(
                row["post_majority_correct_count"]
            ),
            "post_unanimous_count": int(row["post_unanimous_count"]),
            "wrong_consensus_count": int(row["wrong_consensus_count"]),
            "stable_consensus_count": int(row["stable_consensus_count"]),
            "mean_first_stable_consensus_turn": float(
                row["mean_first_stable_consensus_turn"]
            ),
            "mean_post_stable_messages": float(
                row["mean_post_stable_messages"]
            ),
            "ai_rule_agreement": float(row["ai_rule_agreement"]),
            "final_answer_distribution": json.loads(
                row["final_answer_distribution"]
            ),
        }
        summaries[(task_id, condition)] = converted

    audits = _load_jsonl(AUDIT_JSONL)
    if len(audits) != 80:
        raise ValueError("Expected 80 valid AI disclosure audits")
    audit_by_key: dict[tuple[int, str, int], dict] = {}
    audit_requests = 0
    repair_requests = 0
    for row in audits:
        key_data = row["study_key"]
        key = (
            int(key_data["task_id"]),
            key_data["condition"],
            int(key_data["repetition"]),
        )
        audit_by_key[key] = row
        audit_requests += int(row["provider_metadata"]["api_requests"])
        repair_requests += int(row["provider_metadata"]["repair_requests"])
        if len(row["judgments"]) != 4:
            raise ValueError(f"Audit {key} does not contain four judgments")

    run_records = []
    public_messages = 0
    generation_requests = 0
    dynamic_speech_counts: list[dict[str, int]] = []
    selector_reasons: Counter[str] = Counter()
    selector_selected_values: dict[str, list[float]] = {
        name: []
        for name in (
            "disagreement",
            "undisclosed",
            "related_discussion",
            "response_due",
            "waiting",
        )
    }
    with RUNS_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key_data = row["key"]
            key = (
                int(key_data["task_id"]),
                key_data["condition"],
                int(key_data["repetition"]),
            )
            if key not in audit_by_key:
                raise ValueError(f"Missing AI audit for run {key}")
            metrics = row["run"]["metrics"]
            messages = row["run"]["discussion_messages"]
            public_messages += len(messages)
            generation_requests += int(metrics["api_requests"])
            if key[1] == "dynamic":
                counts = Counter(message["agent_id"] for message in messages)
                dynamic_speech_counts.append(dict(counts))
                for event in row["selection_events"]:
                    selected = next(
                        candidate
                        for candidate in event["candidates"]
                        if candidate["selected"]
                    )
                    selector_reasons[selected["tie_break_reason"]] += 1
                    for name in selector_selected_values:
                        selector_selected_values[name].append(
                            float(selected[name])
                        )
            run_records.append(
                {
                    "key": key,
                    "task_id": key[0],
                    "condition": key[1],
                    "repetition": key[2],
                    "ai_disclosure": float(
                        audit_by_key[key]["disclosure_rate"]
                    ),
                    "post_majority_correct": int(
                        bool(metrics["post_majority_correct"])
                    ),
                    "post_unanimous": int(bool(metrics["post_unanimous"])),
                    "post_votes": tuple(
                        vote["vote"] for vote in row["run"]["hidden_post_votes"]
                    ),
                }
            )

    if len(run_records) != 80:
        raise ValueError("Expected 80 formal runs")
    if public_messages != 4800:
        raise ValueError(f"Expected 4800 public messages, got {public_messages}")
    if generation_requests != 5760:
        raise ValueError(
            f"Expected 5760 generation requests, got {generation_requests}"
        )
    if len(dynamic_speech_counts) != 40 or any(
        sorted(counts.values()) != [15, 15, 15, 15]
        for counts in dynamic_speech_counts
    ):
        raise ValueError("Dynamic conditions must contain 15 speeches per agent")

    disclosure_values = [row["ai_disclosure"] for row in run_records]
    correctness_values = [
        row["post_majority_correct"] for row in run_records
    ]
    correlation = _pearson(disclosure_values, correctness_values)

    overall = {}
    for condition in ("fixed", "dynamic"):
        rows = [
            summaries[(task_id, condition)] for task_id in sorted(TASKS)
        ]
        overall[condition] = {
            "runs": sum(row["repetitions"] for row in rows),
            "ai_disclosure_mean": statistics.mean(
                row["ai_disclosure_mean"] for row in rows
            ),
            "correct": sum(
                row["post_majority_correct_count"] for row in rows
            ),
            "wrong_consensus": sum(
                row["wrong_consensus_count"] for row in rows
            ),
            "stable_consensus": sum(
                row["stable_consensus_count"] for row in rows
            ),
            "ai_rule_agreement": statistics.mean(
                row["ai_rule_agreement"] for row in rows
            ),
        }
        overall[condition]["other_incorrect"] = (
            overall[condition]["runs"]
            - overall[condition]["correct"]
            - overall[condition]["wrong_consensus"]
        )
        overall[condition]["correct_ci"] = _wilson_interval(
            overall[condition]["correct"], overall[condition]["runs"]
        )

    paired = {}
    for task_id in sorted(TASKS):
        fixed_wins = 0
        dynamic_wins = 0
        ties = 0
        for repetition in range(10):
            fixed = next(
                row
                for row in run_records
                if row["key"] == (task_id, "fixed", repetition)
            )["post_majority_correct"]
            dynamic = next(
                row
                for row in run_records
                if row["key"] == (task_id, "dynamic", repetition)
            )["post_majority_correct"]
            fixed_wins += fixed > dynamic
            dynamic_wins += dynamic > fixed
            ties += fixed == dynamic
        paired[task_id] = {
            "fixed_wins": fixed_wins,
            "dynamic_wins": dynamic_wins,
            "ties": ties,
            "fixed_ci": _wilson_interval(
                summaries[(task_id, "fixed")]["post_majority_correct_count"],
                10,
            ),
            "dynamic_ci": _wilson_interval(
                summaries[(task_id, "dynamic")]["post_majority_correct_count"],
                10,
            ),
        }

    disagreements = _load_csv(DISAGREEMENTS_CSV)
    blind_review = json.loads(BLIND_REVIEW_SUMMARY.read_text(encoding="utf-8"))
    blind_review_v1 = json.loads(
        BLIND_REVIEW_V1_SUMMARY.read_text(encoding="utf-8")
    )
    blind_review_gpt = json.loads(
        BLIND_REVIEW_GPT_SUMMARY.read_text(encoding="utf-8")
    )
    distribution = Counter(disclosure_values)
    fixed_wins_total = sum(item["fixed_wins"] for item in paired.values())
    dynamic_wins_total = sum(item["dynamic_wins"] for item in paired.values())
    ties_total = sum(item["ties"] for item in paired.values())
    return {
        "verification": verification,
        "summaries": summaries,
        "audits": audits,
        "run_records": run_records,
        "overall": overall,
        "paired": paired,
        "paired_overall": {
            "fixed_wins": fixed_wins_total,
            "dynamic_wins": dynamic_wins_total,
            "ties": ties_total,
            "mcnemar_p": _exact_mcnemar_p(
                fixed_wins_total, dynamic_wins_total
            ),
        },
        "correlation": correlation,
        "disagreement_count": len(disagreements),
        "blind_review": blind_review,
        "blind_review_v1": blind_review_v1,
        "blind_review_gpt": blind_review_gpt,
        "audit_requests": audit_requests,
        "repair_requests": repair_requests,
        "public_messages": public_messages,
        "generation_requests": generation_requests,
        "disclosure_distribution": distribution,
        "dynamic_speech_min": min(
            value
            for counts in dynamic_speech_counts
            for value in counts.values()
        ),
        "dynamic_speech_max": max(
            value
            for counts in dynamic_speech_counts
            for value in counts.values()
        ),
        "selector_reasons": selector_reasons,
        "selector_selected": {
            name: {
                "mean": statistics.mean(values),
                "nonzero": sum(value > 0 for value in values),
            }
            for name, values in selector_selected_values.items()
        },
    }


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = Path("C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size=size, index=0)


def _draw_grouped_bar(
    output: Path,
    *,
    title: str,
    subtitle: str,
    values: dict[str, list[float]],
    errors: dict[str, list[float]] | None = None,
    y_label: str,
) -> None:
    width, height = 1800, 1000
    image = Image.new("RGB", (width, height), f"#{WHITE}")
    draw = ImageDraw.Draw(image)
    title_font = _font(42, True)
    subtitle_font = _font(24)
    axis_font = _font(24)
    label_font = _font(23)
    value_font = _font(22, True)

    draw.text((110, 55), title, fill=f"#{NAVY}", font=title_font)
    draw.text((110, 120), subtitle, fill=f"#{MID_GRAY}", font=subtitle_font)

    left, top, right, bottom = 150, 210, 1720, 825
    draw.line((left, top, left, bottom), fill="#6B7280", width=3)
    draw.line((left, bottom, right, bottom), fill="#6B7280", width=3)
    for tick in range(0, 101, 20):
        y = bottom - (bottom - top) * tick / 100
        draw.line((left, y, right, y), fill="#E5E7EB", width=2)
        label = f"{tick}%"
        bbox = draw.textbbox((0, 0), label, font=axis_font)
        draw.text(
            (left - 20 - (bbox[2] - bbox[0]), y - 14),
            label,
            fill="#4B5563",
            font=axis_font,
        )
    draw.text((35, 470), y_label, fill="#4B5563", font=axis_font)

    groups = list(TASKS)
    series = list(values)
    colors = ["#2E74B5", "#D97706"]
    group_width = (right - left) / len(groups)
    bar_width = 115
    gap = 28

    for group_index, task_id in enumerate(groups):
        center = left + group_width * (group_index + 0.5)
        for series_index, series_name in enumerate(series):
            value = values[series_name][group_index]
            x0 = center + (series_index - 0.5) * (bar_width + gap)
            y0 = bottom - (bottom - top) * value
            draw.rounded_rectangle(
                (x0 - bar_width / 2, y0, x0 + bar_width / 2, bottom),
                radius=12,
                fill=colors[series_index],
            )
            label = f"{value * 100:.1f}%"
            bbox = draw.textbbox((0, 0), label, font=value_font)
            draw.text(
                (
                    x0 - (bbox[2] - bbox[0]) / 2,
                    y0 - 38,
                ),
                label,
                fill="#1F2937",
                font=value_font,
            )
            if errors is not None:
                error = errors[series_name][group_index]
                high = min(1.0, value + error)
                low = max(0.0, value - error)
                y_high = bottom - (bottom - top) * high
                y_low = bottom - (bottom - top) * low
                draw.line((x0, y_high, x0, y_low), fill="#111827", width=3)
                draw.line(
                    (x0 - 15, y_high, x0 + 15, y_high),
                    fill="#111827",
                    width=3,
                )
                draw.line(
                    (x0 - 15, y_low, x0 + 15, y_low),
                    fill="#111827",
                    width=3,
                )

        task_label = f"ID {task_id}\n{TASKS[task_id]['short']}"
        lines = task_label.splitlines()
        for line_index, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=label_font)
            draw.text(
                (
                    center - (bbox[2] - bbox[0]) / 2,
                    bottom + 24 + line_index * 34,
                ),
                line,
                fill="#374151",
                font=label_font,
            )

    legend_y = 920
    legend_x = 660
    for index, series_name in enumerate(series):
        x = legend_x + index * 310
        draw.rounded_rectangle(
            (x, legend_y, x + 42, legend_y + 24),
            radius=5,
            fill=colors[index],
        )
        draw.text(
            (x + 58, legend_y - 4),
            series_name,
            fill="#374151",
            font=label_font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=95)


def _set_run_font(
    run,
    *,
    size: float | None = None,
    bold: bool | None = None,
    color: str | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = FONT_ASCII
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), FONT_ASCII)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), FONT_ASCII)
    run._element.get_or_add_rPr().rFonts.set(
        qn("w:eastAsia"), FONT_EAST_ASIA
    )
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (
        ("top", top),
        ("start", start),
        ("bottom", bottom),
        ("end", end),
    ):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_table_geometry(table, widths_dxa: list[int]) -> None:
    if sum(widths_dxa) != 9360:
        raise ValueError(f"Table widths must sum to 9360, got {widths_dxa}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), "9360")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), "120")

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), str(width))
        grid.append(grid_col)

    for row in table.rows:
        for cell, width in zip(row.cells, widths_dxa, strict=True):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:type"), "dxa")
            tc_w.set(qn("w:w"), str(width))
            _set_cell_margins(cell)


def _repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    tr_pr.append(node)


def _prevent_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def _add_table(
    document: DocumentType,
    headers: list[str],
    rows: Iterable[Iterable[str]],
    widths_dxa: list[int],
    *,
    font_size: float = 9.0,
):
    materialized = [list(row) for row in rows]
    table = document.add_table(rows=1 + len(materialized), cols=len(headers))
    table.style = "Table Grid"
    for col, header in enumerate(headers):
        table.cell(0, col).text = header
    for row_index, row in enumerate(materialized, start=1):
        for col, value in enumerate(row):
            table.cell(row_index, col).text = str(value)
    _set_table_geometry(table, widths_dxa)
    _repeat_header(table.rows[0])
    for row_index, row in enumerate(table.rows):
        _prevent_split(row)
        for col_index, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index == 0:
                _set_cell_shading(cell, LIGHT_GRAY)
            elif row_index % 2 == 0:
                _set_cell_shading(cell, PALE_BLUE)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                if col_index > 0 and len(headers) <= 5:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    _set_run_font(
                        run,
                        size=font_size,
                        bold=(row_index == 0),
                        color=NAVY if row_index == 0 else DARK_GRAY,
                    )
    document.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def _set_paragraph_border_bottom(paragraph, color: str, size: int = 10) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is None:
        p_bdr = OxmlElement("w:pBdr")
        p_pr.append(p_bdr)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)


def _shade_paragraph(paragraph, fill: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = p_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        p_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _add_callout(document: DocumentType, label: str, body: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.style = document.styles["Callout"]
    _shade_paragraph(paragraph, LIGHT_BLUE)
    label_run = paragraph.add_run(f"{label}  ")
    _set_run_font(label_run, size=11, bold=True, color=NAVY)
    body_run = paragraph.add_run(body)
    _set_run_font(body_run, size=11, color=DARK_GRAY)


def _add_caption(document: DocumentType, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(8)
    run = paragraph.add_run(text)
    _set_run_font(run, size=9, color=MID_GRAY, italic=True)


def _add_source_note(document: DocumentType, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(text)
    _set_run_font(run, size=8.5, color=MID_GRAY)


def _add_page_field(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("第 ")
    _set_run_font(run, size=9, color=MID_GRAY)
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)
    end_run = paragraph.add_run(" 页")
    _set_run_font(end_run, size=9, color=MID_GRAY)


def _configure_styles(document: DocumentType) -> None:
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = FONT_ASCII
    normal._element.rPr.rFonts.set(qn("w:ascii"), FONT_ASCII)
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), FONT_ASCII)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_EAST_ASIA)
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(DARK_GRAY)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    for name, size, color, before, after in [
        ("Heading 1", 16, BLUE, 16, 8),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, DARK_BLUE, 8, 4),
    ]:
        style = styles[name]
        style.font.name = FONT_ASCII
        style._element.rPr.rFonts.set(qn("w:ascii"), FONT_ASCII)
        style._element.rPr.rFonts.set(qn("w:hAnsi"), FONT_ASCII)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_EAST_ASIA)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    if "Callout" not in [style.name for style in styles]:
        style = styles.add_style("Callout", 1)
    else:
        style = styles["Callout"]
    style.font.name = FONT_ASCII
    style._element.rPr.rFonts.set(qn("w:ascii"), FONT_ASCII)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), FONT_ASCII)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_EAST_ASIA)
    style.font.size = Pt(11)
    style.paragraph_format.left_indent = Inches(0.12)
    style.paragraph_format.right_indent = Inches(0.12)
    style.paragraph_format.space_before = Pt(8)
    style.paragraph_format.space_after = Pt(10)
    style.paragraph_format.line_spacing = 1.12


def _configure_page(document: DocumentType) -> None:
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    header = section.header
    header_para = header.paragraphs[0]
    header_para.paragraph_format.space_after = Pt(2)
    header_run = header_para.add_run("MAS知识治理｜AI信息包披露率与重复稳定性")
    _set_run_font(header_run, size=8.5, bold=True, color=MID_GRAY)
    _set_paragraph_border_bottom(header_para, "D9DEE7", 6)

    footer = section.footer
    _add_page_field(footer.paragraphs[0])


def _add_cover(document: DocumentType, analysis: dict) -> None:
    document.add_paragraph().paragraph_format.space_after = Pt(12)
    kicker = document.add_paragraph()
    kicker.paragraph_format.space_after = Pt(6)
    run = kicker.add_run("独立实验报告")
    _set_run_font(run, size=11, bold=True, color=BLUE)

    title = document.add_paragraph()
    title.paragraph_format.space_after = Pt(7)
    title.paragraph_format.keep_with_next = True
    run = title.add_run("AI信息包披露率与四题重复稳定性实验")
    _set_run_font(run, size=25, bold=True, color=NAVY)

    subtitle = document.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(18)
    run = subtitle.add_run(
        "让模型判定Agent级私有信息包是否由其拥有者公开，并用80次正式运行检验结果稳定性"
    )
    _set_run_font(run, size=13, color=MID_GRAY)

    rule = document.add_paragraph()
    rule.paragraph_format.space_after = Pt(16)
    _set_paragraph_border_bottom(rule, BLUE, 14)

    metadata = [
        ("实验框架", "Microsoft Agent Framework"),
        ("生成/审计模型", "DeepSeek V4 Flash"),
        ("任务范围", "HiddenBench有意选取题 ID 1、5、7、25"),
        ("重复设计", "4题 × 2种发言机制 × 10次 = 80个run"),
        ("讨论预算", "每个run固定60次公开发言"),
        ("报告日期", "2026年7月30日"),
    ]
    for label, value in metadata:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        label_run = paragraph.add_run(f"{label}：")
        _set_run_font(label_run, size=10.5, bold=True, color=NAVY)
        value_run = paragraph.add_run(value)
        _set_run_font(value_run, size=10.5, color=DARK_GRAY)

    document.add_paragraph().paragraph_format.space_after = Pt(10)
    fixed = analysis["overall"]["fixed"]
    dynamic = analysis["overall"]["dynamic"]
    _add_callout(
        document,
        "核心结果",
        (
            f"AI判定的总体平均信息包披露率为"
            f"{_pct((fixed['ai_disclosure_mean'] + dynamic['ai_disclosure_mean']) / 2)}。"
            f"固定轮转40次中{fixed['correct']}次多数正确；动态发言40次中"
            f"{dynamic['correct']}次多数正确。信息包披露率与正确结果在本样本中正相关，"
            "但高披露并不保证正确，本实验也没有证据显示动态顺序优于固定轮转。"
        ),
    )
    note = document.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.LEFT
    note.paragraph_format.space_before = Pt(12)
    run = note.add_run(
        "本文件由空白文档独立生成，只报告AI信息包披露审计、重复稳定性和结果分析。"
    )
    _set_run_font(run, size=9, italic=True, color=MID_GRAY)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _add_executive_summary(document: DocumentType, analysis: dict) -> None:
    document.add_heading("一、结论先行", level=1)
    fixed = analysis["overall"]["fixed"]
    dynamic = analysis["overall"]["dynamic"]
    combined_disclosure = (
        fixed["ai_disclosure_mean"] + dynamic["ai_disclosure_mean"]
    ) / 2

    document.add_paragraph(
        f"本实验用AI逐项检查80个run中4个Agent级私有信息包是否由其拥有者"
        f"公开，因此共形成320个信息包级判断。一个信息包可能包含多个原子事实，"
        f"本报告的百分比不是原子事实覆盖率。AI判定总体平均信息包披露率为"
        f"{_pct(combined_disclosure)}：固定轮转"
        f"{_pct(fixed['ai_disclosure_mean'])}，动态发言"
        f"{_pct(dynamic['ai_disclosure_mean'])}。"
    )
    document.add_paragraph(
        f"重复实验没有显示动态发言优于固定轮转。固定轮转40次中"
        f"{fixed['correct']}次多数正确、{fixed['wrong_consensus']}次全体一致但错误；"
        f"动态发言40次中{dynamic['correct']}次多数正确、"
        f"{dynamic['wrong_consensus']}次全体一致但错误，另有"
        f"{dynamic['other_incorrect']}次其他错误结果。两种机制都使用相同任务、"
        "相同模型、成对编号、相同私有信息分配和相同60次发言预算。"
    )
    document.add_paragraph(
        "四道题呈现出四种稳定性状态：ID 1 在固定轮转下稳定成功，但动态发言"
        "只有6/10正确；ID 5 在两种机制下均10/10形成错误共识；ID 7 仍然"
        "高度困难；ID 25 在两种机制下均8/10正确。由此可见，重复实验不仅"
        "确认了某些稳定现象，也识别出对发言顺序敏感的题目。"
    )
    _add_callout(
        document,
        "主要判断",
        "拥有者公开私有信息包通常有帮助，但不是正确性的充分条件。系统还需要正确理解、比较并使用已经进入公共讨论的证据；否则仍可能形成错误共识。",
    )


def _add_design(document: DocumentType, analysis: dict) -> None:
    document.add_heading("二、实验问题与重复设计", level=1)
    document.add_heading("1. 本报告只回答三个问题", level=2)
    questions = [
        "AI自己判断：四个Agent级私有信息包中，有多少由其拥有者公开到60条讨论中？",
        "同样的任务重复10次后，正确率、错误共识和披露率是否稳定？",
        "披露率、发言机制与最终正确性之间出现了什么关系？",
    ]
    for index, question in enumerate(questions, start=1):
        paragraph = document.add_paragraph()
        run = paragraph.add_run(f"{index}. ")
        _set_run_font(run, size=11, bold=True, color=BLUE)
        run = paragraph.add_run(question)
        _set_run_font(run, size=11, color=DARK_GRAY)

    document.add_heading("2. 四道有意选取的题目", level=2)
    _add_table(
        document,
        ["ID", "任务", "核心问题", "正确答案"],
        [
            [
                str(task_id),
                TASKS[task_id]["short"],
                TASKS[task_id]["question"],
                TASKS[task_id]["answer"],
            ]
            for task_id in sorted(TASKS)
        ],
        [600, 1350, 4930, 2480],
        font_size=9.2,
    )
    _add_source_note(
        document,
        "选择原则：四题来自第一阶段筛选，按机制研究目的有意选取，覆盖灾害决策、人员选择、复合标准筛选和应急规划；并非从65题随机抽样。四题均含4组私有信息，可与4名Agent一一对应，且在重复运行前锁定。",
    )
    document.add_paragraph(
        "因此，这四题可能偏重失败案例和对发言机制敏感的案例。本文只把结果"
        "解释为四题上的机制性证据，不用它估计HiddenBench 65题的总体表现。"
    )

    document.add_heading("3. 重复实验矩阵", level=2)
    document.add_paragraph(
        "每道题运行固定轮转和动态发言两种条件，每种条件重复10次，共80个"
        "正式run。固定轮转始终按A-B-C-D循环；动态发言根据“分歧、尚未披露、"
        "当前相关性、回应需求、等待时间”五项闭式分数选择下一位发言者。"
        "动态选择器不调用LLM。"
    )
    document.add_paragraph(
        "动态得分权重依次为0.30、0.30、0.15、0.15和0.10。若总分相同，"
        "依次比较剩余发言配额、实际等待轮数，仍相同则按Agent ID确定。"
        f"40个动态run中每名Agent实际都恰好发言15次（最少"
        f"{analysis['dynamic_speech_min']}次，最多{analysis['dynamic_speech_max']}次）；"
        "动态机制改变的是发言顺序，而不是各Agent的总发言次数。"
    )
    factor_labels = {
        "disagreement": ("与当前多数分歧", "0.30"),
        "undisclosed": ("尚未披露代理值", "0.30"),
        "related_discussion": ("当前讨论相关", "0.15"),
        "response_due": ("需要回应", "0.15"),
        "waiting": ("等待时间", "0.10"),
    }
    _add_table(
        document,
        ["动态因子", "权重", "被选者非零次数／2400", "被选者均值"],
        [
            [
                factor_labels[name][0],
                factor_labels[name][1],
                str(analysis["selector_selected"][name]["nonzero"]),
                f"{analysis['selector_selected'][name]['mean']:.3f}",
            ]
            for name in factor_labels
        ],
        [3050, 1050, 3100, 2160],
        font_size=8.8,
    )
    _add_source_note(
        document,
        "2400次动态选择中，2290次由最高总分直接决定；总分并列时，剩余配额决定4次、等待时间决定24次、Agent ID决定82次。权重为设计前固定的探索性设置，本实验没有完成权重消融或最优性验证。",
    )
    document.add_paragraph(
        "因此本文的“动态发言”准确地说是“等额配额下的内容感知动态排序”。"
        "它不检验允许高价值Agent多说、低价值Agent少说的动态额度分配机制。"
        "其中“尚未披露”由透明词法—语义规则实时估计，而最终披露指标由AI审计；"
        f"两者在320个信息包级判断中有{analysis['disagreement_count']}次分歧。"
        "机制效果不佳可能同时来自排序策略和在线代理指标误差。"
    )
    _add_table(
        document,
        ["控制项", "固定设置"],
        [
            ["生成模型", "DeepSeek V4 Flash；temperature=0；thinking disabled"],
            ["Agent数量", "4名；每名固定获得1个私有信息包"],
            ["发言预算", "每个run固定60次公开发言"],
            [
                "重复次数",
                "每题每机制10次；成对编号固定同一份私有信息分配，但不控制模型生成随机性",
            ],
            ["最终评价", "讨论后四名Agent独立投票；统计多数正确与错误共识"],
        ],
        [1900, 7460],
        font_size=9.3,
    )
    _add_callout(
        document,
        "公平比较",
        "两种机制的模型调用预算完全一致。这样可以避免把“多说了几次”误当成治理机制更有效。",
    )
    _add_callout(
        document,
        "seed的真实含义",
        "DeepSeek/MAF适配器没有把seed传给模型服务。这里的seed只固定私有信息分配并配对固定轮转与动态发言；temperature=0也不等于服务端输出必然一致。因此10次重复测到的是同配置下真实的服务端非确定性和对话演化差异，不是10个被严格控制的生成随机种子。",
    )


def _add_ai_audit_method(document: DocumentType, analysis: dict) -> None:
    document.add_heading("三、AI如何生成信息包披露百分比", level=1)
    document.add_heading("1. AI逐个信息包判断，而不是数关键词", level=2)
    document.add_paragraph(
        "每个run结束后，审计模型同时看到一个Agent级私有信息包和该run的"
        "完整60条公开消息。它需要判断该信息包的决策关键含义是否由拥有者以"
        "原文、概括或等价含义公开，并返回是否披露、证据message ID、原文引句、"
        "理由和置信度。四个信息包分别判断，不能只根据最终答案倒推“应该已经披露”。"
    )
    document.add_heading("2. 判定规则与真实输出示例", level=2)
    rules = [
        "信息拥有者说出原事实，或给出保留决策关键含义的忠实转述，才算披露。",
        "极性颠倒、与事实矛盾或把关键断言明显弱化，不算披露。",
        "只说出部分内容时，只有保留了影响决策的核心部分才算披露。",
        "非拥有者的猜测或重复，不替代拥有者披露其私有信息。",
        "disclosed=true时，必须返回拥有者发言的message ID和原文证据引句。",
        "disclosed=false时，证据ID列表和引句必须为空。",
    ]
    for index, rule in enumerate(rules, start=1):
        document.add_paragraph(f"{index}. {rule}")
    _add_table(
        document,
        ["示例", "AI输出"],
        [
            [
                "已披露",
                "ID 1／固定轮转／第0次；agent-a；disclosed=true；"
                "message ID=1c5c4a60df046572；证据："
                "“the supply truck is stuck in the tunnel to East Town”。",
            ],
            [
                "未披露",
                "ID 1／动态发言／第0次；agent-d；disclosed=false；"
                "证据为空；理由：No message from agent-d mentions walking "
                "trails being closed due to fallen trees.",
            ],
        ],
        [1200, 8160],
        font_size=8.7,
    )
    formula = document.add_paragraph()
    formula.alignment = WD_ALIGN_PARAGRAPH.CENTER
    formula.paragraph_format.space_before = Pt(8)
    formula.paragraph_format.space_after = Pt(10)
    run = formula.add_run(
        "单个run信息包披露率 = AI判定由拥有者公开的信息包数 ÷ 4"
    )
    _set_run_font(run, size=12, bold=True, color=NAVY)
    _shade_paragraph(formula, LIGHT_BLUE)

    document.add_paragraph(
        "AI只负责上述语义判断；程序再按“已披露信息包数÷4”确定性计算百分比，"
        "避免让模型自行做算术或随意输出一个比例。"
    )
    _add_callout(
        document,
        "指标边界",
        "本指标测量的是“来源披露率”：只有信息拥有者说出才计入。非拥有者正确猜测或复述虽然会让内容进入公共频道，但不计入本指标。后续应另报“公共可见率”，即不限制说话者、只判断信息是否已经公开出现；二者不能混称。",
    )

    document.add_heading("3. 防止AI随意给百分比", level=2)
    document.add_paragraph(
        "程序会检查AI给出的证据引句是否确实出现在对应message ID中。若输出"
        "结构错误或证据不匹配，只允许修复一次；修复后仍不满足要求则审计失败。"
        "正式数据中80份审计全部通过，共发送"
        f"{analysis['audit_requests']}次审计请求，其中"
        f"{analysis['repair_requests']}次属于修复请求。"
    )
    document.add_paragraph(
        f"为了识别审计模型的偏差，实验还保留一套透明规则作为交叉检查。AI与"
        f"规则在320个信息包级判断中有{analysis['disagreement_count']}次分歧，"
        f"总体一致率为{_pct(1 - analysis['disagreement_count'] / 320, 2)}。"
        "报告中的主披露率来自AI；规则结果只用于提醒哪些案例需要人工复核。"
    )
    _add_callout(
        document,
        "审计边界",
        "生成模型和审计模型均为DeepSeek V4 Flash，可能存在同模型偏差。本轮尚未完成独立人工或异构模型复核，因此AI百分比是带证据、可复查的审计结果，不是金标准。",
    )
    document.add_page_break()
    document.add_heading("4. 确认性盲审的执行结果与诚信边界", level=2)
    blind = analysis["blind_review"]
    blind_v1 = analysis["blind_review_v1"]
    metrics = blind["metrics"]
    metrics_v1 = blind_v1["metrics"]
    document.add_paragraph(
        "已建立固定种子20260730的盲化复核队列：84项AI—规则分歧全部纳入；"
        "其余236项一致判断按AI“已披露/未披露”、任务和发言机制分层，各抽取"
        "30项，共60项。盲审总数为144项。复核者只看到随机blind ID、私有"
        "信息包、拥有者及其公开发言，不看到原AI标签、规则标签、题号、机制"
        "或重复编号。"
    )
    _add_table(
        document,
        ["确认性复核项", "结果"],
        [
            ["总体与样本", "320项总体；84项分歧全审；一致层抽样60项；共复核144项"],
            ["模型辅助复核一致率", _pct(metrics["ai_human_agreement"], 1)],
            ["AI精确率（加权预估）", _pct(metrics["ai_precision"], 1)],
            ["AI召回率（加权预估）", _pct(metrics["ai_recall"], 1)],
            ["修订披露率（加权预估）", _pct(metrics["revised_disclosure_rate"], 1)],
        ],
        [3300, 6060],
        font_size=9.0,
    )
    document.add_paragraph(
        "加权方法为：84项分歧属于全量复核，权重为1；一致样本按"
        "AI标签×任务×机制层的总体数除以该层样本数赋权，再把估计范围还原到"
        "全部320项。模型辅助复核得到的加权混淆矩阵为"
        f"TP={metrics['estimated_tp']:.2f}、FP={metrics['estimated_fp']:.2f}、"
        f"TN={metrics['estimated_tn']:.2f}、FN={metrics['estimated_fn']:.2f}。"
    )
    _add_table(
        document,
        ["判定规则版本", "一致率", "精确率", "召回率", "修订披露率"],
        [
            [
                "首轮盲审v1",
                _pct(metrics_v1["ai_human_agreement"], 1),
                _pct(metrics_v1["ai_precision"], 1),
                _pct(metrics_v1["ai_recall"], 1),
                _pct(metrics_v1["revised_disclosure_rate"], 1),
            ],
            [
                "冻结口径v2",
                _pct(metrics["ai_human_agreement"], 1),
                _pct(metrics["ai_precision"], 1),
                _pct(metrics["ai_recall"], 1),
                _pct(metrics["revised_disclosure_rate"], 1),
            ],
        ],
        [2300, 1765, 1765, 1765, 1765],
        font_size=8.8,
    )
    _add_callout(
        document,
        "不能冒充人工金标准",
        "上述144项逐项复核由盲化的DeepSeek V4 Flash生成，属于模型辅助预审，"
        "不是人类审阅。v1与冻结口径v2有8项标签变化，说明判定对“是否必须复述"
        "原因、时间和全部子事实”较敏感。因此正文只能写“模型辅助复核一致率”，"
        "不能写“人工一致率”。不含既有标签的签核表已保存为"
        "artifacts/hiddenbench-stability-20260729.blind-review.queue.csv；真人填写"
        "全部144行后运行run_hiddenbench_blind_review.py --from-human-queue，"
        "即可证据校验并自动重算最终人工指标。",
    )
    document.add_paragraph(
        "复核队列、选中样本快照、逐项判断、原始调用元数据、摘要和补充分析的"
        "字节数与SHA-256已写入"
        "artifacts/hiddenbench-stability-20260729.blind-review.manifest.json。"
    )
    document.add_heading("5. 独立模型盲审（Codex，2026-08-02）", level=2)
    gpt = analysis["blind_review_gpt"]
    gpt_metrics = gpt["metrics"]
    document.add_paragraph(
        "为检验“同模型自审”的偏差，由独立评审模型（Codex，与DeepSeek不同源）"
        "对同一144项盲化队列重新逐项判定。评审只看到blind ID、私有信息包和"
        "拥有者发言，全程不接触AI标签、规则标签、题号与机制；判定规则与审计"
        "prompt的六条规则一致，且程序校验每条“已披露”都带拥有者消息ID和"
        "原文引句。评审结果："
    )
    _add_table(
        document,
        ["评审者", "一致率", "AI精确率", "AI召回率", "修订披露率"],
        [
            [
                "DeepSeek自审（冻结口径v2）",
                _pct(metrics["ai_human_agreement"], 1),
                _pct(metrics["ai_precision"], 1),
                _pct(metrics["ai_recall"], 1),
                _pct(metrics["revised_disclosure_rate"], 1),
            ],
            [
                "独立模型盲审（Codex）",
                _pct(gpt_metrics["ai_human_agreement"], 1),
                _pct(gpt_metrics["ai_precision"], 1),
                _pct(gpt_metrics["ai_recall"], 1),
                _pct(gpt_metrics["revised_disclosure_rate"], 1),
            ],
        ],
        [2850, 1627, 1627, 1627, 1629],
        font_size=8.8,
    )
    document.add_paragraph(
        "两组指标按同一加权方法（84项分歧权重1，一致层按AI标签×任务×机制"
        "分层赋权）还原到全部320项。独立盲审的144项中73项判“披露”、71项判"
        "“未披露”，未加权与AI标签一致98项。"
    )
    _add_callout(
        document,
        "同模型偏差的证据",
        "DeepSeek自审的一致率93.5%、召回率94.8%，而独立模型盲审只有79.5%和"
        "66.7%：AI审计模型漏报了约三分之一它自己会判为已披露的案例，主要集中"
        "在RFP字母值题——独立评审认可“拥有者说出了信息包中的具体值”即算披露，"
        "而AI审计常要求复述整个信息包。修订披露率因此从36.4%上调至55.7%。"
        "这证明披露率对评审者高度敏感，任何单一评审者（含本报告的独立模型）"
        "都不能自称金标准，最终仍需要真人仲裁。",
    )
    document.add_paragraph(
        "独立盲审的逐项判断、带证据的签核表（已填版本）和摘要分别保存为"
        "hiddenbench-stability-20260729.blind-review.gpt.judgments.jsonl、"
        "blind-review.gpt.queue.csv 和 blind-review.gpt.summary.json；"
        "评审脚本为 reports/run_codex_blind_review.py，可复现。"
    )
    document.add_page_break()


def _add_results(
    document: DocumentType,
    analysis: dict,
    disclosure_chart: Path,
    accuracy_chart: Path,
) -> None:
    document.add_heading("四、AI信息包披露率结果", level=1)
    summaries = analysis["summaries"]
    result_rows = []
    for task_id in sorted(TASKS):
        for condition in ("fixed", "dynamic"):
            row = summaries[(task_id, condition)]
            distribution = "；".join(
                f"{answer}×{count}"
                for answer, count in row["final_answer_distribution"].items()
            )
            result_rows.append(
                [
                    f"{task_id} {TASKS[task_id]['short']}",
                    CONDITION_LABEL[condition],
                    (
                        f"{_pct(row['ai_disclosure_mean'])}"
                        f" ± {_pct(row['ai_disclosure_std'])}"
                    ),
                    f"{row['post_majority_correct_count']}/10",
                    f"{row['wrong_consensus_count']}/10",
                    distribution,
                ]
            )
    _add_table(
        document,
        ["任务", "机制", "AI信息包披露率\n均值±标准差", "多数正确", "错误共识", "最终答案分布"],
        result_rows,
        [1250, 900, 1570, 950, 950, 3740],
        font_size=8.5,
    )
    _add_source_note(
        document,
        "信息包披露率按每个run的4个Agent级私有信息包计算，再对10次重复取均值；它不是原子事实覆盖率。标准差反映同题同机制下10次运行之间的波动。“错误共识”专指四名Agent最终全体一致且答案错误，不等于所有错误结果。",
    )
    interval_rows = []
    for task_id in sorted(TASKS):
        fixed_count = summaries[(task_id, "fixed")][
            "post_majority_correct_count"
        ]
        dynamic_count = summaries[(task_id, "dynamic")][
            "post_majority_correct_count"
        ]
        fixed_low, fixed_high = analysis["paired"][task_id]["fixed_ci"]
        dynamic_low, dynamic_high = analysis["paired"][task_id]["dynamic_ci"]
        interval_rows.append(
            [
                f"ID {task_id}",
                f"{fixed_count}/10 [{_pct(fixed_low)}, {_pct(fixed_high)}]",
                f"{dynamic_count}/10 [{_pct(dynamic_low)}, {_pct(dynamic_high)}]",
            ]
        )
    _add_table(
        document,
        ["任务", "固定轮转正确数［Wilson 95% CI］", "动态发言正确数［Wilson 95% CI］"],
        interval_rows,
        [1200, 4080, 4080],
        font_size=8.8,
    )
    _add_source_note(
        document,
        "每格仅10次重复，区间较宽。例如10/10的95%区间仍为[72.2%, 100.0%]，不能把观测到的100%理解为真实成功率已经精确确定。",
    )

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    run.add_picture(str(disclosure_chart), width=Inches(6.35))
    _add_caption(
        document,
        "图1  四题在固定轮转和动态发言下的AI信息包披露率（误差线为10次重复的标准差）",
    )
    document.add_paragraph(
        "披露率的任务差异远大于两种机制之间的差异。ID 1 在两种机制下都能"
        "披露大部分私有信息；ID 5和ID 7几乎没有被AI判定为完整披露；ID 25"
        "稳定在67.5%。固定轮转总体平均信息包披露率为40.0%，动态发言为38.1%，"
        "差距只有1.9个百分点。"
    )

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    run.add_picture(str(accuracy_chart), width=Inches(6.35))
    _add_caption(
        document,
        "图2  四题在两种机制下的讨论后多数正确率（每格10次重复）",
    )


def _add_stability_analysis(document: DocumentType, analysis: dict) -> None:
    document.add_heading("五、重复实验的稳定性判断", level=1)
    summaries = analysis["summaries"]
    paired = analysis["paired"]

    document.add_heading("ID 1：固定轮转稳定，动态发言对顺序敏感", level=2)
    document.add_paragraph(
        "固定轮转10/10多数正确，AI信息包披露率90.0%；动态发言只有6/10正确，"
        "AI信息包披露率仍达到85.0%。成对比较中固定轮转胜4次、动态发言胜0次、"
        "其余6次相同。这说明问题不只是“有没有披露”，还包括哪条证据先成为"
        "讨论锚点，以及已经披露的信息是否被正确解释。"
    )

    document.add_heading("ID 5：稳定失败", level=2)
    document.add_paragraph(
        "两种机制均0/10正确，并且都10/10形成错误共识。AI信息包披露率固定轮转"
        "仅2.5%，动态发言为0%。这是最稳定的失败案例：关键候选人信息没有"
        "充分进入公共讨论，增加动态选人机制也没有改善结果。"
    )

    document.add_heading("ID 7：复合信息使AI审计更严格", level=2)
    document.add_paragraph(
        "固定轮转2/10正确，动态发言0/10正确。AI信息包披露率均为0%，但透明规则"
        "分别给出50.0%和87.5%。二者不是同一判据：当前AI审计把每名Agent"
        "的一整组RFP信息作为一个项目，透明规则会命中其中部分子条款。"
        "本研究尚未把RFP逐项拆成原子子主张再交给AI逐项审计，因此不能把"
        "这两个比例直接解释成谁更准确。当前只能说本题稳定困难，且整项披露"
        "指标的粒度不足；后续应先拆分子条款，再使用相同分母重新比较。"
    )

    document.add_heading("ID 25：中等稳定的成功", level=2)
    document.add_paragraph(
        "两种机制均8/10正确，AI信息包披露率也同为67.5%。成对比较中固定轮转胜"
        "1次、动态发言胜1次、8次结果相同。该题说明当关键安全信息较容易被"
        "概括并复用时，两种机制都能较稳定地得到正确结果。"
    )

    _add_table(
        document,
        ["任务", "固定胜", "动态胜", "相同", "稳定性判断"],
        [
            [
                f"ID {task_id} {TASKS[task_id]['short']}",
                str(paired[task_id]["fixed_wins"]),
                str(paired[task_id]["dynamic_wins"]),
                str(paired[task_id]["ties"]),
                {
                    1: "机制敏感",
                    5: "稳定失败",
                    7: "稳定困难",
                    25: "中等稳定成功",
                }[task_id],
            ]
            for task_id in sorted(TASKS)
        ],
        [2200, 1100, 1100, 1100, 3860],
        font_size=9.2,
    )
    _add_source_note(
        document,
        "“胜”指同一题、同一重复编号下，一种机制多数正确而另一种错误；“相同”包括两者同时正确或同时错误。",
    )
    paired_overall = analysis["paired_overall"]
    document.add_paragraph(
        f"合并40组成对结果后，固定轮转胜{paired_overall['fixed_wins']}次，"
        f"动态发言胜{paired_overall['dynamic_wins']}次，"
        f"其余{paired_overall['ties']}次相同。对8个不一致对进行双侧精确"
        f"McNemar检验，p={paired_overall['mcnemar_p']:.4f}。按常用0.05阈值，"
        "结果不足以认定两种机制存在统计显著差异；稳妥结论是本实验没有证据"
        "表明动态发言更好，而不是宣称固定轮转已被证明更优。"
    )
    _add_callout(
        document,
        "统计口径",
        "上述Wilson区间和McNemar检验仅作探索性描述。40次运行来自4道任务各重复10次，并非40道独立抽样任务；同时DeepSeek不接收本实验的seed，重复编号只匹配任务与信息分配，不共享同一次模型随机扰动。因此不能把p值解释为对一般任务上机制差异的确认性检验。",
    )


def _add_synthesis(document: DocumentType, analysis: dict) -> None:
    document.add_heading("六、结果综合分析", level=1)
    fixed = analysis["overall"]["fixed"]
    dynamic = analysis["overall"]["dynamic"]
    document.add_heading("1. 等额配额动态排序没有显示稳定增益", level=2)
    document.add_paragraph(
        f"固定轮转40次中{fixed['correct']}次多数正确，正确率"
        f"{_pct(fixed['correct'] / 40)}，Wilson 95% CI为"
        f"[{_pct(fixed['correct_ci'][0])}, {_pct(fixed['correct_ci'][1])}]；"
        f"动态发言40次中"
        f"{dynamic['correct']}次多数正确，正确率"
        f"{_pct(dynamic['correct'] / 40)}，Wilson 95% CI为"
        f"[{_pct(dynamic['correct_ci'][0])}, {_pct(dynamic['correct_ci'][1])}]。"
        f"固定轮转的40次结果可闭合为{fixed['correct']}次正确、"
        f"{fixed['wrong_consensus']}次全体一致但错误、"
        f"{fixed['other_incorrect']}次其他错误；动态发言为"
        f"{dynamic['correct']}次正确、{dynamic['wrong_consensus']}次全体一致"
        f"但错误、{dynamic['other_incorrect']}次其他错误。后两次分别是ID 7"
        "一次3比1的错误多数，以及ID 25一次2比2、无多数。由于预算、模型、"
        "信息分配和配对编号已经匹配，这个差异不能解释成动态机制调用了更多模型；"
        "但该检验仅为探索性分析且未达0.05，因此不能据此宣称动态排序造成了伤害。"
    )

    document.add_heading("2. 总体相关主要由任务差异驱动", level=2)
    document.add_paragraph(
        f"在80个run层面，AI信息包披露率与多数正确的描述性Pearson相关系数为"
        f"r={analysis['correlation']:.2f}。但该相关性主要由任务难度共同驱动："
        "ID 1和ID 25同时拥有较高披露率和较高正确率，ID 5和ID 7同时偏低。"
        "题内关系并不一致，例如ID 1题内的披露率与正确性并未呈现同方向的"
        "稳定关系。只有四道任务，不能据此作因果推断，也不宜笼统表述为"
        "“提高披露率就能提高正确率”。"
    )
    document.add_paragraph(
        "ID 1提供了关键反例：动态条件信息包披露率仍有85.0%，但只有6/10正确。"
        "因此披露之后至少还有三个环节可能失败：其他Agent没有注意到证据、"
        "把证据解释成错误方向、或在后续讨论中让错误答案成为群体锚点。"
    )

    document.add_heading("3. 共识不能替代正确性检查", level=2)
    document.add_paragraph(
        "ID 5在两种机制下都快速形成全体一致，却10/10选择错误答案。固定"
        "轮转平均在第7.2条发言形成稳定共识，此后仍有大量重复确认。这个"
        "结果说明“大家一致”只能表示系统收敛，不能证明信息整合正确。"
    )

    document.add_heading("4. 固定60次用于公平比较，不代表最佳停止策略", level=2)
    document.add_paragraph(
        "本实验在已经出现共识后仍继续到60次发言，是为了让两种机制拥有完全"
        "相同的调用预算，并观察错误共识是否会被后续证据打破。该设计回答机制"
        "比较问题，但不回答实际系统何时应该停止。本轮没有在首次共识处重新"
        "触发四名Agent投票，因此不能从现有最终投票倒推出提前停止的真实正确率。"
        "下一步应增加预先定义的停止规则，在首次稳定共识、连续两轮不变和预算"
        "上限三个节点分别重新投票，同时比较正确率、共识翻转和Token消耗。"
    )

    document.add_heading("5. 当前结果支持的结论边界", level=2)
    _add_callout(
        document,
        "可以说",
        "在这四道有意选取的任务、DeepSeek V4 Flash和60次发言预算下，AI信息包披露率存在明显任务差异；重复实验观察到稳定成功、稳定失败和机制敏感三类现象；没有证据显示等额配额动态排序优于固定轮转。",
    )
    _add_callout(
        document,
        "不能说",
        "不能把四题推广为HiddenBench全部65题；不能把总体相关性解释为披露导致正确；不能把同模型AI审计视为人工金标准；也不能把本实验推广为所有动态发言或提前停止机制的结论。",
    )


def _add_reproducibility(document: DocumentType, analysis: dict) -> None:
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    document.add_heading("七、数据完整性与复核入口", level=1)
    document.add_paragraph(
        f"本次报告直接读取正式实验附件，共{len(analysis['run_records'])}个run、"
        f"{analysis['public_messages']}条公开发言、"
        f"{analysis['generation_requests']}次正式生成请求和"
        f"{len(analysis['audits'])}份有效AI审计。正式闸门13项全部通过，"
        "包括完整运行矩阵、相同发言预算、配对编号与信息分配、顺序可见性、证据引句"
        "校验、凭据扫描和文件哈希。"
    )
    document.add_paragraph(
        "5760次正式生成请求由80个run×72次组成：每个run包含4次讨论前投票、"
        "60次公开发言、4次讨论后投票和4次Full Profile独立投票。AI审计的"
        f"{analysis['audit_requests']}次请求另行统计，其中"
        f"{analysis['repair_requests']}次为格式或证据修复请求。Full Profile"
        "用于判断信息完全可见时模型能否解题，不参与60次讨论预算。"
    )
    _add_table(
        document,
        ["复现项", "固定值或入口"],
        [
            [
                "实验材料快照",
                f"{REPO_COMMIT}；{REPO_COMMIT_URL}",
            ],
            [
                "运行时代码",
                f"{RUN_COMMIT}；{RUN_COMMIT_URL}",
            ],
            [
                "完整仓库树",
                REPO_TREE_URL,
            ],
            [
                "HiddenBench论文",
                HIDDENBENCH_PAPER_URL,
            ],
            [
                "官方数据",
                HIDDENBENCH_DATA_URL,
            ],
            [
                "官方代码快照",
                f"{HIDDENBENCH_CODE_COMMIT}；{HIDDENBENCH_CODE_URL}",
            ],
            [
                "Microsoft Agent Framework",
                "agent-framework-core 1.12.1；"
                "agent-framework-orchestrations 1.0.1；"
                "agent-framework-openai 1.11.0",
            ],
            [
                "运行环境",
                "Windows 11；Python 3.13.12；mas-experiment 0.1.0；"
                "pydantic 2.12.4",
            ],
            [
                "Prompt与原始输出",
                "固定commit中的artifacts/hiddenbench-stability-20260729.jsonl；"
                "每次调用均保存system prompt、user prompt、输出和request ID",
            ],
            [
                "官方四题对照",
                "固定commit中的reports/HiddenBench_官方GPT4.1四题对照_2026-07-30.md；"
                "原论文使用作者自定义Python模拟器，本实验使用Microsoft Agent Framework，"
                "因此差异不能单独归因于框架",
            ],
        ],
        [2250, 7110],
        font_size=8.0,
    )
    document.add_paragraph(
        "复现时还需注意：deepseek-v4-flash是服务端模型名称，而不是本地冻结的"
        "权重快照。实验已保留request ID、原始输出、配置和哈希，可复核本轮"
        "结果；但若服务端以后更新同名模型，即使使用同一名称和temperature=0，"
        "未来重跑也可能出现不同输出。"
    )
    manifest = analysis["verification"]["manifest"]
    manifest_lookup = {item["path"]: item for item in manifest["files"]}
    attachment_rows = []
    for filename, description in [
        (
            "hiddenbench-stability-20260729.jsonl",
            "80个run的完整模型输出、投票与指标",
        ),
        (
            "hiddenbench-stability-20260729.ai-disclosure.jsonl",
            "80份AI披露判断及证据message ID",
        ),
        (
            "hiddenbench-stability-20260729.summary.csv",
            "八个题目—机制组合的重复统计",
        ),
        (
            "hiddenbench-stability-20260729.disagreements.csv",
            "AI与透明规则的全部分歧记录",
        ),
        (
            "hiddenbench-stability-20260729.gate.json",
            "13项正式完整性检查",
        ),
    ]:
        item = manifest_lookup[filename]
        attachment_rows.append(
            [
                filename,
                description,
                f"{item['bytes']:,}",
                item["sha256"][:16] + "…",
            ]
        )
    _add_table(
        document,
        ["附件", "用途", "字节数", "SHA-256前16位"],
        attachment_rows,
        [3300, 3020, 1180, 1860],
        font_size=8.3,
    )
    _add_source_note(
        document,
        f"Manifest生成时间：{manifest['generated_at']}；本报告生成前重新核对全部7个manifest文件的字节数与SHA-256。",
    )
    _add_callout(
        document,
        "最终结论",
        "本报告已完成Agent级信息包来源披露审计、四题两种机制各10次重复、"
        "84项分歧全量复核与60项一致判断分层抽样的模型辅助盲审、结果分类和"
        "探索性统计。真正的人工一致率、AI精确率、召回率和修订披露率仍须由"
        "真人填写已生成的144项盲化签核表后确认；此外仍待完成原子事实级审计、"
        "公共可见率、提前停止对照、动态额度分配和更多随机任务。",
    )


def _build_document(analysis: dict) -> DocumentType:
    WORK.mkdir(parents=True, exist_ok=True)
    disclosure_chart = WORK / "ai-disclosure-by-task.png"
    accuracy_chart = WORK / "majority-accuracy-by-task.png"
    summaries = analysis["summaries"]

    _draw_grouped_bar(
        disclosure_chart,
        title="AI判定的Agent级信息包来源披露率",
        subtitle="每个柱为10次重复的平均值；误差线表示标准差",
        values={
            "固定轮转": [
                summaries[(task_id, "fixed")]["ai_disclosure_mean"]
                for task_id in sorted(TASKS)
            ],
            "动态发言": [
                summaries[(task_id, "dynamic")]["ai_disclosure_mean"]
                for task_id in sorted(TASKS)
            ],
        },
        errors={
            "固定轮转": [
                summaries[(task_id, "fixed")]["ai_disclosure_std"]
                for task_id in sorted(TASKS)
            ],
            "动态发言": [
                summaries[(task_id, "dynamic")]["ai_disclosure_std"]
                for task_id in sorted(TASKS)
            ],
        },
        y_label="披露率",
    )
    _draw_grouped_bar(
        accuracy_chart,
        title="讨论后多数正确率",
        subtitle="每道题、每种机制均重复10次",
        values={
            "固定轮转": [
                summaries[(task_id, "fixed")][
                    "post_majority_correct_count"
                ]
                / 10
                for task_id in sorted(TASKS)
            ],
            "动态发言": [
                summaries[(task_id, "dynamic")][
                    "post_majority_correct_count"
                ]
                / 10
                for task_id in sorted(TASKS)
            ],
        },
        y_label="正确率",
    )

    document = Document()
    _configure_styles(document)
    _configure_page(document)
    _add_cover(document, analysis)
    _add_executive_summary(document, analysis)
    _add_design(document, analysis)
    _add_ai_audit_method(document, analysis)
    _add_results(document, analysis, disclosure_chart, accuracy_chart)
    _add_stability_analysis(document, analysis)
    _add_synthesis(document, analysis)
    _add_reproducibility(document, analysis)
    return document


def main() -> None:
    analysis = _analyze()
    document = _build_document(analysis)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    DESKTOP_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT, DESKTOP_OUTPUT)
    print(OUTPUT)
    print(DESKTOP_OUTPUT)
    print(
        json.dumps(
            {
                "runs": len(analysis["run_records"]),
                "audits": len(analysis["audits"]),
                "messages": analysis["public_messages"],
                "audit_requests": analysis["audit_requests"],
                "correlation": round(analysis["correlation"], 4),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
