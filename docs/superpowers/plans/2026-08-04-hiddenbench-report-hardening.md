# HiddenBench Report Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately gated, official-compatible Reveal-All supplement and produce a statistically and methodologically corrected advisor-facing Word report without changing the frozen 210-run evidence.

**Architecture:** Extend the existing fixed HiddenBench protocol with a distinct global-round-one reveal mode, then run that mode through a small standalone supplement study and gate. Build all statistical corrections and concrete evidence tables from immutable JSONL artifacts, and generate a new DOCX while retaining the old report.

**Tech Stack:** Python 3.13, Pydantic, Typer, Microsoft Agent Framework, DeepSeek OpenAI-compatible API, pytest, python-docx, Microsoft Word COM/PDF rendering when available.

## Global Constraints

- Preserve `artifacts/hiddenbench-confirmatory-20260804.jsonl`, its audits, gate, and published SHA-256 values byte-for-byte.
- Preserve `reports/HiddenBench确认性修订实验报告_2026-08-04.docx` and the Desktop copy unchanged.
- Store the 30-run supplement under the distinct basename `hiddenbench-official-reveal-supplement-20260804`.
- The supplement uses task IDs 1, 2, and 3; ten repetitions per task; four agents; fixed round-robin; fifteen rounds; sixty public speeches; `deepseek-v4-flash`; temperature 0; thinking disabled.
- Pair seeds control assignment construction only; never claim that DeepSeek generation randomness was seeded.
- Use `apply_patch` for hand-written source and test changes.
- Do not commit raw API JSONL artifacts or credentials.

---

### Task 1: Add official-compatible global round-one reveal semantics

**Files:**
- Modify: `src/mas_experiment/hiddenbench_protocol.py`
- Modify: `src/mas_experiment/hiddenbench_atomic_disclosure.py`
- Modify: `src/mas_experiment/hiddenbench_domain.py`
- Test: `tests/test_hiddenbench_atomic_disclosure.py`

**Interfaces:**
- Consumes: `decompose_private_facts(assignment) -> tuple[AtomicPrivateFact, ...]` and `append_reveal_all_block(content, facts)`.
- Produces: `run_hiddenbench_task(..., mechanical_global_reveal_round_one: bool = False) -> HiddenBenchRawRun | ShadowVotingRun` and message metadata keys `global_reveal_round_one`, `appended_fact_ids`.

- [ ] **Step 1: Write failing protocol tests**

Add tests that call `run_hiddenbench_task(..., discussion_rounds=2, mechanical_global_reveal_round_one=True)` and assert:

```python
assert len(run.discussion_messages) == 8
for message in run.discussion_messages[:4]:
    assert message.provider_metadata["global_reveal_round_one"] is True
    assert len(message.provider_metadata["appended_fact_ids"]) == 4
for message in run.discussion_messages[4:]:
    assert message.provider_metadata["global_reveal_round_one"] is False
    assert message.provider_metadata["appended_fact_ids"] == []
```

Also assert every round-1 message contains every exact atomic fact and that each round-2 message contains no mechanically appended header.

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest -q tests/test_hiddenbench_atomic_disclosure.py -k global_reveal`

Expected: failure because `mechanical_global_reveal_round_one` and its metadata do not exist.

- [ ] **Step 3: Implement the protocol flag**

In `run_hiddenbench_task`, decompose all assignment facts once. When `mechanical_global_reveal_round_one and round_index == 1`, pass all facts to `append_reveal_all_block` for each of the four round-1 responses. Keep the existing `mechanical_reveal_all` owner-only behavior unchanged.

Include the new flag in provider metadata and `_configuration_fingerprint` so owner-reveal and global-reveal runs cannot share a fingerprint.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_hiddenbench_atomic_disclosure.py tests/test_hiddenbench_confirmatory_gate.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mas_experiment/hiddenbench_protocol.py src/mas_experiment/hiddenbench_atomic_disclosure.py src/mas_experiment/hiddenbench_domain.py tests/test_hiddenbench_atomic_disclosure.py
git commit -m "feat: add official global reveal protocol"
```

### Task 2: Build the standalone supplement study, resume logic, gate, and CLI

**Files:**
- Create: `src/mas_experiment/hiddenbench_official_reveal_supplement.py`
- Create: `src/mas_experiment/hiddenbench_official_reveal_gate.py`
- Create: `configs/hiddenbench-official-reveal-supplement-20260804.json`
- Modify: `src/mas_experiment/cli.py`
- Test: `tests/test_hiddenbench_official_reveal_supplement.py`
- Test: `tests/test_hiddenbench_official_reveal_gate.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `OfficialRevealSupplementKey(task_id: int, repetition: int)`.
- Produces `OfficialRevealSupplementRecord(key, pair_seed, assignment_fingerprint, run_commit, code_commit, run)`.
- Produces `run_official_reveal_supplement(*, tasks, config, provider_factory, output, resume) -> tuple[OfficialRevealSupplementRecord, ...]`.
- Produces `build_official_reveal_gate(config, records, dataset_path) -> OfficialRevealSupplementGate`.
- Adds CLI commands `run-hiddenbench-official-reveal-supplement`, `resume-hiddenbench-official-reveal-supplement`, and `gate-hiddenbench-official-reveal-supplement`.

- [ ] **Step 1: Write failing domain/resume/gate tests**

Create a reduced offline fixture with one task and two repetitions. Assert deterministic ordering, append-only resume, exact 60-message production in the real configuration, four round-1 global reveal blocks, no later blocks, unique keys, correct task hash, assignment fingerprint, model settings, and credential scan.

The complete fixture gate must satisfy:

```python
assert gate.passed is True
assert all(gate.checks.values())
```

Deleting one record or one appended fact must make the named check false.

- [ ] **Step 2: Run the new tests and verify failure**

Run: `python -m pytest -q tests/test_hiddenbench_official_reveal_supplement.py tests/test_hiddenbench_official_reveal_gate.py tests/test_cli.py -k "official_reveal or command"`

Expected: import and command-registration failures.

- [ ] **Step 3: Implement config and study runner**

Use the confirmatory task validator and `derive_pair_seed(base_seed, task_id, repetition)`. Each record calls:

```python
raw = await run_hiddenbench_task(
    task,
    provider,
    seed=pair_seed,
    discussion_rounds=15,
    assignment=assignment,
    mechanical_global_reveal_round_one=True,
)
```

Score with `score_hiddenbench_run(raw)`, append one JSON object per line, and accept only a deterministic prefix on resume.

- [ ] **Step 4: Implement gate and CLI**

The gate must name checks for complete matrix, unique keys, deterministic order, task/dataset hashes, assignments, 60-message shape, global reveal timing, provider settings, code provenance, and credential scan. The CLI must use `StabilityOfflineProvider` with `--offline`, otherwise `DeepSeekSettings.from_env()` and `MAFPromptProvider`.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest -q tests/test_hiddenbench_official_reveal_supplement.py tests/test_hiddenbench_official_reveal_gate.py tests/test_cli.py`

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add src/mas_experiment/hiddenbench_official_reveal_supplement.py src/mas_experiment/hiddenbench_official_reveal_gate.py src/mas_experiment/cli.py configs/hiddenbench-official-reveal-supplement-20260804.json tests/test_hiddenbench_official_reveal_supplement.py tests/test_hiddenbench_official_reveal_gate.py tests/test_cli.py
git commit -m "feat: add official reveal supplement study"
```

### Task 3: Add reproducible statistical and evidence summaries

**Files:**
- Create: `reports/build_hardened_confirmatory_summaries.py`
- Test: `tests/test_hardened_confirmatory_summaries.py`

**Interfaces:**
- Produces `wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]`.
- Produces `exact_paired_mcnemar(a: Sequence[bool], b: Sequence[bool]) -> dict[str, int | float]` with `a_only`, `b_only`, `discordant`, and `p_value`.
- Produces `classify_early_stop(row) -> Literal["same-majority", "final-tie", "different-majority", "no-candidate"]`.
- Writes `reports/data/hiddenbench-hardened-analysis-20260804.json`, `reports/data/hiddenbench-hardened-statistics-20260804.csv`, and `reports/data/hiddenbench-mast-cases-20260804.csv`.

- [ ] **Step 1: Write failing calculation tests**

Test known Wilson values, including 10/10 approximately `[0.7225, 1.0]`, and exact McNemar values:

```python
assert exact_paired_mcnemar([False] * 4, [True] * 4)["p_value"] == 0.125
```

Test the observed ID3 repetition 4 early-stop row classifies as `final-tie`, not `different-majority`, and candidate/final correctness totals are both 17/30.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest -q tests/test_hardened_confirmatory_summaries.py`

Expected: module import failure.

- [ ] **Step 3: Implement statistics and summary builder**

Read the frozen 210-run JSONL, its atomic audits, the official GPT-4.1 summary, and the 30-run supplement. Recompute all headline values from raw numerators and denominators. Use exact two-sided binomial probability over discordant pairs for McNemar; do not use an asymptotic chi-square approximation.

Build concrete MAST rows with study key, run ID, category, evidence message IDs, final votes, disclosure rate, and a boundary field containing one of `confirmed`, `candidate-needs-human-causal-coding`, or `not-confirmed`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_hardened_confirmatory_summaries.py tests/test_confirmatory_summaries.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add reports/build_hardened_confirmatory_summaries.py tests/test_hardened_confirmatory_summaries.py
git commit -m "feat: add hardened confirmatory statistics"
```

### Task 4: Run offline smoke and the 30 real DeepSeek supplement runs

**Files:**
- Generate ignored: `artifacts/hiddenbench-official-reveal-supplement-offline-smoke.jsonl`
- Generate ignored: `artifacts/hiddenbench-official-reveal-supplement-20260804.jsonl`
- Generate ignored: corresponding gate, trace, summary, provenance, and manifest files
- Generate tracked: `reports/data/hiddenbench-official-reveal-supplement-summary.json`

**Interfaces:**
- Consumes the Task 2 CLI and Task 3 summary builder.
- Produces the only new API-derived evidence used by the revised report.

- [ ] **Step 1: Run offline smoke**

Run:

```powershell
python -m mas_experiment.cli run-hiddenbench-official-reveal-supplement --offline --output artifacts/hiddenbench-official-reveal-supplement-offline-smoke.jsonl
```

Expected: the supplement gate passes with zero external API calls.

- [ ] **Step 2: Verify DeepSeek credential availability without printing it**

Run: `if (Test-Path Env:DEEPSEEK_API_KEY) { 'configured' } else { 'missing' }`

Expected: `configured`. If missing, use the existing approved local environment-loading mechanism; never print or copy the key into a file.

- [ ] **Step 3: Run or resume the real supplement**

Run:

```powershell
python -m mas_experiment.cli resume-hiddenbench-official-reveal-supplement --output artifacts/hiddenbench-official-reveal-supplement-20260804.jsonl
```

Expected: exactly 30 records and a passed gate. Resume on transient API failure until the deterministic matrix is complete.

- [ ] **Step 4: Build and verify summaries**

Run: `python reports/build_hardened_confirmatory_summaries.py`

Expected: summary source counts and hashes agree with the raw supplement; existing confirmatory artifact hashes remain unchanged.

- [ ] **Step 5: Commit compact evidence only**

```powershell
git add reports/data/hiddenbench-official-reveal-supplement-summary.json reports/data/hiddenbench-hardened-analysis-20260804.json reports/data/hiddenbench-hardened-statistics-20260804.csv reports/data/hiddenbench-mast-cases-20260804.csv
git commit -m "data: add official reveal supplement results"
```

### Task 5: Build the corrected advisor-facing Word report

**Files:**
- Create: `reports/build_hardened_confirmatory_report.py`
- Create: `reports/HiddenBench确认性完善实验报告_2026-08-04.docx`
- Copy: `C:/Users/liuli/Desktop/HiddenBench确认性完善实验报告_2026-08-04.docx`
- Test: `tests/test_build_hardened_confirmatory_report.py`

**Interfaces:**
- Consumes the frozen confirmatory summary, official GPT-4.1 summary, supplement summary, hardened analysis JSON, statistics CSV, MAST CSV, raw run/audit examples, and locked task dataset.
- Produces a standalone DOCX; it must not require the earlier report to understand the study.

- [ ] **Step 1: Write failing report-content tests**

Build into a temporary path and assert extracted DOCX text contains:

```python
required = (
    "official-compatible global Reveal-All",
    "owner-by-owner mechanical reveal",
    "generation seed was not transmitted",
    "external centralized scheduler",
    "Wilson 95%",
    "McNemar",
    "2-2 final tie",
    "3 disclosed / 4 total = 75%",
    "FM-2.4",
    "FM-2.5",
    "FM-2.6",
)
```

Also assert ID1/ID2/ID3 each include public context, four private facts, correct answer, and evidence chain. Assert the original DOCX SHA-256 is unchanged.

- [ ] **Step 2: Run report tests and verify failure**

Run: `python -m pytest -q tests/test_build_hardened_confirmatory_report.py`

Expected: module import or missing-content failure.

- [ ] **Step 3: Implement the report builder**

Use a formal business-report layout with explicit 9360-DXA table geometry. Lead with an answer-to-advisor table, then methods, official protocol comparison, results with intervals, paired tests, early-stop correction, task cards, disclosure example, MAST evidence, limitations, prompts, artifact hashes, and GitHub links.

Do not state causal superiority. Label official-versus-local numbers as cross-model descriptive comparisons. State that AI-plus-rule audit is not human ground truth.

- [ ] **Step 4: Run report tests and structural checks**

Run: `python -m pytest -q tests/test_build_hardened_confirmatory_report.py tests/test_build_confirmatory_report.py`

Expected: all pass; DOCX ZIP opens; required text is present; every table has explicit geometry.

- [ ] **Step 5: Commit builder and repository DOCX**

```powershell
git add reports/build_hardened_confirmatory_report.py reports/HiddenBench确认性完善实验报告_2026-08-04.docx tests/test_build_hardened_confirmatory_report.py
git commit -m "docs: add hardened HiddenBench report"
```

### Task 6: Render, inspect, and finalize the Word document

**Files:**
- Generate ignored QA PDF/PNGs under `.tmp/hardened-report-render/`
- Update only if defects are found: `reports/build_hardened_confirmatory_report.py`
- Regenerate: repository and Desktop DOCX copies

**Interfaces:**
- Consumes the Task 5 DOCX.
- Produces verified page images and byte-identical repository/Desktop deliverables.

- [ ] **Step 1: Attempt canonical DOCX rendering**

Run the bundled `render_docx.py`. If LibreOffice is unavailable, automate installed Microsoft Word through COM to export a PDF, then render each PDF page to PNG with bundled PyMuPDF.

- [ ] **Step 2: Inspect every page image**

Check every page at full resolution for clipping, overlap, broken Chinese glyphs, table wrapping, stranded headings, large blank gaps, and header/footer placement.

- [ ] **Step 3: Fix and rerender**

Make only source-builder changes, regenerate both DOCX copies, and repeat until all inspected pages are clean.

- [ ] **Step 4: Verify identical deliverables**

Compute SHA-256 for repository and Desktop copies and assert equality. Check OOXML package integrity, section count, paragraph count, table geometry, and absence of comments/tracked-change residue.

- [ ] **Step 5: Commit any render-driven fixes**

```powershell
git add reports/build_hardened_confirmatory_report.py reports/HiddenBench确认性完善实验报告_2026-08-04.docx
git commit -m "docs: polish hardened report layout"
```

### Task 7: Final verification, evidence packaging, and branch publication

**Files:**
- Create: `reports/package_hardened_supplement_release.py`
- Create tracked: `release/hiddenbench-official-reveal-supplement-20260804-raw.sha256`
- Modify: `.gitignore` only if a new ZIP ignore rule is required
- Test: `tests/test_package_hardened_supplement_release.py`

**Interfaces:**
- Produces ignored `release/hiddenbench-official-reveal-supplement-20260804-raw.zip` containing raw supplement runs, gate, trace, compact summaries, provenance, source hashes, and no secrets.

- [ ] **Step 1: Write and run failing packaging tests**

Assert deterministic member ordering, CRC validity, required members, manifest hashes, and secret-pattern rejection.

- [ ] **Step 2: Implement and run the package builder**

Run: `python reports/package_hardened_supplement_release.py`

Expected: ZIP CRC passes and the generated SHA-256 file matches the ZIP.

- [ ] **Step 3: Run final verification**

Run:

```powershell
python -m pytest -q
git diff --check
git status --short --branch
```

Also recompute both confirmatory and supplement gates, compare frozen artifact hashes with the pre-work manifest, scan tracked files and the ZIP for credentials, and verify the Desktop/repository DOCX SHA-256 match.

- [ ] **Step 4: Commit packaging code and hash**

```powershell
git add reports/package_hardened_supplement_release.py tests/test_package_hardened_supplement_release.py release/hiddenbench-official-reveal-supplement-20260804-raw.sha256 .gitignore
git commit -m "build: package hardened supplement evidence"
```

- [ ] **Step 5: Push the feature branch and update PR #5**

Run: `git push origin codex/budget-matched-dynamic`

Upload the new ZIP and SHA-256 as release assets only after their local hashes pass. Leave PR #5 open and mergeable for review; do not merge without a separate user instruction.

