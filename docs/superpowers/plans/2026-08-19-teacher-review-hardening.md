# Teacher Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining teacher-facing ambiguities in the HiddenBench/MAF report without changing the frozen experiment results or overwriting the previous report.

**Architecture:** Keep the frozen JSONL and audit values unchanged. Modify the report generator and its regression tests so the report distinguishes participant discussion from independent audit self-report, labels every cross-implementation denominator, states the MAF execution-layer boundary, and exposes the compute/privileged-information limitations of dynamic-60. Add a versioned evidence manifest and a new release/commit entry point for the revised package.

**Tech Stack:** Python, python-docx, pytest, LibreOffice renderer, Git/GitHub CLI.

**Spec:** Teacher-review findings from the 2026-08-19 report audit.

## Global Constraints

- Preserve all original DOCX files; generate a new dated DOCX.
- Do not alter frozen experiment JSONL, frozen audit labels, or reported counts.
- Do not claim dynamic-60 is a fair causal baseline or that audit self-report proves label correctness.
- Keep the report's existing footnote order and 28-page-readable style where possible.
- New evidence entry must point to the revised commit/manifest; old Release may remain historical but must not be the only handoff path.

### Task 1: Add regression tests for teacher-facing distinctions

**Files:**
- Modify: `tests/test_build_hiddenbench_closure_report.py`

- [ ] **Step 1: Add failing assertions** for: independent audit-model wording; participant self-report distinction; official/local denominator labels; MAF execution-layer boundary; exploratory clustered-sample caveat; new manifest/release entry; group-vs-owner metric boundary.
- [ ] **Step 2: Run the focused report tests** and confirm the new assertions fail against the current report.

### Task 2: Revise report content and evidence metadata

**Files:**
- Modify: `reports/build_hiddenbench_closure_report.py`
- Modify: `reports/data/hiddenbench-teacher-review-20260819.manifest.json`

- [ ] **Step 1: Rename supplementary self-report language** to “独立审计模型自报披露率”; state that participating Agents did not emit the percentage and that 60/60 is only an arithmetic consistency check.
- [ ] **Step 2: Add explicit official/local sample-size and percentage columns/notes** and state that 30-run official results and 10-run local results are directional only.
- [ ] **Step 3: Put the dynamic-60 fairness limitation in the abstract and comparison table note**, including 132 vs 72 response slots and privileged private-fact access.
- [ ] **Step 4: State the MAF boundary**: Agent/Agent.run and optional MAF group-chat execution layer, with project-owned protocol/selector; include resolved package versions when available and state the run's missing exact resolved versions if not recorded.
- [ ] **Step 5: Add the statistical boundary**: three shared-background tasks, 10 repeats each, no synchronized generation seed, and p-values treated as exploratory rather than population-level inference; note no multiplicity correction.
- [ ] **Step 6: Clarify D_owner versus D_group and package-level versus clause-level measurement**, including that “atomic-fact” is an internal ID, not a clause-level gold label.
- [ ] **Step 7: Replace the old Release-only handoff sentence with the new manifest/commit/release entry**, while retaining the old Release as historical source for the large frozen JSONL assets.

### Task 3: Regenerate and verify the revised report

**Files:**
- Create: `reports/基于MAF的HiddenBench多智能体正确性诊断与错误链路分析_老师问题全部修订版_2026-08-20.docx`

- [ ] **Step 1:** Run the report generator to a new dated filename and copy it to Desktop.
- [ ] **Step 2:** Run `py_compile` and the focused/full pytest suites.
- [ ] **Step 3:** Render the DOCX to a fresh QA directory and inspect every generated page for clipping, stale wording, tables, and footnotes.
- [ ] **Step 4:** Extract text and assert no old “AI self-report” or old Release-only claims remain.

### Task 4: Fix evidence handoff

**Files:**
- Modify: `reports/data/hiddenbench-teacher-review-20260819.manifest.json`
- Create: Git tag/release for the revised package, if GitHub authentication and asset limits permit.

- [ ] **Step 1:** Add final report/script/manifest/self-report hashes and explicit historical-source links to the manifest.
- [ ] **Step 2:** Commit the revised package and push the branch.
- [ ] **Step 3:** Create/update a GitHub Release or otherwise make the new manifest/commit the primary evidence entry; preserve the old Release as a historical asset source.

### Task 5: Final verification

- [ ] **Step 1:** Re-run hash verification from the manifest.
- [ ] **Step 2:** Confirm the Desktop and worktree DOCX hashes match.
- [ ] **Step 3:** Confirm Git status, commit hash, PR title/body, and release/manifest URL.
