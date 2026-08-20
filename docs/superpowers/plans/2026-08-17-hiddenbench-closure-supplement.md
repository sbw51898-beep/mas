# HiddenBench Closure Supplement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed supplement that closes all automatable teacher requirements while clearly isolating human-review and GPT-4.1 dependencies.

**Architecture:** A small analysis module reads the frozen confirmatory JSONL and emits a machine-readable closure snapshot. A report builder consumes that snapshot to create a new Word paper. Blind-review utilities emit two independently shuffled, label-blind workbooks and validate/merge completed human sheets.

**Tech Stack:** Python 3.11+, Pydantic, python-docx, openpyxl, pytest, existing HiddenBench JSONL artifacts.

## Global Constraints

- Never rewrite the existing 2026-08-17 final Word.
- Never label model review as human review.
- Use only the frozen confirmation artifacts for quantitative claims.
- Treat the current DeepSeek endpoint as unsuitable evidence for GPT-4.1 results.

---

### Task 1: Derive formal single-agent and causal-chain evidence

**Files:**
- Create: `src/mas_experiment/hiddenbench_closure.py`
- Create: `reports/build_hiddenbench_closure_evidence.py`
- Create: `tests/test_hiddenbench_closure.py`

- [ ] **Step 1: Write failing tests** for derived single-local/full/fixed results and for three causal cards with exact run IDs and evidence messages.
- [ ] **Step 2: Run the focused tests** and verify they fail because the new module is absent.
- [ ] **Step 3: Implement the minimal parser and validators** that read the frozen JSONL and emit a closure JSON snapshot.
- [ ] **Step 4: Re-run focused tests** and verify they pass.

### Task 2: Create actual-human dual-blind signoff tooling

**Files:**
- Create: `reports/build_dual_blind_review_pack.py`
- Create: `reports/merge_dual_blind_reviews.py`
- Create: `tests/test_dual_blind_review_pack.py`

- [ ] **Step 1: Write failing tests** asserting A/B sheets have identical blind cases in different deterministic orders and that merge rejects non-human/missing decisions.
- [ ] **Step 2: Run the focused tests** and verify they fail.
- [ ] **Step 3: Implement workbook generation and merge validation** without adding labels to review sheets.
- [ ] **Step 4: Re-run focused tests** and verify they pass.

### Task 3: Update the report with bounded conclusions

**Files:**
- Create: `reports/build_hiddenbench_closure_report.py`
- Create: `tests/test_build_hiddenbench_closure_report.py`
- Create: `reports/基于MAF的多智能体正确性治理与错误链路分析_闭环补充版_2026-08-17.docx`

- [ ] **Step 1: Write failing document-content tests** for disclosure rules, diagnostic continuation, single-agent table, causal cards and limitations.
- [ ] **Step 2: Run the focused test** and verify it fails.
- [ ] **Step 3: Implement a new builder** that consumes the new closure snapshot and preserves citations/footnotes.
- [ ] **Step 4: Re-run document tests** and render all pages for visual QA.

### Task 4: Verify and publish the supplemental evidence

**Files:**
- Modify: `reports/data/hiddenbench-closure-evidence-20260817.json`
- Create: `reports/盲审签核表_审阅者A_2026-08-17.xlsx`
- Create: `reports/盲审签核表_审阅者B_2026-08-17.xlsx`

- [ ] **Step 1: Run the full project test suite using the installed Miniconda runtime.**
- [ ] **Step 2: Generate evidence, workbooks and report; verify hashes and rendered pages.**
- [ ] **Step 3: Commit only task-related files and push the current branch.**
