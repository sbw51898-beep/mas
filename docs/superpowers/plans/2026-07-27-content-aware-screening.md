# Content-Aware Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a four-condition, three-task hidden-profile screening experiment with a content-aware five-factor speaker selector and reproducible audit artifacts.

**Architecture:** Extend `Question` with explicit keyword metadata, derive information-use metrics from real transcripts, and pass public-message state into the selector. Add a seeded matched-budget random-order orchestration, then expose all four conditions through a dedicated screening CLI that reuses one initial state per task-repeat pair.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest, Microsoft Agent Framework, DeepSeek OpenAI-compatible API.

## Global Constraints

- Keep exactly three mutually invisible initialization calls per task-repeat pair.
- Keep exactly six follow-up calls in every condition.
- Do not add adaptive termination or passive listener belief updates.
- Do not copy task text, values, or source code from `meeting-room`.
- Treat two repeats as screening evidence only.
- Never write API keys or authorization values to traces or manifests.

---

### Task 1: Information metadata and transcript measures

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Create: `src/mas_experiment/information.py`
- Modify: `src/mas_experiment/metrics.py`
- Test: `tests/test_information.py`
- Modify: `tests/test_metrics.py`

**Interfaces:**
- Produces: `Question.information_keywords`, `Question.dependency_keywords`
- Produces: `calculate_information_measures(question, messages, initial_message_count) -> InformationMeasures`
- Produces: `ExperimentMetrics.information_coverage`, `cross_agent_input_use_rate`, and `ignored_input_candidate_rate`

- [ ] **Step 1: Write failing tests for keyword coverage and cross-agent use**

```python
def test_information_measures_distinguish_exposure_use_and_ignored_input():
    measures = calculate_information_measures(
        question,
        messages,
        initial_message_count=3,
    )
    assert measures.information_coverage == pytest.approx(0.75)
    assert measures.cross_agent_input_use_rate == pytest.approx(0.5)
    assert measures.ignored_input_candidate_rate == pytest.approx(0.5)
```

- [ ] **Step 2: Run the focused test and confirm it fails because the module and fields do not exist**

Run: `python -m pytest tests/test_information.py -q`

Expected: FAIL during import of `mas_experiment.information`.

- [ ] **Step 3: Implement immutable question metadata and transcript measures**

Implement case-insensitive literal keyword matching. Coverage uses all messages; cross-agent use and ignored-input candidates use follow-up messages and each message's `visible_history_ids`.

- [ ] **Step 4: Connect the measures to `calculate_metrics` and orchestration result construction**

Change `calculate_metrics` to accept `messages` and `initial_message_count`, then persist all three values in `ExperimentMetrics`.

- [ ] **Step 5: Run information and metric tests**

Run: `python -m pytest tests/test_information.py tests/test_metrics.py -q`

Expected: PASS.

### Task 2: Content-aware five-factor selector

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Modify: `src/mas_experiment/selectors.py`
- Modify: `src/mas_experiment/orchestrations.py`
- Modify: `tests/test_selectors.py`
- Modify: `tests/test_orchestrations.py`

**Interfaces:**
- Extends: `score_candidates(..., question: Question | None = None, public_messages: tuple[Message, ...] = ())`
- Extends: `SelectionScore` with `information_exposure` and `dependency_trigger`

- [ ] **Step 1: Write a failing test where an agent with unexposed relevant information outranks the longest-waiting agent**

```python
scores = score_candidates(
    agent_ids=("a", "b"),
    latest_responses=responses,
    last_spoken_steps={"a": 3, "b": 1},
    current_step=4,
    question=question,
    public_messages=messages,
)
assert scores[0].agent_id == "a"
assert scores[0].information_exposure == 1.0
assert scores[0].dependency_trigger == 1.0
```

- [ ] **Step 2: Run the selector test and confirm the new contract fails**

Run: `python -m pytest tests/test_selectors.py -q`

Expected: FAIL because the new arguments and score fields are absent.

- [ ] **Step 3: Implement the five factors with weights 0.30, 0.25, 0.20, 0.15, and 0.10**

Use only the declared keyword metadata and messages already visible in the public transcript. Keep scores in `[0, 1]`.

- [ ] **Step 4: Pass question and public messages from `run_dynamic`**

The dynamic selector must receive the current full public transcript on every selection step.

- [ ] **Step 5: Run selector and orchestration tests**

Run: `python -m pytest tests/test_selectors.py tests/test_orchestrations.py -q`

Expected: PASS.

### Task 3: Matched-budget random-order baseline

**Files:**
- Modify: `src/mas_experiment/orchestrations.py`
- Modify: `src/mas_experiment/cli.py`
- Modify: `tests/test_orchestrations.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `run_random_order(question, roles, provider, *, seed, initial_state=None) -> ExperimentResult`

- [ ] **Step 1: Write a failing orchestration test**

```python
result = await run_random_order(
    question,
    roles,
    provider,
    seed=17,
    initial_state=state,
)
follow_up = result.messages[3:]
assert Counter(message.speaker for message in follow_up) == {
    "agent-a": 2,
    "agent-b": 2,
    "agent-c": 2,
}
assert [m.speaker for m in follow_up] == [
    "agent-a", "agent-c", "agent-b", "agent-c", "agent-b", "agent-a"
]
```

- [ ] **Step 2: Run the focused test and confirm the missing runner failure**

Run: `python -m pytest tests/test_orchestrations.py -q`

Expected: FAIL importing `run_random_order`.

- [ ] **Step 3: Implement seeded shuffling of two slots per agent**

Use a local `random.Random(seed)` instance. Every follow-up sees the complete public transcript and produces the same six-call budget as round-robin and dynamic.

- [ ] **Step 4: Expose `random_order` in the general CLI**

`--mode all` must emit four records, and `--mode random_order` must run only the new baseline.

- [ ] **Step 5: Run orchestration and CLI tests**

Run: `python -m pytest tests/test_orchestrations.py tests/test_cli.py -q`

Expected: PASS.

### Task 4: Three independent hidden-profile screening tasks

**Files:**
- Modify: `src/mas_experiment/datasets.py`
- Modify: `tests/test_datasets.py`

**Interfaces:**
- Produces: `SCREENING_ROLES: tuple[AgentRole, ...]`
- Produces: `SCREENING_QUESTIONS: tuple[Question, ...]`
- Produces: `SCREENING_DIFFICULTIES: dict[str, str]`

- [ ] **Step 1: Write failing tests for task count, computed ground truth, and metadata completeness**

```python
assert len(SCREENING_QUESTIONS) == 3
assert set(SCREENING_DIFFICULTIES.values()) == {"easy", "medium", "hard"}
for question in SCREENING_QUESTIONS:
    assert set(question.private_contexts) == set(role_ids)
    assert set(question.information_keywords) == set(role_ids)
    assert set(question.dependency_keywords) == set(role_ids)
    assert weighted_winner(question.question_id) == question.correct_answer
```

- [ ] **Step 2: Run dataset tests and confirm the new exports are missing**

Run: `python -m pytest tests/test_datasets.py -q`

Expected: FAIL importing the screening exports.

- [ ] **Step 3: Implement easy, medium, and hard tasks with hand-checked weighted totals**

Each task must expose weights publicly, place one complete dimension in each private context, and declare literal information/dependency keywords.

- [ ] **Step 4: Run dataset tests**

Run: `python -m pytest tests/test_datasets.py -q`

Expected: PASS.

### Task 5: Screening CLI, report, configuration fingerprint, and SHA-256 manifest

**Files:**
- Create: `src/mas_experiment/audit.py`
- Modify: `src/mas_experiment/cli.py`
- Modify: `src/mas_experiment/reporting.py`
- Create: `tests/test_audit.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_reporting.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `configuration_fingerprint(question, roles, seed) -> str`
- Produces: `write_sha256_manifest(paths, destination) -> Path`
- Produces CLI: `mas-experiment screening-pilot`

- [ ] **Step 1: Write failing tests for deterministic fingerprints and manifest verification data**

```python
assert configuration_fingerprint(question, roles, 7) == configuration_fingerprint(
    question, roles, 7
)
manifest = json.loads(write_sha256_manifest((result, report), target).read_text())
assert {entry["path"] for entry in manifest["files"]} == {
    result.name,
    report.name,
}
```

- [ ] **Step 2: Write a failing CLI test for 24 offline records and four modes**

Run the command with three tasks and two repeats, then assert 24 records, six shared initial-state IDs, equal nine logical responses per record, and modes `independent`, `round_robin`, `random_order`, and `dynamic`.

- [ ] **Step 3: Run audit and CLI tests and confirm failures**

Run: `python -m pytest tests/test_audit.py tests/test_cli.py tests/test_reporting.py -q`

Expected: FAIL because audit functions and the screening command are absent.

- [ ] **Step 4: Implement the screening command and audit artifacts**

Use derived seed `base_seed + task_index * 100 + repeat_index`. Write the JSONL, Markdown report, and adjacent `.manifest.json`. Record difficulty and fingerprint in result metadata without exposing credentials.

- [ ] **Step 5: Document exact offline and DeepSeek commands and the 162-call budget**

Add commands for a zero-cost offline screening and the real DeepSeek screening, including `--overwrite` protection.

- [ ] **Step 6: Run the complete test suite and an offline screening smoke test**

Run:

```powershell
python -m pytest -q
mas-experiment screening-pilot --provider offline --output artifacts/screening-offline.jsonl --overwrite
```

Expected: all tests pass; the command reports 24 records, 162 discussion request equivalents, and writes JSONL, Markdown, and manifest files.

### Task 6: Real DeepSeek screening run

**Files:**
- Create at runtime: `artifacts/deepseek-screening-20260727.jsonl`
- Create at runtime: `artifacts/deepseek-screening-20260727.md`
- Create at runtime: `artifacts/deepseek-screening-20260727.manifest.json`

**Interfaces:**
- Consumes: the verified `screening-pilot` command and existing `DEEPSEEK_API_KEY` environment variable
- Produces: 24 complete, auditable screening records

- [ ] **Step 1: Confirm the API key is present without printing it**

Run a boolean environment check and stop if the key is absent.

- [ ] **Step 2: Execute the real screening**

Run:

```powershell
mas-experiment screening-pilot --provider deepseek --output artifacts/deepseek-screening-20260727.jsonl
```

- [ ] **Step 3: Verify record counts, modes, shared initial states, errors, provider metadata, report, and manifest hashes**

Expected: 24 records, four modes, six shared initial-state IDs, nine logical responses per record, no recorded errors, and valid SHA-256 values for the JSONL and Markdown files.

- [ ] **Step 4: Summarize screening results without making confirmatory claims**

Report mode-by-difficulty accuracy, Brier score, information-use measures, speaker sequences, request counts, and any FM-2.5 candidates requiring manual review.
