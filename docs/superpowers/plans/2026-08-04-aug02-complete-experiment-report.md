# August 2-4 Complete Experiment Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and visually verify a new Chinese Word report covering every HiddenBench × MAF experiment performed from 2026-08-02 through 2026-08-04.

**Architecture:** A deterministic summary builder first reads the saved JSONL, CSV, configuration, gate, and official-result files and freezes one cumulative evidence snapshot. A separate Word builder consumes only that snapshot plus the selected representative records, applies the `standard_business_brief` preset and `memo_masthead`, and writes new repository and Desktop DOCX files. Structural tests and a Word-to-PDF-to-PNG render loop protect the statistical wording and layout.

**Tech Stack:** Python 3.12, `json`, `csv`, `hashlib`, `python-docx`, OOXML table geometry, Microsoft Word COM export, Poppler `pdftoppm`, pytest.

## Global Constraints

- Preserve every existing report; create `reports/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx` and the same-named Desktop copy.
- Use only saved experiment artifacts; do not call DeepSeek or incur API cost.
- Lock local run counts to 560, discussion/vote API requests to 25,531, audit API requests to 397, and total model requests to 25,928.
- Keep 8/2-8/3 exploratory results separate from 8/4 official-task confirmatory results.
- State that Codex blind review and the 144-item filled sign-off sheet are not human gold labels.
- State that MAF is the execution layer and that the dynamic selector is a privileged centralized external scheduler.
- Replace the outdated “answer reversal” description with the verified 2-2 final tie.
- Use Letter portrait, 1-inch margins, 9360-DXA tables, 120-DXA table indent, and visual inspection of every rendered page.

---

### Task 1: Freeze the August 2-4 evidence snapshot

**Files:**
- Create: `reports/build_aug02_complete_summary.py`
- Create: `reports/data/hiddenbench-aug02-complete-summary.json`
- Test: `tests/test_aug02_complete_summary.py`

**Interfaces:**
- Consumes: the six formal run JSONLs, five audit JSONLs, their gate/config files, `reports/data/hiddenbench-confirmatory-summary.json`, `reports/data/hiddenbench-hardened-analysis-20260804.json`, and the 144-item blind-review summary.
- Produces: `build_complete_summary(root: Path) -> dict[str, Any]` and `write_complete_summary(root: Path, output: Path) -> Path`.

- [ ] **Step 1: Write the failing snapshot test**

```python
def test_complete_summary_locks_scope_and_boundaries(tmp_path: Path) -> None:
    summary = build_complete_summary(ROOT)
    assert summary["scope"] == {
        "local_runs": 560,
        "discussion_vote_api_requests": 25531,
        "audit_api_requests": 397,
        "total_model_requests": 25928,
        "confirmatory_runs": 210,
        "official_global_reveal_runs": 30,
    }
    assert summary["blind_review"]["status"] == "not_human_gold"
    assert summary["early_stop"]["classifications"] == {
        "same-majority": 29,
        "final-tie": 1,
    }
    assert summary["paired_tests"]["fixed-60_vs_dynamic-60"]["p_value"] == 0.125
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `python -m pytest -q tests/test_aug02_complete_summary.py`

Expected: collection fails because `reports.build_aug02_complete_summary` does not exist.

- [ ] **Step 3: Implement artifact loading and locked checks**

```python
RUN_FILES = {
    "governance": "artifacts/hiddenbench-governance-20260802.jsonl",
    "structured": "artifacts/hiddenbench-structured-20260802.jsonl",
    "contrast": "artifacts/hiddenbench-contrast-20260803.jsonl",
    "earlystop": "artifacts/hiddenbench-earlystop-20260803.jsonl",
    "confirmatory": "artifacts/hiddenbench-confirmatory-20260804.jsonl",
    "official_global_reveal": "artifacts/hiddenbench-official-reveal-supplement-20260804.jsonl",
}

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def _run_api_requests(rows: list[dict[str, Any]]) -> int:
    return sum(int(row["run"]["provider_metadata"]["api_requests"]) for row in rows)
```

The builder must validate all six expected row counts `(80, 40, 120, 80, 210, 30)`, all available gate booleans, audit counts `(80, 40, 40, 80, 210)`, source SHA-256 values, official GPT-4.1 results, disclosure example arithmetic, MAST cases, and paired statistics before writing JSON.

- [ ] **Step 4: Run snapshot tests**

Run: `python -m pytest -q tests/test_aug02_complete_summary.py`

Expected: all tests pass and two independently written snapshots have identical bytes.

- [ ] **Step 5: Generate and commit the snapshot**

```powershell
python reports\build_aug02_complete_summary.py
git add reports/build_aug02_complete_summary.py reports/data/hiddenbench-aug02-complete-summary.json tests/test_aug02_complete_summary.py
git commit -m "data: summarize Aug 2-4 HiddenBench experiments"
```

### Task 2: Build the complete Word report

**Files:**
- Create: `reports/build_aug02_complete_report.py`
- Create: `reports/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx`
- Test: `tests/test_build_aug02_complete_report.py`

**Interfaces:**
- Consumes: `reports/data/hiddenbench-aug02-complete-summary.json`, the selected ID1 dynamic-60 repetition-2 run/audit, and the first official-global-reveal public message.
- Produces: `build_report(root: Path, output: Path, desktop_output: Path | None) -> Path`.

- [ ] **Step 1: Write the failing content and geometry test**

```python
def test_complete_report_contains_required_results(tmp_path: Path) -> None:
    output = tmp_path / "complete.docx"
    build_report(root=ROOT, output=output, desktop_output=None)
    text = extract_text(Document(output))
    for phrase in (
        "560 次本地运行",
        "25,928 次模型请求",
        "3 disclosed / 4 total = 75.0%",
        "2-2 final tie",
        "generation seed was not transmitted",
        "FM-2.4",
        "FM-2.5",
        "FM-2.6",
        "0.125",
        "0.388",
    ):
        assert phrase in text
    assert "答案翻转" not in text
    assert "人工金标准已完成" not in text
```

Add a second test that verifies Letter geometry, one-inch margins, at least 15 tables, every table `tblW=9360 dxa` and `tblInd=120 dxa`, and unchanged SHA-256 values for all pre-existing Word reports.

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `python -m pytest -q tests/test_build_aug02_complete_report.py`

Expected: collection fails because `reports.build_aug02_complete_report` does not exist.

- [ ] **Step 3: Implement the Word builder**

Use `standard_business_brief` tokens and the `memo_masthead` opening. Build these visible sections in order: technical summary; direct answers to the teacher; dated timeline; paper/framework boundary; task and metric definitions; August 2 results; August 3 results; August 4 confirmatory results; official comparison; disclosure prompt and 75% case; paired tests and same-trajectory early stop; MAST cases; limitations and robustness; next steps and further questions; task/prompt/provenance appendices.

The builder must read the locked JSON snapshot rather than duplicating numeric constants throughout the document. Tables must use repeated header rows, exact fixed DXA widths, expandable row heights, 80/80/120/120-DXA cell margins, and explicit fonts for Latin and East Asian text.

- [ ] **Step 4: Generate the report with the bundled document Python**

```powershell
$env:PYTHONPATH='.;src'
& 'C:\Users\liuli\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' reports\build_aug02_complete_report.py
```

Expected: repository and Desktop DOCX files exist and have identical SHA-256 values.

- [ ] **Step 5: Run focused report tests and commit**

```powershell
python -m pytest -q tests\test_build_aug02_complete_report.py
git add reports/build_aug02_complete_report.py tests/test_build_aug02_complete_report.py reports/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx
git commit -m "docs: add complete Aug 2-4 experiment report"
```

### Task 3: Render and visually inspect every page

**Files:**
- Create only ignored QA intermediates under `.tmp/aug02-complete-report-render/`.
- Modify: `reports/build_aug02_complete_report.py` only if a visual defect is found.

**Interfaces:**
- Consumes: final repository DOCX.
- Produces: Word-exported PDF and one PNG per page for internal QA only.

- [ ] **Step 1: Export DOCX to PDF with Microsoft Word COM**

Open the repository DOCX read-only in a hidden Word instance, call `ExportAsFixedFormat(..., 17)`, record the Word page count, close the document, and quit Word.

- [ ] **Step 2: Render every PDF page to PNG**

Run the bundled Poppler executable at 144 DPI and write `.tmp/aug02-complete-report-render/pages/page-NN.png`.

- [ ] **Step 3: Inspect every page at original detail**

Check title hierarchy, Chinese glyphs, paragraph spacing, table wrapping, repeated headers, page breaks, code blocks, footer page numbers, right-edge clipping, and unnecessary blank pages. Inspect every page, not a sample.

- [ ] **Step 4: Fix and rerender if required**

For each defect, add or adjust deterministic builder formatting, regenerate both DOCX copies, rerun focused tests, re-export, and reinspect all pages.

- [ ] **Step 5: Record a clean visual gate**

Expected: every page is readable with no clipping, overlap, missing glyph, broken table, or meaningless blank page.

### Task 4: Final verification and handoff

**Files:**
- Verify: new DOCX, summary JSON, builder scripts, and tests.

**Interfaces:**
- Consumes: the committed report tree.
- Produces: a final evidence-backed handoff with one DOCX output citation.

- [ ] **Step 1: Run focused and full tests**

```powershell
python -m pytest -q tests\test_aug02_complete_summary.py tests\test_build_aug02_complete_report.py
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Recompute data and document integrity checks**

Verify all six run counts, all five audit counts, all gate booleans, output/source SHA-256 values, no credential-like text, `git diff --check`, and identical repository/Desktop report bytes.

- [ ] **Step 3: Confirm Git status and latest commits**

The worktree may be ahead of the existing PR branch but must contain no untracked or unstaged report changes.

- [ ] **Step 4: Deliver only the final Word report**

In the final response, summarize the date range, total experimental scope, main corrections, and verification result. Cite `C:/Users/liuli/Desktop/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx` exactly once with `purpose="output"`.
