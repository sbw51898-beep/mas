# HiddenBench Report Hardening Design

## Goal

Turn the current HiddenBench confirmatory report into a defensible advisor-facing revision without invalidating or rewriting the frozen 210-run evidence bundle.

## Chosen approach

Keep the existing seven-condition confirmatory study immutable and add one separately gated supplement that reproduces the authors' Reveal-All timing exactly. The supplement uses the same official short tasks (ID1/ID2/ID3), the same DeepSeek model settings, the same fixed 60-speech round-robin protocol, and ten repetitions per task. It differs from the current owner-by-owner reveal condition only in disclosure timing: during round 1, every response receives the complete four-fact global reveal block, matching the official result files.

This is preferred to a report-only patch because it resolves the protocol mismatch with evidence. It is preferred to rebuilding the entire confirmatory matrix because the existing run, audit, gate, release, and commit provenance remain valid and independently reproducible.

## Scope

### 1. Official-compatible Reveal-All supplement

- Add a protocol option that appends all four atomic private facts to every round-1 response and never appends the block in rounds 2-15.
- Do not replace or rename stored condition identifiers in the frozen 210-run artifacts.
- Run 3 tasks x 10 repetitions = 30 supplementary runs with fixed round-robin and exactly 60 public speeches per run.
- Reuse the locked task contents and per-task/repetition assignment seeds from the confirmatory configuration.
- Record that the pair seed controls assignment construction only. `MAFPromptProvider` does not transmit a generation seed to DeepSeek.
- Produce append-only JSONL, a compact summary, a trace file, a gate, and a SHA-256 manifest under a distinct `official-reveal-supplement` basename.
- Mechanically verify 100% disclosure, round-1-only injection, 60-message budgets, unique study keys, model settings, task hashes, assignment fingerprints, and credential safety.

### 2. Statistical and early-stop corrections

- Add Wilson 95% confidence intervals to every task-condition majority-accuracy proportion in the revised report.
- Add exact paired McNemar tests for the predeclared local contrasts:
  - fixed-60 vs dynamic-60;
  - fixed owner-reveal vs dynamic owner-reveal;
  - fixed-12 vs structured-12.
- Treat the official GPT-4.1 files and local DeepSeek runs as unpaired, cross-model descriptive comparisons only.
- Replace the phrase "one reversal" with the verified event: one early unanimous candidate later became a 2-2 final tie. Report candidate and final accuracy as 17/30 in both cases.
- Do not claim that any local mechanism is statistically superior unless the paired exact test supports that claim.

### 3. Methodological boundary corrections

- Rename the current report labels `fixed-reveal-all` and `dynamic-reveal-all` to "owner-by-owner mechanical reveal" in prose and tables; preserve stored IDs for reproducibility.
- Describe the new supplement as "official-compatible global Reveal-All".
- Describe MAF accurately as the model-agent execution layer. Fixed, dynamic, structured, reveal, gate, and audit protocols are project code.
- Describe the five-factor scheduler as an external centralized scheduler with privileged access to the assignment's private-fact inventory. Do not call it decentralized.
- State that its runtime lexical `undisclosed` feature is not the same measurement as the post-run AI-plus-rule atomic disclosure audit.
- State that the five selector weights are fixed design choices without sensitivity-analysis support.

### 4. Concrete evidence added to the report

- Add a three-task appendix containing, for ID1/ID2/ID3:
  - scenario name;
  - public context and decision question;
  - each of the four private facts;
  - correct answer and the evidence chain that determines it.
- Add one end-to-end disclosure example containing:
  - study key and run ID;
  - the four atomic facts;
  - the AI JSON judgments;
  - rule validation outcome;
  - explicit arithmetic such as `3 disclosed / 4 total = 75%`;
  - the exact CSV/JSONL artifact paths.
- Add concrete MAST evidence:
  - one FM-2.4 confirmed non-disclosure trace;
  - one FM-2.5 candidate with complete disclosure but wrong consensus, including message and vote evidence;
  - FM-2.6 reported as unconfirmed unless a rationale-vote inconsistency is directly verified.
- State that the current 210-run audit uses DeepSeek judgments with deterministic evidence checks and is not human ground truth.

### 5. Revised deliverables

- Preserve `HiddenBench确认性修订实验报告_2026-08-04.docx` unchanged.
- Create `HiddenBench确认性完善实验报告_2026-08-04.docx` in the repository and copy the identical file to the Desktop.
- Generate the DOCX from checked-in source code and checked-in compact summaries; raw API artifacts remain ignored and are packaged separately.
- Update the existing feature branch and PR only after all tests and gates pass.

## Testing strategy

1. Write failing unit tests for global round-1 reveal timing, exact block contents, and no later-round injection.
2. Write failing gate tests for missing runs, wrong message budgets, incomplete global reveal, mismatched assignments, and invalid model metadata.
3. Write failing calculation tests for Wilson intervals, paired exact tests, and the early-stop tie classification.
4. Implement the minimum code needed to pass each test group.
5. Run a no-API offline smoke study before the real DeepSeek supplement.
6. Run the 30 real supplementary runs and the deterministic gate.
7. Recompute all compact summaries from raw artifacts.
8. Build the new DOCX, validate OOXML structure and table geometry, and export through Microsoft Word to PDF for page-image inspection if Word COM is available. If neither Word nor LibreOffice rendering is available, report the visual-QA limitation explicitly.
9. Run the full test suite, secret scan, artifact hash verification, and clean-worktree check before commit and push.

## Acceptance criteria

- Existing 210-run artifacts and their hashes are unchanged.
- The new supplement contains exactly 30 unique real-model runs and passes every gate check.
- Every supplement run has exactly 60 public messages; all four global facts are mechanically present in each round-1 response and absent as injected blocks thereafter.
- The report no longer calls the owner-by-owner condition an exact reproduction of official Reveal-All.
- The report no longer implies that DeepSeek randomness was seed-controlled.
- The early-stop event is described as a loss of unanimity to a tie, not an answer reversal.
- Confidence intervals and paired exact-test results are visible beside the relevant claims.
- The report contains the complete three-task setup, a reproducible disclosure calculation, and concrete MAST evidence boundaries.
- Repository and Desktop DOCX copies have identical SHA-256 hashes.
- Full tests, data gates, secret scans, and final document checks pass.

