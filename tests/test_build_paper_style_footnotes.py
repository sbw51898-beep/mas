import hashlib
import re
import zipfile
from pathlib import Path

from lxml import etree

from reports.build_paper_style_footnotes import build_footnote_report


ROOT = Path(__file__).resolve().parents[1]
BASE_REPORT = ROOT / "reports" / "基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx"
BASE_REPORT_SHA256 = "e1aa4be327c847ddfa3987e408a1a7a5f178f798eb8903928d95ff2a37c5f668"
COMPLETE_REPORT = ROOT / "reports" / "给彭老师的完整实验报告_2026-08-02至2026-08-04.docx"
COMPLETE_REPORT_SHA256 = "0d56f74c359e1a7359102de678c8c8e39bd568d381e9ff2ccf37189b83f72765"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _text(element: etree._Element) -> str:
    return "".join(node.text or "" for node in element.xpath(".//w:t", namespaces=NS))


def test_footnote_report_has_true_sequential_footnotes(tmp_path: Path) -> None:
    output = tmp_path / "paper-footnotes.docx"

    build_footnote_report(ROOT, output, None)

    with zipfile.ZipFile(output) as archive:
        assert "word/footnotes.xml" in archive.namelist()
        document = etree.fromstring(archive.read("word/document.xml"))
        footnotes = etree.fromstring(archive.read("word/footnotes.xml"))
        reference_ids = [
            int(node.get(f"{{{W_NS}}}id"))
            for node in document.xpath(".//w:footnoteReference", namespaces=NS)
        ]
        note_nodes = footnotes.xpath(".//w:footnote[number(@w:id) >= 1]", namespaces=NS)
        note_ids = [int(node.get(f"{{{W_NS}}}id")) for node in note_nodes]

        assert reference_ids == list(range(1, 18))
        assert note_ids == list(range(1, 18))
        assert all(
            node.xpath("./w:rPr/w:rStyle[@w:val='FootnoteReference']", namespaces=NS)
            for node in document.xpath(".//w:r[w:footnoteReference]", namespaces=NS)
        )
        note_texts = [_text(node) for node in note_nodes]
        assert "Guo et al." in note_texts[0]
        assert "Du et al." in note_texts[1]
        assert "Microsoft Agent Framework" in note_texts[-1]


def test_footnote_report_removes_bracket_citations_from_body_and_reorders_bibliography(tmp_path: Path) -> None:
    output = tmp_path / "paper-footnotes.docx"

    build_footnote_report(ROOT, output, None)

    with zipfile.ZipFile(output) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        paragraphs = document.xpath(".//w:body/w:p", namespaces=NS)
        texts = [_text(paragraph) for paragraph in paragraphs]
        reference_index = texts.index("参考文献")
        appendix_index = texts.index("附录")
        body_text = "\n".join(texts[:reference_index])
        reference_texts = [text for text in texts[reference_index + 1 : appendix_index] if text.strip()]

        assert not re.search(r"\[\d+(?:-\d+)?\]", body_text)
        assert "[[FN" not in body_text
        assert len(reference_texts) == 17
        assert reference_texts[0].startswith("[1] Taicheng Guo")
        assert reference_texts[1].startswith("[2] Yilun Du")
        assert reference_texts[-1].startswith("[17] Microsoft")
        reference_paragraphs = [
            paragraph
            for paragraph in paragraphs[reference_index + 1 : appendix_index]
            if _text(paragraph).strip()
        ]
        assert all(
            paragraph.xpath("./w:pPr/w:keepLines", namespaces=NS)
            for paragraph in reference_paragraphs
        )


def test_footnote_report_preserves_existing_reports_and_copies_desktop_output(tmp_path: Path) -> None:
    output = tmp_path / "paper-footnotes.docx"
    desktop = tmp_path / "desktop-paper-footnotes.docx"

    build_footnote_report(ROOT, output, desktop)

    assert hashlib.sha256(output.read_bytes()).hexdigest() == hashlib.sha256(desktop.read_bytes()).hexdigest()
    assert hashlib.sha256(BASE_REPORT.read_bytes()).hexdigest() == BASE_REPORT_SHA256
    assert hashlib.sha256(COMPLETE_REPORT.read_bytes()).hexdigest() == COMPLETE_REPORT_SHA256
