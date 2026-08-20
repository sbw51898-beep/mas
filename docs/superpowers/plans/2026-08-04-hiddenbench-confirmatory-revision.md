# HiddenBench Confirmatory Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a cleanly versioned HiddenBench confirmatory study on official tasks ID1/ID2/ID3, with atomic-fact disclosure measurement, same-trajectory shadow voting for early-stop evaluation, official GPT-4.1 per-task comparisons, and a corrected new Word report.

**Architecture:** Add a confirmatory layer beside the existing exploratory studies instead of mutating historical artifacts. Reuse the existing HiddenBench task, provider, voting, fixed-round, dynamic-selector, scoring, and report-style utilities; isolate new provenance, atomic-audit, shadow-vote, official-result, study-orchestration, gate, and report responsibilities into focused modules. Freeze and commit all runtime code before any formal API call, then commit only derived summaries, gates, manifests, and the new report while publishing large raw artifacts as a release asset.

**Tech Stack:** Python 3.13, Pydantic 2, Typer, pytest, Microsoft Agent Framework adapters, DeepSeek OpenAI-compatible API, python-docx, Git, GitHub CLI.

## Global Constraints

- Preserve every existing report and artifact; create only new confirmatory files.
- Formal tasks are exactly HiddenBench ID1, ID2, and ID3 from the official `benchmark_short.json` snapshot.
- Local formal model is exactly `deepseek-v4-flash`, `temperature=0`, `thinking=disabled`.
- Run exactly 7 conditions × 3 tasks × 10 repetitions = 210 confirmatory runs.
- Do not claim that a seed controls DeepSeek generation; it only pairs assignments.
- Do not call packet-level disclosure an atomic-fact disclosure rate.
- Do not call independent-model review human ground truth.
- Do not make any formal API call unless the repository is clean and `frozen_code_commit` equals `HEAD`.
- Do not claim early stopping is generally safe; report same-trajectory disagreement evidence and sample scope.
- Do not overwrite existing DOCX files; output `reports/HiddenBench确认性修订实验报告_2026-08-04.docx` and copy the same bytes to the Desktop.

---

### Task 1: Formal-run Git provenance gate

**Files:**
- Modify: `src/mas_experiment/audit.py`
- Create: `tests/test_formal_git_gate.py`
- Modify: `src/mas_experiment/cli.py`

**Interfaces:**
- Consumes: a repository path and optional expected commit.
- Produces: `GitWorktreeState`, `inspect_git_worktree(path)`, and `require_clean_git_commit(path, expected_commit)`.

- [ ] **Step 1: Write failing tests for clean, dirty, and mismatched commits**

Create `tests/test_formal_git_gate.py` using a real temporary Git repository:

```python
from pathlib import Path
import subprocess

import pytest

from mas_experiment.audit import (
    GitWorktreeError,
    inspect_git_worktree,
    require_clean_git_commit,
)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def test_clean_repo_returns_exact_head(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    state = inspect_git_worktree(repo)
    assert state.commit == head
    assert state.dirty is False
    assert require_clean_git_commit(repo, head) == head


def test_untracked_file_blocks_formal_run(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    (repo / "new.py").write_text("print('dirty')\n", encoding="utf-8")
    with pytest.raises(GitWorktreeError, match="dirty"):
        require_clean_git_commit(repo, head)


def test_expected_commit_mismatch_blocks_formal_run(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    with pytest.raises(GitWorktreeError, match="frozen_code_commit"):
        require_clean_git_commit(repo, "0" * 40)
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_formal_git_gate.py -q
```

Expected: collection/import failure because the three new symbols do not exist.

- [ ] **Step 3: Implement the minimal provenance API**

Add to `audit.py`:

```python
class GitWorktreeError(RuntimeError):
    pass


class GitWorktreeState(BaseModel):
    model_config = ConfigDict(frozen=True)
    commit: str
    branch: str
    dirty: bool
    porcelain: tuple[str, ...]


def inspect_git_worktree(path: Path) -> GitWorktreeState:
    commit = _git(path, "rev-parse", "HEAD")
    branch = _git(path, "branch", "--show-current")
    porcelain = tuple(
        line for line in _git(path, "status", "--porcelain=v1").splitlines()
        if line.strip()
    )
    return GitWorktreeState(
        commit=commit,
        branch=branch,
        dirty=bool(porcelain),
        porcelain=porcelain,
    )


def require_clean_git_commit(path: Path, expected_commit: str) -> str:
    state = inspect_git_worktree(path)
    if not state.branch:
        raise GitWorktreeError("formal run requires a named branch")
    if state.dirty:
        raise GitWorktreeError("formal run requires a clean worktree")
    if state.commit != expected_commit:
        raise GitWorktreeError("frozen_code_commit does not equal HEAD")
    return state.commit
```

Use the same subprocess error-handling style as existing `current_git_commit()`. Add a CLI preflight helper but do not yet connect a formal command.

- [ ] **Step 4: Verify GREEN and regression safety**

Run:

```powershell
python -m pytest tests/test_formal_git_gate.py tests/test_audit.py tests/test_cli.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Remove the interrupted untracked model-switch helper**

Verify that `scripts/deepseek-env.ps1` is the helper created during the interrupted GPT/DeepSeek setup and contains no experiment logic. Remove that single untracked file with `apply_patch`, then remove the empty `scripts` directory if it is empty. Do not run a broad `git clean` command.

- [ ] **Step 6: Commit the provenance gate**

```powershell
git add src/mas_experiment/audit.py src/mas_experiment/cli.py tests/test_formal_git_gate.py
git commit -m "feat: block formal runs from dirty worktrees"
```

---

### Task 2: Confirmatory configuration and official task lock

**Files:**
- Create: `src/mas_experiment/hiddenbench_confirmatory_domain.py`
- Create: `configs/hiddenbench-confirmatory-20260804.json`
- Create: `tests/test_hiddenbench_confirmatory_domain.py`
- Modify: `src/mas_experiment/cli.py`

**Interfaces:**
- Consumes: official task list and confirmatory JSON config.
- Produces: `ConfirmatoryStudyConfig`, `ConfirmatoryStudyKey`, `ConfirmatoryCondition`, `load_confirmatory_config()`, and `validate_confirmatory_tasks()`.

- [ ] **Step 1: Write failing domain tests**

```python
from pathlib import Path
import pytest

from mas_experiment.hiddenbench_confirmatory_domain import (
    ConfirmatoryStudyConfig,
    validate_confirmatory_tasks,
)
from mas_experiment.hiddenbench_data import load_hiddenbench_tasks


def test_config_requires_exact_matrix() -> None:
    config = ConfirmatoryStudyConfig.model_validate({
        "configuration_version": "hiddenbench-confirmatory-v1",
        "task_ids": [1, 2, 3],
        "conditions": [
            "fixed-60", "dynamic-60", "fixed-reveal-all",
            "dynamic-reveal-all", "structured-12", "fixed-12",
            "single-local",
        ],
        "repetitions": 10,
        "base_seed": 20260804,
        "dataset_sha256": "a" * 64,
        "frozen_code_commit": "b" * 40,
        "provider": {
            "model": "deepseek-v4-flash", "temperature": 0,
            "thinking": "disabled",
        },
    })
    assert config.expected_run_count == 210


def test_official_short_tasks_are_exactly_ids_1_2_3() -> None:
    tasks = load_hiddenbench_tasks(Path("data/hiddenbench/benchmark.json"))
    selected = validate_confirmatory_tasks(tasks)
    assert [task.id for task in selected] == [1, 2, 3]
    assert [task.name for task in selected] == [
        "evacuation_west_city",
        "evacuation_north_hill",
        "evacuation_east_town",
    ]


def test_wrong_task_set_is_rejected() -> None:
    payload = {
        "configuration_version": "hiddenbench-confirmatory-v1",
        "task_ids": [1, 5, 7],
        "conditions": [
            "fixed-60", "dynamic-60", "fixed-reveal-all",
            "dynamic-reveal-all", "structured-12", "fixed-12",
            "single-local",
        ],
        "repetitions": 10,
        "base_seed": 20260804,
        "dataset_sha256": "a" * 64,
        "frozen_code_commit": "b" * 40,
        "provider": {
            "model": "deepseek-v4-flash", "temperature": 0,
            "thinking": "disabled",
        },
    }
    with pytest.raises(ValueError, match="1, 2, 3"):
        ConfirmatoryStudyConfig.model_validate(payload)
```

Fill the rejection payload completely; do not use an ellipsis in the actual test.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/test_hiddenbench_confirmatory_domain.py -q
```

Expected: import failure because the module is absent.

- [ ] **Step 3: Implement frozen config and task validation**

Use Pydantic frozen models and exact `Literal` values. `expected_run_count` returns `len(task_ids) * len(conditions) * repetitions`. Validate model, temperature, thinking, task IDs, repetition count, and condition order.

The config file must include the real official dataset hash. When Task 2 creates it, set `frozen_code_commit` to the exact output of `git rev-parse HEAD` after Task 1. Task 7 replaces that value with the final runtime-code commit after all implementation tasks, then creates one configuration-only freeze commit.

- [ ] **Step 4: Add a read-only CLI preflight command**

Add:

```powershell
mas-experiment confirmatory-preflight --config configs/hiddenbench-confirmatory-20260804.json
```

It loads the config, validates official tasks, prints 210 expected runs, prints the current commit/dirty status, and makes zero API calls.

- [ ] **Step 5: Verify GREEN**

```powershell
python -m pytest tests/test_hiddenbench_confirmatory_domain.py tests/test_cli.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add configs/hiddenbench-confirmatory-20260804.json src/mas_experiment/hiddenbench_confirmatory_domain.py src/mas_experiment/cli.py tests/test_hiddenbench_confirmatory_domain.py
git commit -m "feat: lock confirmatory study to official short tasks"
```

---

### Task 3: Atomic facts and mechanical Reveal-All

**Files:**
- Create: `src/mas_experiment/hiddenbench_atomic_disclosure.py`
- Create: `tests/test_hiddenbench_atomic_disclosure.py`
- Modify: `src/mas_experiment/hiddenbench_protocol.py`
- Modify: `src/mas_experiment/hiddenbench_dynamic_protocol.py`

**Interfaces:**
- Consumes: `HiddenBenchAssignment`, public `HiddenBenchMessage` records, and a prompt provider.
- Produces: `AtomicPrivateFact`, `AtomicDisclosureJudgment`, `AtomicDisclosureAudit`, `decompose_private_facts()`, `append_reveal_all_block()`, `audit_atomic_disclosure()`, and `validate_atomic_evidence()`.

- [ ] **Step 1: Write failing decomposition and Reveal-All tests**

```python
def test_each_short_benchmark_private_item_is_one_atomic_fact() -> None:
    assignment = make_short_assignment(task_id=1, seed=11)
    facts = decompose_private_facts(assignment)
    assert len(facts) == 4
    assert {fact.owner_agent_id for fact in facts} == set(AGENT_IDS)
    assert all(fact.text.strip() for fact in facts)


def test_structured_bullets_split_to_stable_atomic_ids() -> None:
    assignment = assignment_with_private_text(
        "agent-a", "Cape Industries:\n- (a) Y\n- (b) N"
    )
    facts = decompose_private_facts(assignment)
    assert [fact.text for fact in facts] == [
        "Cape Industries: (a) Y",
        "Cape Industries: (b) N",
    ]
    assert len({fact.fact_id for fact in facts}) == 2


def test_reveal_all_appends_exact_private_facts_mechanically() -> None:
    content = append_reveal_all_block("My view is West City.", facts)
    assert content.startswith("My view is West City.")
    assert "[All Private Information Revealed]" in content
    assert all(fact.text in content for fact in facts)
```

Add a contrast test proving that the model completion may omit a fact but the stored public message still contains the mechanically appended fact.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_hiddenbench_atomic_disclosure.py -q
```

- [ ] **Step 3: Implement atomic decomposition and IDs**

Generate `fact_id` as SHA-256 over canonical JSON containing task/assignment owner, source packet index, atomic index, and normalized text. Preserve the original wording; normalization is only for stable hashing.

- [ ] **Step 4: Implement mechanical Reveal-All**

For fixed conditions, append all of the current speaker's atomic private facts to that speaker's round-1 message. For dynamic conditions, append them to the first public message produced by each speaker. Do not rely on a prompt request to disclose. Mark provider metadata with `mechanical_reveal_all: true` and the appended fact IDs.

- [ ] **Step 5: Write failing audit/evidence tests**

Test that:

- a faithful owner quote is accepted;
- a non-owner quote is rejected;
- an evidence message ID that does not exist is rejected;
- an evidence quote that is not a continuous substring is rejected;
- a polarity reversal is rejected by the scripted judgment fixture;
- mechanical Reveal-All produces 100% atomic disclosure without an extra judge call.

- [ ] **Step 6: Implement the audit and deterministic evidence validator**

Use the existing disclosure judge provider pattern but make the judge return one judgment per atomic fact. Compute a run rate deterministically as `sum(disclosed) / len(facts)`.

- [ ] **Step 7: Verify GREEN and existing protocol regression tests**

```powershell
python -m pytest tests/test_hiddenbench_atomic_disclosure.py tests/test_hiddenbench_protocol.py tests/test_hiddenbench_dynamic_protocol.py tests/test_hiddenbench_ai_disclosure.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add src/mas_experiment/hiddenbench_atomic_disclosure.py src/mas_experiment/hiddenbench_protocol.py src/mas_experiment/hiddenbench_dynamic_protocol.py tests/test_hiddenbench_atomic_disclosure.py
git commit -m "feat: measure atomic disclosure and mechanically reveal facts"
```

---

### Task 4: Same-trajectory shadow voting and hypothetical stop rule

**Files:**
- Create: `src/mas_experiment/hiddenbench_shadow_voting.py`
- Create: `tests/test_hiddenbench_shadow_voting.py`
- Modify: `src/mas_experiment/hiddenbench_protocol.py`

**Interfaces:**
- Consumes: public history after each complete round and a prompt provider.
- Produces: `ShadowVoteCheckpoint`, `EarlyStopEvaluation`, `collect_shadow_votes()`, `find_candidate_stop()`, and fixed-60 runs with 15 checkpoints.

- [ ] **Step 1: Write failing stop-rule tests**

```python
def test_stop_requires_two_consecutive_identical_unanimous_rounds() -> None:
    checkpoints = [
        checkpoint(1, ["A", "A", "A", "A"]),
        checkpoint(2, ["B", "B", "B", "B"]),
        checkpoint(3, ["B", "B", "B", "B"]),
    ]
    stop = find_candidate_stop(checkpoints)
    assert stop.round_index == 3
    assert stop.answer == "B"


def test_split_vote_resets_consecutive_consensus() -> None:
    checkpoints = [
        checkpoint(1, ["A", "A", "A", "A"]),
        checkpoint(2, ["A", "A", "A", "B"]),
        checkpoint(3, ["A", "A", "A", "A"]),
    ]
    assert find_candidate_stop(checkpoints) is None


def test_no_consensus_returns_none() -> None:
    assert find_candidate_stop([
        checkpoint(1, ["A", "B", "A", "B"]),
        checkpoint(2, ["A", "A", "B", "B"]),
    ]) is None
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_hiddenbench_shadow_voting.py -q
```

- [ ] **Step 3: Implement the pure stop-rule functions**

`find_candidate_stop()` compares only adjacent complete checkpoints. `EarlyStopEvaluation` stores candidate round, candidate answer, final votes, exact-match boolean, candidate correctness, final correctness, and saved public messages.

- [ ] **Step 4: Write failing protocol-isolation test**

Use a scripted provider to run two rounds and assert:

```python
assert len(record.shadow_checkpoints) == 2
assert all(len(item.votes) == 4 for item in record.shadow_checkpoints)
assert "shadow" not in record.run.discussion_messages[4].user_prompt.lower()
assert not any(
    vote.rationale in message.user_prompt
    for checkpoint in record.shadow_checkpoints
    for vote in checkpoint.votes
    for message in record.run.discussion_messages
)
```

- [ ] **Step 5: Add invisible round-end shadow votes to fixed-60**

After each block of four public messages, call the existing vote completion logic with the current public history. Store votes separately. Never append them to `discussion_messages` or `visible_message_ids`.

- [ ] **Step 6: Verify GREEN**

```powershell
python -m pytest tests/test_hiddenbench_shadow_voting.py tests/test_hiddenbench_protocol.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/hiddenbench_shadow_voting.py src/mas_experiment/hiddenbench_protocol.py tests/test_hiddenbench_shadow_voting.py
git commit -m "feat: add invisible round-level shadow votes"
```

---

### Task 5: Confirmatory orchestration, resumability, and integrity gate

**Files:**
- Create: `src/mas_experiment/hiddenbench_confirmatory_study.py`
- Create: `src/mas_experiment/hiddenbench_confirmatory_gate.py`
- Create: `tests/test_hiddenbench_confirmatory_study.py`
- Create: `tests/test_hiddenbench_confirmatory_gate.py`
- Modify: `src/mas_experiment/cli.py`

**Interfaces:**
- Consumes: confirmed config, provider, official tasks, condition key.
- Produces: append-only run JSONL, atomic-audit JSONL, trace JSONL, summary CSV/JSON, gate JSON, and manifest JSON.

- [ ] **Step 1: Write failing paired-matrix study tests**

Test an offline 7 × 3 × 2 reduced fixture and assert:

```python
assert len(records) == 42
assert len({record.key.value for record in records}) == 42
for task_id in (1, 2, 3):
    for repetition in (0, 1):
        group = [r for r in records if r.key.task_id == task_id and r.key.repetition == repetition]
        assert len({r.pair_seed for r in group}) == 1
        assert len({r.assignment_fingerprint for r in group}) == 1
```

Also assert single-local has one post vote, fixed-60 has 60 public messages plus 15 shadow checkpoints, structured/fixed-12 have 12 messages, and dynamic conditions have zero selector LLM calls.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_hiddenbench_confirmatory_study.py -q
```

- [ ] **Step 3: Implement condition dispatch and resumable writer**

Follow existing study writers: deterministic key order, skip only keys already present and valid, append one complete JSON object per line, flush after each run, never rewrite completed rows.

- [ ] **Step 4: Write failing integrity-gate tests**

Create fixtures for:

- missing run key;
- duplicate run key;
- mismatched assignment fingerprint;
- missing shadow checkpoint;
- Reveal-All rate below 1.0;
- invalid evidence quote;
- wrong provider model;
- code commit mismatch;
- non-deterministic row order.

Each fixture must fail one named gate check. A complete fixture must produce `passed: true`.

- [ ] **Step 5: Implement the gate**

Gate output includes every check as a named boolean and refuses to report `passed: true` unless all checks are true. It also recomputes API requests directly from run and audit provider metadata.

- [ ] **Step 6: Add CLI commands**

```powershell
mas-experiment run-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --output artifacts/hiddenbench-confirmatory-20260804.jsonl
mas-experiment resume-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --output artifacts/hiddenbench-confirmatory-20260804.jsonl
mas-experiment gate-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --input artifacts/hiddenbench-confirmatory-20260804.jsonl
```

The run/resume commands call `require_clean_git_commit()` before constructing a provider or making a connectivity request.

- [ ] **Step 7: Verify GREEN and full tests**

```powershell
python -m pytest tests/test_hiddenbench_confirmatory_study.py tests/test_hiddenbench_confirmatory_gate.py tests/test_cli.py -q
python -m pytest -q
```

- [ ] **Step 8: Commit**

```powershell
git add src/mas_experiment/hiddenbench_confirmatory_study.py src/mas_experiment/hiddenbench_confirmatory_gate.py src/mas_experiment/cli.py tests/test_hiddenbench_confirmatory_study.py tests/test_hiddenbench_confirmatory_gate.py
git commit -m "feat: orchestrate and validate confirmatory study"
```

---

### Task 6: Official GPT-4.1 per-task result importer

**Files:**
- Create: `src/mas_experiment/hiddenbench_official_results.py`
- Create: `tests/fixtures/official_hidden_short_minimal.json`
- Create: `tests/test_hiddenbench_official_results.py`
- Create: `reports/fetch_hiddenbench_official_short_results.py`

**Interfaces:**
- Consumes: official legacy `conditions -> runs` JSON and official task definitions.
- Produces: verified source records and per-task average, majority, unanimous, and false-consensus metrics.

- [ ] **Step 1: Write failing importer tests**

The fixture contains one condition, three scenarios, and deterministic final votes. Test:

```python
def test_scores_legacy_official_results_per_task() -> None:
    result = score_official_short_results(FIXTURE, TASKS)
    west = result.by_task[1]
    assert west.runs == 2
    assert west.average_accuracy == 0.75
    assert west.majority_correct_runs == 1
    assert west.unanimous_correct_runs == 1


def test_source_hash_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="sha256"):
        load_verified_official_result(FIXTURE, expected_sha256="0" * 64)
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_hiddenbench_official_results.py -q
```

- [ ] **Step 3: Implement importer and scorer**

Map official scenario names to ID1/ID2/ID3 using the official task data, not positional guessing. Compute all metrics from `final_votes`; never read summary percentages as trusted outputs.

- [ ] **Step 4: Implement the fetch script**

Fetch and hash:

- `results_hidden_short_hidden_short.json`
- `results_hidden_short_reveal_all_hidden_hidden_short_reveal_all_hidden.json`
- `results/MANIFEST.json`

Write a small tracked JSON summary to `reports/data/hiddenbench-official-gpt41-short-summary.json`. Record missing Structured per-task data explicitly if the manifest has no matching entry.

- [ ] **Step 5: Verify GREEN**

```powershell
python -m pytest tests/test_hiddenbench_official_results.py -q
python reports/fetch_hiddenbench_official_short_results.py --offline-fixture tests/fixtures/official_hidden_short_minimal.json
```

- [ ] **Step 6: Commit**

```powershell
git add src/mas_experiment/hiddenbench_official_results.py tests/fixtures/official_hidden_short_minimal.json tests/test_hiddenbench_official_results.py reports/fetch_hiddenbench_official_short_results.py
git commit -m "feat: verify official GPT-4.1 short-task results"
```

---

### Task 7: Freeze runtime commit before formal API calls

**Files:**
- Modify: `configs/hiddenbench-confirmatory-20260804.json`

**Interfaces:**
- Consumes: clean tested HEAD.
- Produces: a committed config whose `frozen_code_commit` equals the commit used for real model runs.

- [ ] **Step 1: Run the complete pre-freeze verification suite**

```powershell
python -m pytest -q
git diff --check
git status --porcelain=v1
```

Expected: tests pass; only the intentional config edit may remain after the next step.

- [ ] **Step 2: Set `frozen_code_commit` to current HEAD**

Read `git rev-parse HEAD` and replace the config value using `apply_patch`.

- [ ] **Step 3: Commit the frozen config**

Avoid self-reference by defining `frozen_code_commit` as the parent runtime-code commit. The formal gate verifies:

- `frozen_code_commit == HEAD^`;
- `git diff --quiet frozen_code_commit..HEAD -- src tests`.

Commit:

```powershell
git add configs/hiddenbench-confirmatory-20260804.json
git commit -m "chore: freeze confirmatory runtime configuration"
```

The run manifest records both `run_commit=HEAD` and `frozen_code_commit=HEAD^`. Update Task 2/Task 5 tests to enforce this exact rule before proceeding.

- [ ] **Step 4: Verify formal preflight from a clean tree**

```powershell
git status --porcelain=v1
mas-experiment confirmatory-preflight --config configs/hiddenbench-confirmatory-20260804.json
```

Expected: clean tree, named branch, runtime code diff check passes, exactly 210 expected runs, zero API calls.

---

### Task 8: Run the formal DeepSeek study and atomic audit

**Files generated locally:**
- `artifacts/hiddenbench-confirmatory-20260804.jsonl`
- `artifacts/hiddenbench-confirmatory-20260804.atomic-disclosure.jsonl`
- `artifacts/hiddenbench-confirmatory-20260804.trace.jsonl`
- `artifacts/hiddenbench-confirmatory-20260804.summary.csv`
- `artifacts/hiddenbench-confirmatory-20260804.summary.json`
- `artifacts/hiddenbench-confirmatory-20260804.gate.json`
- `artifacts/hiddenbench-confirmatory-20260804.manifest.json`

**Interfaces:**
- Consumes: frozen config, clean code, DeepSeek environment.
- Produces: 210 complete formal runs plus audits and integrity evidence.

- [ ] **Step 1: Load DeepSeek credentials only into the current PowerShell process**

Clear dead localhost proxy variables for the process, set DeepSeek endpoint/model, and read the API key from the user's existing secure environment. Do not echo the key and do not write it into the repository.

- [ ] **Step 2: Connectivity preflight**

Run the project's provider connectivity command once. Confirm provider model, temperature, and thinking mode from returned metadata.

- [ ] **Step 3: Execute the 210-run matrix at high concurrency**

```powershell
mas-experiment run-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --output artifacts/hiddenbench-confirmatory-20260804.jsonl
```

Use 8 experiment workers and 16 audit workers unless the service returns rate limits. On transient failure, use only the resumable command; never restart from scratch.

- [ ] **Step 4: Resume until complete**

```powershell
mas-experiment resume-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --output artifacts/hiddenbench-confirmatory-20260804.jsonl
```

Repeat only while the command reports incomplete keys. Preserve all logs.

- [ ] **Step 5: Run the integrity gate**

```powershell
mas-experiment gate-hiddenbench-confirmatory --config configs/hiddenbench-confirmatory-20260804.json --input artifacts/hiddenbench-confirmatory-20260804.jsonl
```

Expected: 210 unique runs, all audit keys present, Reveal-All atomic disclosure 100%, fixed-60 has 15 shadow checkpoints per run, provider/code/data checks pass.

- [ ] **Step 6: Independently recompute headline totals**

Run a separate read-only analysis script that does not import the report builder. Reconcile its totals with the summary JSON and gate. Stop if any number differs.

---

### Task 9: Fetch real official results and create comparison summary

**Files generated:**
- `reports/data/hiddenbench-official-gpt41-short-summary.json`
- `reports/data/hiddenbench-confirmatory-summary.json`
- `reports/data/hiddenbench-confirmatory-earlystop-cases.csv`
- `reports/data/hiddenbench-confirmatory-atomic-disclosure.csv`

- [ ] **Step 1: Fetch official files from author sources**

```powershell
python reports/fetch_hiddenbench_official_short_results.py --output reports/data/hiddenbench-official-gpt41-short-summary.json
```

Verify URLs and SHA-256 against the downloaded bytes.

- [ ] **Step 2: Build tracked, compact confirmatory summaries**

Create `reports/build_confirmatory_summaries.py` with tests in `tests/test_confirmatory_summaries.py`. It reads raw artifacts and writes only compact, non-sensitive, deterministic JSON/CSV outputs.

- [ ] **Step 3: Verify the corrected historical appendix values**

Assert in tests:

```python
assert historical.total_conditions == 10
assert historical.total_runs == 400
assert historical.multi_agent_correct_range == (14, 24)
assert historical.earlystop_by_task["fixed-4"] == {1: 10, 5: 0, 7: 1, 25: 9}
assert historical.earlystop_by_task["fixed-8"] == {1: 10, 5: 0, 7: 2, 25: 8}
assert historical.earlystop_by_task["fixed"] == {1: 10, 5: 0, 7: 2, 25: 8}
```

- [ ] **Step 4: Commit compact evidence**

```powershell
git add reports/data reports/build_confirmatory_summaries.py tests/test_confirmatory_summaries.py
git commit -m "data: add verified confirmatory study summaries"
```

Do not commit the large raw JSONL files in this step.

---

### Task 10: Generate the corrected new Word report

**Files:**
- Create: `reports/build_confirmatory_report.py`
- Create: `tests/test_build_confirmatory_report.py`
- Generate: `reports/HiddenBench确认性修订实验报告_2026-08-04.docx`
- Copy: `C:\Users\liuli\Desktop\HiddenBench确认性修订实验报告_2026-08-04.docx`

**Interfaces:**
- Consumes: compact confirmatory and official comparison summaries, prompt constants, manifest, gate, and fixed URLs.
- Produces: one new report with deterministic tables and no historical-report overwrite.

- [ ] **Step 1: Write failing content and calculation tests**

Test that the report input model rejects:

- task IDs other than 1/2/3 in the confirmatory section;
- run count other than 210;
- missing prompt text;
- missing commit/release/hash fields;
- a sentence claiming general early-stop safety;
- a sentence calling ID1/5/7 the paper's three manual tasks.

Test generated text includes:

```python
assert "ID1、ID2、ID3" in text
assert "7 条件 × 3 题 × 10 次 = 210 次" in text
assert "原子事实披露率" in text
assert "本样本未观察到" in text or "观察到提前停止翻转" in text
assert "局部信息单智能体" in text
assert "完整信息单智能体" in text
assert "作者自定义 Python 模拟器" in text
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_build_confirmatory_report.py -q
```

- [ ] **Step 3: Build the new report**

Reuse the existing Word style helpers, but create a new report from compact summaries. Required sections follow the approved design. Include the complete generation, Reveal-All, Structured, shadow-vote, and atomic-audit prompts in an appendix.

Use exact DXA table geometry totaling 9360. Do not use the old “8 conditions/320 runs/9400 calls”, “any 4-agent group 20–24”, “ID5/ID7 100% and all wrong”, or “early stopping is safe” wording.

- [ ] **Step 4: Verify report structure and deterministic totals**

```powershell
python -m pytest tests/test_build_confirmatory_report.py -q
python reports/build_confirmatory_report.py
```

Open the generated DOCX with `python-docx`, verify all expected headings/tables, test the ZIP package, and compare the Desktop/repository SHA-256 values.

- [ ] **Step 5: Render and inspect if available**

Use the bundled document renderer. If LibreOffice remains unavailable, record that limitation in the final handoff and perform structural/table-geometry validation without claiming visual render completion.

- [ ] **Step 6: Commit**

```powershell
git add reports/build_confirmatory_report.py tests/test_build_confirmatory_report.py reports/HiddenBench确认性修订实验报告_2026-08-04.docx
git commit -m "docs: add corrected HiddenBench confirmatory report"
```

---

### Task 11: Package raw evidence, final verification, push, and release

**Files:**
- Generate: `release/hiddenbench-confirmatory-20260804-raw.zip`
- Generate: `release/hiddenbench-confirmatory-20260804-raw.sha256`
- Modify: `reports/data/hiddenbench-confirmatory-summary.json` only to insert the final public release URL after upload.

- [ ] **Step 1: Package only the named formal artifacts**

Resolve each absolute path, verify it is inside the worktree `artifacts` directory, then create the ZIP. Include raw run JSONL, atomic audit JSONL, trace JSONL, gate, manifest, summaries, and run logs. Do not include `.env`, API keys, proxy settings, or the local DeepSeek backup file.

- [ ] **Step 2: Secret scan**

Run repository and ZIP-content scans for API-key patterns, authorization headers, and environment assignments. The scan must pass before push/upload.

- [ ] **Step 3: Fresh full verification**

```powershell
python -m pytest -q
git diff --check
git status --short
```

Re-run the confirmatory gate and independently recompute 210-run totals. Verify all DOCX/JSON/CSV/ZIP hashes.

- [ ] **Step 4: Push the branch**

```powershell
git push origin codex/budget-matched-dynamic
```

- [ ] **Step 5: Create or update the pull request**

Use `gh pr view` first. If a PR exists, update its description with the confirmatory scope; otherwise create a ready-for-review PR targeting `master`.

- [ ] **Step 6: Create a GitHub Release and upload raw evidence**

Create tag `hiddenbench-confirmatory-20260804`, attach the ZIP and SHA-256 file, and record the public asset URL in the tracked summary/report. If GitHub rejects the asset, report the exact blocker and do not claim public reproducibility is complete.

- [ ] **Step 7: Commit only the final URL update and push**

Regenerate the report so the fixed release URL appears in it, rerun report tests/structural checks, commit the URL-only update, and push again.

- [ ] **Step 8: Final requirements audit**

Check every approved design section against concrete evidence:

- ID1/2/3 exact mapping;
- seven conditions and 210 runs;
- atomic disclosure and Reveal-All 100% gate;
- same-trajectory shadow votes and counterexamples;
- local/full-profile/multi-agent distinction;
- official GPT-4.1 source/hash/metrics;
- clean runtime commit provenance;
- raw public release asset;
- corrected new DOCX preserved beside old reports;
- honest limitations.

Only after this checklist and fresh verification may the work be described as complete.
