# MAS Correctness Governance Paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new, submission-ready Chinese Word paper that reorganizes the existing HiddenBench/MAF evidence around MAS correctness governance, error chains, observable indicators, targeted interventions, prior-work boundaries, and cross-implementation comparison.

**Architecture:** Keep the frozen evidence and reference registries as the sole quantitative source. Add one focused figure builder for the correctness-governance chain and one focused report builder that reuses the existing paper typography/table helpers, creates citations in first-use order, then patches them into true Word footnotes. Generate a new DOCX and Desktop copy while hashing and preserving both 2026-08-05 papers and the earlier complete experiment report.

**Tech Stack:** Python 3.13, `python-docx`, `lxml`, Matplotlib, OOXML/ZIP patching, pytest, Microsoft Word COM export, Poppler.

## Global Constraints

- Do not modify `reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`.
- Do not modify `reports/基于MAF的多智能体私有信息披露机制复现与对比研究_脚注版_2026-08-05.docx`.
- Do not modify `reports/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx`.
- The only quantitative source is `reports/data/hiddenbench-paper-evidence-20260805.json`; do not rerun experiments or invent additional results.
- Treat global Reveal-All as an information-availability upper bound and diagnostic control, not the main contribution.
- State that model and framework changed together, so the current study cannot identify a single causal source for differences from the official paper.
- Report `p=0.125` and `p=0.388` as statistically non-significant; do not claim proven superiority.
- Report FM-2.4 as confirmed, FM-2.5 as a candidate requiring human causal coding, and FM-2.6 as not confirmed.
- Use true Word footnotes, numbered sequentially by first appearance; retain a full bibliography in the same order.
- Output `reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx` and an identical Desktop copy.
- Use the existing paper visual language: Letter portrait, 1-inch margins, justified 11 pt body, blue heading hierarchy, fixed 9360-DXA tables, restrained callouts, running header/footer, and page numbers.
- Render and inspect every page after generation; no clipping, overlap, split bibliography entries, missing glyphs, broken tables, or accidental blank pages.

---

## File Map

- Create `reports/build_correctness_governance_figures.py`: generate the error-chain/governance-loop figure.
- Create `reports/build_correctness_governance_report.py`: assemble the full paper, citations, bibliography, appendices, true footnotes, preservation checks, and Desktop copy.
- Create `tests/test_build_correctness_governance_figures.py`: verify figure dimensions and nonblank content.
- Create `tests/test_build_correctness_governance_report.py`: verify thesis, headings, numbers, boundaries, true footnotes, fixed geometry, old-file preservation, and identical output copies.
- Create `reports/figures/mas-correctness-governance-loop.png`: generated figure used by the paper.
- Create `reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx`: final repository deliverable.
- Create Desktop copy at `C:/Users/liuli/Desktop/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx`.
- Do not modify the frozen evidence JSON, reference JSON, old report builders, old report tests, or existing DOCX deliverables.

---

### Task 1: Correctness-Governance Figure

**Files:**
- Create: `reports/build_correctness_governance_figures.py`
- Create: `tests/test_build_correctness_governance_figures.py`
- Create: `reports/figures/mas-correctness-governance-loop.png`

**Interfaces:**
- Consumes: no experiment data; only fixed Chinese labels from the approved design.
- Produces: `build_correctness_governance_figure(output: Path, dpi: int = 200) -> Path`.

- [ ] **Step 1: Write the failing figure tests**

```python
from pathlib import Path

from PIL import Image

from reports.build_correctness_governance_figures import build_correctness_governance_figure


def test_correctness_governance_figure_is_large(tmp_path: Path) -> None:
    output = tmp_path / "governance.png"
    build_correctness_governance_figure(output)
    with Image.open(output) as image:
        assert image.width >= 1800
        assert image.height >= 1000


def test_correctness_governance_figure_is_not_blank(tmp_path: Path) -> None:
    output = tmp_path / "governance.png"
    build_correctness_governance_figure(output)
    with Image.open(output).convert("RGB") as image:
        colors = image.resize((100, 56)).getcolors(maxcolors=5600)
        assert colors is not None
        assert len(colors) >= 10
```

- [ ] **Step 2: Run tests and verify the missing-module failure**

Run: `python -m pytest -q tests/test_build_correctness_governance_figures.py`

Expected: collection fails with `ModuleNotFoundError: reports.build_correctness_governance_figures`.

- [ ] **Step 3: Implement the governance-loop figure**

Create a Matplotlib figure with five linked stages:

```text
私有事实 -> 公开 -> 读取/利用 -> 解释 -> 决策
              |          |          |        |
           披露审计    引用/立场    一致性    投票/共识
              |          |          |        |
           结构交换    证据提醒    冲突核验  异常复审
```

Add a feedback arrow from `决策评估` to `选择干预`, and a bottom note stating that final correctness is the outcome metric while disclosure, use, interpretation, and voting are diagnostic indicators. Reuse the navy/blue/gold/green/red palette from `reports/build_paper_figures.py` and save with a white background.

- [ ] **Step 4: Run figure tests**

Run: `python -m pytest -q tests/test_build_correctness_governance_figures.py`

Expected: `2 passed`.

- [ ] **Step 5: Generate and visually inspect the repository figure**

Run:

```powershell
python -m reports.build_correctness_governance_figures `
  --output reports/figures/mas-correctness-governance-loop.png
```

Open the PNG and confirm all Chinese labels render, arrows do not overlap boxes, and the figure is readable at normal page width.

- [ ] **Step 6: Commit the figure unit**

```powershell
git add reports/build_correctness_governance_figures.py `
  reports/figures/mas-correctness-governance-loop.png `
  tests/test_build_correctness_governance_figures.py
git commit -m "docs: add MAS correctness governance figure"
```

---

### Task 2: Paper Content and Evidence-Locked Structure

**Files:**
- Create: `reports/build_correctness_governance_report.py`
- Create: `tests/test_build_correctness_governance_report.py`

**Interfaces:**
- Consumes: `reports/data/hiddenbench-paper-evidence-20260805.json`, `reports/data/hiddenbench-paper-references-20260805.json`, the new governance figure, and reusable formatting helpers from `reports.build_paper_style_report`.
- Produces: `build_correctness_governance_report(root: Path, output: Path, desktop_output: Path | None) -> Path`.

- [ ] **Step 1: Write the failing content-structure test**

```python
def test_report_follows_correctness_governance_thesis(tmp_path: Path) -> None:
    output = tmp_path / "correctness.docx"
    build_correctness_governance_report(ROOT, output, None)
    text = document_text(Document(output))
    for heading in [
        "1 引言",
        "2 多智能体错误现象与已有研究",
        "3 多智能体正确性治理体系",
        "4 已有工作、本文改进与原创边界",
        "5 实验设置与对标方法",
        "6 实验结果与归因分析",
        "7 总结与展望",
        "参考文献",
        "附录",
    ]:
        assert heading in text
    assert "公开、读取、解释和行动" in text
    assert "全局 Reveal-All 仅作为" in text
    assert "不能把差异单独归因" in text
```

- [ ] **Step 2: Write the failing evidence-lock test**

```python
def test_report_uses_locked_results_and_bounded_claims(tmp_path: Path) -> None:
    output = tmp_path / "correctness.docx"
    build_correctness_governance_report(ROOT, output, None)
    text = document_text(Document(output))
    for claim in [
        "11/30、4/30、6/30",
        "10/10、0/10、7/10",
        "30/30",
        "26/30",
        "17/30",
        "21/30",
        "20/30",
        "24/30",
        "p=0.125",
        "p=0.388",
        "未达到统计显著",
    ]:
        assert claim in text
    assert "FM-2.4" in text and "已确认" in text
    assert "FM-2.5" in text and "待人工因果编码" in text
    assert "FM-2.6" in text and "未确认" in text
    assert "动态发言显著优于" not in text
```

- [ ] **Step 3: Run focused tests and verify they fail**

Run: `python -m pytest -q tests/test_build_correctness_governance_report.py`

Expected: collection fails because the report builder does not yet exist.

- [ ] **Step 4: Implement the paper shell and citation tracker**

In `reports/build_correctness_governance_report.py`:

- Import `_configure_paper`, `_heading`, `_body`, `_formula`, `_caption`, `_table_caption`, `_callout`, `_figure`, `_page_break`, `_reference_entry`, `_validate_tables`, `_font`, `REFERENCE_PATH`, and `EVIDENCE_PATH` from the existing paper builder.
- Define `REPORT_NAME = "基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx"`.
- Define a `CitationTracker` that receives the reference list and exposes `cite(key: str) -> str`. The first call for a key returns `[[FN01]]`, the second new key returns `[[FN02]]`, and repeated calls return an empty string. Preserve the ordered keys for footnotes and bibliography.
- Define one function per major section: `_title_and_abstract`, `_introduction`, `_error_phenomena_and_prior_work`, `_governance_system`, `_contribution_boundaries`, `_experiment_design`, `_results_and_attribution`, `_conclusion`, `_references`, and `_appendices`.
- Keep the abstract to seven Chinese full-stop-terminated sentences and do not place citations in it.

- [ ] **Step 5: Implement the five-stage error-chain content**

The related-work and governance chapters must distinguish:

```text
公开失败：事实未出现或出现过晚
利用失败：事实出现但没有进入后续理由或投票
解释失败：事实含义或事实-选项关系被错误理解
协调失败：过早收敛、从众或发言机会不均
决策失败：理由与投票不一致或形成错误共识
```

Add a five-row governance matrix with columns `错误环节 / 可观测现象 / 观测指标 / 对应干预`. Include atomic disclosure rate, first-disclosure round, later evidence citation, stance change, rationale-evidence consistency, speaking distribution, consensus round, vote-rationale consistency, majority accuracy, and false-consensus rate.

- [ ] **Step 6: Implement prior-work and originality boundaries**

Add explicit labeled paragraphs:

```text
已有研究：HiddenBench supplies tasks and official GPT-4.1 results; MAST supplies failure categories; MAF supplies Agent/model execution.
本文实现：MAF replication, atomic-fact audit, matched-budget scheduling comparison, structured discussion, run-level error-chain coding, and governance feedback loop.
非本文原创：Hidden Profile, Reveal-All, MAST taxonomy, and Microsoft Agent Framework.
```

State that the dynamic selector is external project code with centralized access to the private-fact assignment, and that Codex blind review is model-assisted rather than human ground truth.

- [ ] **Step 7: Implement task selection and cross-implementation comparison**

Explain that ID1-ID3 were selected because the official result release provides directly comparable GPT-4.1 baseline and Reveal-All numbers for these three short tasks; they share background and answer options while changing the decisive private-fact chain. State that the study does not cover all 65 tasks.

Add a comparison table:

| Task | Official GPT-4.1 baseline | Local DeepSeek fixed-60 | Official GPT-4.1 Reveal-All | Local official-compatible Reveal-All |
|---|---:|---:|---:|---:|
| ID1 | 11/30 | 10/10 | 10/10 | 10/10 |
| ID2 | 4/30 | 0/10 | 9/10 | 10/10 |
| ID3 | 6/30 | 7/10 | 10/10 | 10/10 |

Immediately after the table, state that direction is similar but magnitudes differ, and list model, framework/message organization, protocol/budget, and uncontrolled generation randomness as candidate explanations—not established causes.

- [ ] **Step 8: Implement intervention comparisons and conclusions**

Add tables and prose for:

- Official-compatible first-round global Reveal-All: 30/30.
- Gradual fixed-reveal-all: 26/30 overall; ID2 6/10 despite final 100% disclosure.
- Fixed-60 vs dynamic-60: 17/30 vs 21/30, exact McNemar `p=0.125`.
- Fixed-12 vs structured-12: 20/30 vs 24/30, exact McNemar `p=0.388`.
- MAST mapping with FM-2.4 confirmed, FM-2.5 candidate, and FM-2.6 not confirmed.

The conclusion must state that completeness, timing, interpretation, and action jointly affect correctness, while current dynamic and structured interventions show directional but non-significant improvements.

- [ ] **Step 9: Implement appendices without duplicating the full old report**

Include:

- Appendix A: ID1-ID3 selection rationale and concise decisive evidence chains.
- Appendix B: exact discussion, vote, atomic-audit, and official global Reveal-All prompts reused from `reports.build_paper_style_report`.
- Appendix C: provenance table with official paper/code/results, local repository, branch, PR, release, and evidence hashes.
- Appendix D: terminology and conclusion boundaries.

Do not repeat all 560 run records or all 17 evidence hashes in body prose; keep reproducibility detail in appendices.

- [ ] **Step 10: Run content tests**

Run: `python -m pytest -q tests/test_build_correctness_governance_report.py -k "thesis or locked"`

Expected: the content and evidence-lock tests pass.

- [ ] **Step 11: Commit the content unit**

```powershell
git add reports/build_correctness_governance_report.py `
  tests/test_build_correctness_governance_report.py
git commit -m "docs: restructure paper around MAS correctness governance"
```

---

### Task 3: True Footnotes, Bibliography Order, and Preservation Gates

**Files:**
- Modify: `reports/build_correctness_governance_report.py`
- Modify: `tests/test_build_correctness_governance_report.py`

**Interfaces:**
- Consumes: `CitationTracker.ordered_keys`, `_patch_true_footnotes`, and `_short_note` from `reports.build_paper_style_footnotes`.
- Produces: a true-footnote DOCX with body references and footnote definitions numbered `1..N`, plus bibliography entries in the same order.

- [ ] **Step 1: Add a failing true-footnote test**

```python
def test_report_has_true_sequential_footnotes(tmp_path: Path) -> None:
    output = tmp_path / "correctness.docx"
    build_correctness_governance_report(ROOT, output, None)
    with zipfile.ZipFile(output) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        footnotes = etree.fromstring(archive.read("word/footnotes.xml"))
        body_ids = [
            int(node.get(f"{{{W_NS}}}id"))
            for node in document.xpath(".//w:footnoteReference", namespaces=NS)
        ]
        note_ids = [
            int(node.get(f"{{{W_NS}}}id"))
            for node in footnotes.xpath(".//w:footnote[number(@w:id) >= 1]", namespaces=NS)
        ]
        assert body_ids == list(range(1, len(body_ids) + 1))
        assert note_ids == body_ids
        assert len(body_ids) >= 15
```

- [ ] **Step 2: Add a failing bibliography-order test**

Parse body paragraphs between `参考文献` and `附录`; assert the number of nonempty entries equals the footnote count, entries begin `[1]`, `[2]`, and so on, and no `[[FN` marker or bracket citation remains before `参考文献`.

- [ ] **Step 3: Add a failing preservation test**

Record and assert the frozen SHA-256 values:

```python
ORIGINAL_PAPER_SHA256 = "e1aa4be327c847ddfa3987e408a1a7a5f178f798eb8903928d95ff2a37c5f668"
FOOTNOTE_PAPER_SHA256 = "4f486bf87a380b0961f69ae1e822609993297ac94c2590f6a4334851b572f575"
COMPLETE_REPORT_SHA256 = "0d56f74c359e1a7359102de678c8c8e39bd568d381e9ff2ccf37189b83f72765"
```

Also assert that a requested Desktop output is byte-identical to the repository output.

- [ ] **Step 4: Run the new tests and verify failure**

Run: `python -m pytest -q tests/test_build_correctness_governance_report.py -k "footnote or bibliography or preserves"`

Expected: failures because marker conversion and preservation gates are incomplete.

- [ ] **Step 5: Implement true-footnote generation**

Generate the formatted marker DOCX in a temporary directory, build note text from `CitationTracker.ordered_keys`, and call:

```python
_patch_true_footnotes(marked_docx, output, note_texts)
```

Before patching, write bibliography entries in first-use order with `_reference_entry(index, reference)` and `paragraph.paragraph_format.keep_together = True` so a single reference cannot split across pages.

- [ ] **Step 6: Implement preservation gates**

Hash all three old reports before generation and after copying the new output. Raise `ValueError` if any hash differs. Create parent directories and use `shutil.copyfile` for a byte-identical Desktop copy.

- [ ] **Step 7: Run all report tests**

Run: `python -m pytest -q tests/test_build_correctness_governance_report.py`

Expected: all report tests pass.

- [ ] **Step 8: Commit footnotes and preservation gates**

```powershell
git add reports/build_correctness_governance_report.py `
  tests/test_build_correctness_governance_report.py
git commit -m "docs: add true footnotes and preservation gates"
```

---

### Task 4: Generate the Final Word Deliverable

**Files:**
- Create: `reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx`
- Create outside repository: `C:/Users/liuli/Desktop/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx`

**Interfaces:**
- Consumes: `build_correctness_governance_report(...)` from Task 2/3.
- Produces: repository and Desktop DOCX copies with identical bytes.

- [ ] **Step 1: Mark the document edit operation**

Run exactly once before the first DOCX-authoring command:

```powershell
& 'C:\Users\liuli\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' `
  'C:\Users\liuli\.codex\plugins\cache\openai-primary-runtime\documents\26.813.12317\skills\documents\container_tools\mark_artifact_operation_started.mjs' `
  --operation-kind edit --expected-output-count 1 --output-format docx
```

Expected: command exits successfully.

- [ ] **Step 2: Build the repository and Desktop outputs with the bundled runtime**

Run:

```powershell
& 'C:\Users\liuli\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  -m reports.build_correctness_governance_report `
  --root . `
  --output 'reports\基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx' `
  --desktop-output 'C:\Users\liuli\Desktop\基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx'
```

Expected: both files exist.

- [ ] **Step 3: Run structural audits**

Verify:

- Word can load the DOCX with `Document(path)`.
- Body footnote references and `word/footnotes.xml` definitions are sequential and equal.
- At least 15 references are used.
- All tables have 9360-DXA width and 120-DXA indent.
- The new governance figure exists in `document.inline_shapes`.
- There are no marker tokens, unresolved bracket citations, or corrupted Chinese characters.
- Repository and Desktop SHA-256 values match.
- All three old report SHA-256 values remain frozen.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
python -m pytest -q tests/test_build_correctness_governance_figures.py `
  tests/test_build_correctness_governance_report.py
python -m pytest -q
git diff --check
```

Expected: focused tests pass, the full suite passes, and `git diff --check` prints nothing.

- [ ] **Step 5: Commit the generated deliverable**

```powershell
git add 'reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx'
git commit -m "docs: generate MAS correctness governance paper"
```

---

### Task 5: Word Render and Every-Page Visual QA

**Files:**
- Read only: final DOCX.
- Create temporary QA artifacts under `.tmp/correctness-governance-paper-render-v1/`; do not commit them.

**Interfaces:**
- Consumes: final DOCX from Task 4.
- Produces: QA-only PDF and `page-NN.png` images.

- [ ] **Step 1: Attempt the canonical document renderer**

Run the packaged `render_docx.py` with `--emit_pdf`. If LibreOffice is unavailable, record that exact failure and continue with Microsoft Word COM export, which has already rendered the preceding paper successfully on this machine.

- [ ] **Step 2: Export through Microsoft Word and rasterize with Poppler when needed**

Use Word `ExportAsFixedFormat(..., 17)` to create a PDF, then use bundled `pdftoppm.exe -png -r 140` to create one PNG per page. Catch the known `Word.Quit()` RPC warning only after verifying that a nonempty PDF exists.

- [ ] **Step 3: Inspect every page at 100% zoom**

Check all pages for:

- title, abstract, and keywords fit on page 1;
- section hierarchy follows the approved structure;
- governance-loop figure labels and arrows are readable;
- five-row governance matrix does not clip or create excessively narrow prose columns;
- official/local comparison table retains all four result columns;
- footnotes remain readable and stay on the correct pages;
- bibliography numbering is sequential and each entry stays together;
- appendices have no broken tables, missing prompt text, or accidental blank pages;
- header/footer and page numbers are consistent.

- [ ] **Step 4: Fix any layout defect and repeat full render review**

For every defect, add a regression assertion where practical, modify the builder—not the generated DOCX by hand—rebuild, rerun focused tests, rerender, and inspect every page again.

- [ ] **Step 5: Run final verification immediately before completion**

Run:

```powershell
python -m pytest -q
git diff --check
git status --short
git rev-list --left-right --count HEAD...origin/codex/budget-matched-dynamic
```

Record the final page count, output SHA-256, test count, and old-file hashes.

- [ ] **Step 6: Commit any layout fixes**

If layout changes were required:

```powershell
git add reports/build_correctness_governance_report.py `
  tests/test_build_correctness_governance_report.py `
  'reports/基于MAF的多智能体正确性治理与错误链路分析_2026-08-17.docx'
git commit -m "fix: polish correctness governance paper layout"
```

---

### Task 6: Publish to the Existing Pull Request

**Files:**
- No new local files.

**Interfaces:**
- Consumes: committed branch state.
- Produces: updated remote branch and PR #5 description.

- [ ] **Step 1: Push the branch**

Run:

```powershell
git -c http.version=HTTP/1.1 push -u origin codex/budget-matched-dynamic
```

Expected: remote advances to the final local commit.

- [ ] **Step 2: Update PR #5**

Add a concise section covering:

- correctness-governance thesis;
- five-stage error chain and intervention matrix;
- official/local comparison and attribution limitation;
- why ID1-ID3 were selected;
- the 30/30 vs 26/30 timing result;
- non-significant dynamic and structured comparisons;
- true footnotes, page count, SHA-256, and test count.

- [ ] **Step 3: Verify clean publication state**

Run:

```powershell
git status --short
git rev-list --left-right --count HEAD...origin/codex/budget-matched-dynamic
gh pr view 5 --json url,headRefName,baseRefName,body
```

Expected: clean worktree, divergence `0 0`, and PR body describes the new deliverable accurately.

