from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

from docx import Document

from reports.build_hiddenbench_closure_report import (
    build_hiddenbench_closure_report,
)


ROOT = Path(__file__).resolve().parents[1]
PRESERVED_REPORT = (
    ROOT / "reports" / "基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx"
)
PRESERVED_SHA256 = "21ac7bcbde08b17eb5f1978af35192e03af72642ae9d34fdf4c8c35e790a048f"


def _document_text(document: Document) -> str:
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    cells = [
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    ]
    return "\n".join(paragraphs + cells)


def test_closure_report_adds_reproducible_controls_and_bounded_conclusions(
    tmp_path: Path,
) -> None:
    output = tmp_path / "closure.docx"

    build_hiddenbench_closure_report(ROOT, output, None)

    text = _document_text(Document(output))
    for required in [
        "基于 MAF 的多智能体正确性治理与错误链路分析（闭环补充版）",
        "6.6 闭环补充：单智能体对照、错误链路与人工复核入口",
        "4/30",
        "20/30",
        "17/30",
        "普通条件下不随机、不强制披露",
        "15 轮 × 4 个 Agent",
        "0d078a3c85f64262",
        "e46521e6691a10ca",
        "bfba1db7a056ebea",
        "真人双盲审阅尚未完成",
        "GPT-4.1（或同等可验证接口）尚不可用",
    ]:
        assert required in text
    for forbidden in [
        "已完成人工盲审",
        "已完成 GPT-4.1 解耦实验",
        "AI 复核即人工金标准",
    ]:
        assert forbidden not in text


def test_closure_report_keeps_true_footnotes_and_preserves_original(
    tmp_path: Path,
) -> None:
    output = tmp_path / "closure.docx"

    build_hiddenbench_closure_report(ROOT, output, None)

    with zipfile.ZipFile(output) as archive:
        assert "word/footnotes.xml" in archive.namelist()
    assert hashlib.sha256(PRESERVED_REPORT.read_bytes()).hexdigest() == PRESERVED_SHA256


def test_closure_report_direct_script_entrypoint_loads() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "reports" / "build_hiddenbench_closure_report.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
