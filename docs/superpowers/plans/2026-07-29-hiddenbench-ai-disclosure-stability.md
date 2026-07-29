# HiddenBench AI Disclosure Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-backed DeepSeek disclosure auditing, run a paired 4-task × 2-condition × 10-repetition HiddenBench study, analyze outcome and consensus stability, and update the teacher-facing Word report.

**Architecture:** Keep the acting protocol, AI audit, deterministic rule cross-check, consensus analysis, reporting, and Word publishing as separate units. A resumable study runner produces paired fixed/dynamic records first, then audits immutable transcripts, computes task-condition summaries, gates completeness and budget equality, and writes a hash-verified artifact bundle.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, pytest/pytest-asyncio, Microsoft Agent Framework adapter, DeepSeek OpenAI-compatible API, python-docx.

## Global Constraints

- Tasks are exactly HiddenBench IDs `1`, `5`, `7`, and `25`.
- Conditions are exactly `fixed` and `dynamic`.
- Repetitions are exactly `10`, indexed `0..9`.
- Fixed and dynamic runs in one pair use the same task, derived seed, assignment, model settings, and 60-speech budget.
- Every agent speaks exactly 15 times per condition.
- The dynamic selector makes zero LLM calls.
- The AI auditor is post-hoc and cannot alter discussion or votes.
- AI disclosure requires owner-authored evidence with a valid message ID and an exact quote.
- Existing `lexical-semantic-v2` results remain visible; AI labels do not replace them.
- Equal speech count does not claim equal token use.
- Results are descriptive and cannot claim general superiority or significance.
- Formal outputs use the stable prefix `artifacts/hiddenbench-stability-20260729`.
- No API key, authorization header, or bearer token may enter an artifact.

---

### Task 1: Stability Configuration and Study Domain

**Files:**
- Create: `configs/hiddenbench-ai-disclosure-stability.json`
- Create: `src/mas_experiment/hiddenbench_stability_domain.py`
- Create: `tests/test_hiddenbench_stability_domain.py`

**Interfaces:**
- Produces: `StabilityStudyConfig`, `StudyCondition`, `StudyKey`, `StudyRunRecord`, `derive_pair_seed()`, and `load_stability_config()`.
- Consumes: `HiddenBenchRun`, `DynamicHiddenBenchRun`, and the existing frozen selector weights.

- [ ] **Step 1: Write failing configuration and seed tests**

```python
def test_stability_config_locks_matrix_and_budget() -> None:
    config = load_stability_config(ROOT / "configs/hiddenbench-ai-disclosure-stability.json")
    assert config.task_ids == (1, 5, 7, 25)
    assert config.conditions == ("fixed", "dynamic")
    assert config.repetitions == 10
    assert config.total_speeches == 60
    assert config.speeches_per_agent == 15
    assert config.selector_llm_calls == 0


def test_pair_seed_is_deterministic_and_shared_by_condition() -> None:
    assert derive_pair_seed(20260729, task_id=7, repetition=3) == derive_pair_seed(
        20260729, task_id=7, repetition=3
    )
    assert derive_pair_seed(20260729, task_id=7, repetition=3) != derive_pair_seed(
        20260729, task_id=7, repetition=4
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_domain.py -q
```

Expected: import failure because `hiddenbench_stability_domain` does not exist.

- [ ] **Step 3: Implement the immutable configuration and run keys**

Create:

```python
StudyCondition = Literal["fixed", "dynamic"]


class StabilityStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    configuration_version: Literal["hiddenbench-stability-v1"]
    task_ids: tuple[int, ...]
    conditions: tuple[StudyCondition, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str
    prompt_version: str
    total_speeches: Literal[60]
    speeches_per_agent: Literal[15]
    selector_llm_calls: Literal[0]
    experiment_workers: int = Field(ge=1, le=16)
    judge_workers: int = Field(ge=1, le=16)
    judge_prompt_version: str
    provider: DynamicProviderSettings
    selector: SelectorWeights


class StudyKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: int
    condition: StudyCondition
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return f"task-{self.task_id}:{self.condition}:rep-{self.repetition}"
```

Use SHA-256 based seed derivation:

```python
def derive_pair_seed(base_seed: int, *, task_id: int, repetition: int) -> int:
    payload = f"{base_seed}|{task_id}|{repetition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")
```

Validate the exact task/condition matrix and frozen selector values in a
model validator.

- [ ] **Step 4: Run domain tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_domain.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add configs/hiddenbench-ai-disclosure-stability.json `
  src/mas_experiment/hiddenbench_stability_domain.py `
  tests/test_hiddenbench_stability_domain.py
git commit -m "feat: define HiddenBench stability study"
```

---

### Task 2: Evidence-Backed LLM Disclosure Auditor

**Files:**
- Create: `src/mas_experiment/hiddenbench_ai_disclosure.py`
- Create: `tests/test_hiddenbench_ai_disclosure.py`

**Interfaces:**
- Consumes: `HiddenBenchRun`, `PromptProvider`, and owner-to-private-fact assignments.
- Produces: `FactDisclosureJudgment`, `DisclosureAudit`, `build_disclosure_audit_prompt()`, `parse_disclosure_audit()`, `validate_disclosure_evidence()`, and `audit_run_disclosure()`.

- [ ] **Step 1: Write failing parser and evidence tests**

```python
def test_audit_requires_one_judgment_per_owner_fact() -> None:
    payload = valid_audit_payload()
    payload["facts"].pop()
    with pytest.raises(ValueError, match="exactly one judgment"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_disclosed_evidence_must_exist_and_belong_to_owner() -> None:
    payload = valid_audit_payload()
    payload["facts"][0]["evidence_message_ids"] = ["peer-message"]
    with pytest.raises(ValueError, match="owner-authored"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_evidence_quote_must_be_exact_substring() -> None:
    payload = valid_audit_payload()
    payload["facts"][0]["evidence_quote"] = "invented quotation"
    with pytest.raises(ValueError, match="exact substring"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_ai_disclosure_rate_is_disclosed_fact_fraction() -> None:
    audit = parse_disclosure_audit(RUN, json.dumps(valid_audit_payload(disclosed=3)))
    assert audit.disclosure_rate == pytest.approx(0.75)
    assert audit.disclosure_percentage == pytest.approx(75.0)
```

- [ ] **Step 2: Run the auditor tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_ai_disclosure.py -q
```

Expected: import failure because the auditor module does not exist.

- [ ] **Step 3: Implement strict audit models and prompt construction**

Implement immutable models:

```python
class FactDisclosureJudgment(BaseModel):
    model_config = ConfigDict(frozen=True)
    fact_id: str
    owner_agent_id: str
    disclosed: bool
    evidence_message_ids: tuple[str, ...]
    evidence_quote: str
    reason: str
    confidence: float = Field(ge=0, le=1)


class DisclosureAudit(BaseModel):
    model_config = ConfigDict(frozen=True)
    study_key: StudyKey
    judge_model: str
    judge_prompt_version: str
    judgments: tuple[FactDisclosureJudgment, ...]
    disclosure_rate: float = Field(ge=0, le=1)
    provider_metadata: dict[str, Any]
```

The prompt must:

- list fact IDs and owner IDs;
- include all messages as `message_id | agent_id | text`;
- define owner disclosure, faithful paraphrase, polarity reversal, partial
  decision-relevant claims, and non-owner guesses;
- require strict JSON with no Markdown.

- [ ] **Step 4: Implement evidence validation and one repair call**

`parse_disclosure_audit(run, text)` must:

1. parse the outer JSON object;
2. require exactly the four expected fact IDs;
3. validate owner IDs;
4. verify every evidence ID and speaker;
5. require evidence for `disclosed=true`;
6. require no evidence for `disclosed=false`;
7. verify the exact quote against at least one referenced message;
8. compute disclosure rate in code rather than trusting a model-supplied percentage.

`audit_run_disclosure()` calls the provider once and makes one repair request
only after a parse or evidence error. Aggregate both calls in provider
metadata.

- [ ] **Step 5: Run auditor tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hiddenbench_ai_disclosure.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/mas_experiment/hiddenbench_ai_disclosure.py `
  tests/test_hiddenbench_ai_disclosure.py
git commit -m "feat: add evidence-backed disclosure auditor"
```

---

### Task 3: Rule Cross-Check and Consensus Dynamics

**Files:**
- Modify: `src/mas_experiment/hiddenbench_metrics.py`
- Create: `src/mas_experiment/hiddenbench_consensus.py`
- Create: `tests/test_hiddenbench_consensus.py`
- Modify: `tests/test_hiddenbench_metrics.py`

**Interfaces:**
- Produces: `RuleDisclosureEvidence`, `rule_disclosure_evidence()`, `extract_expressed_position()`, and `analyze_consensus_dynamics()`.
- Consumes: existing `lexical-semantic-v2` matching primitives, possible answers, and public messages.

- [ ] **Step 1: Write a failing rule-evidence test**

```python
def test_rule_disclosure_evidence_returns_fact_level_labels() -> None:
    evidence = rule_disclosure_evidence(SCORED_RUN)
    assert set(evidence) == set(SCORED_RUN.assignment.private_information.values())
    assert all(item.owner_agent_id for item in evidence.values())
    assert all(item.disclosed == bool(item.evidence_message_ids) for item in evidence.values())
```

- [ ] **Step 2: Run the rule-evidence test and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_metrics.py -q
```

Expected: failure because `rule_disclosure_evidence` is undefined.

- [ ] **Step 3: Expose existing rule matches without changing scoring**

Refactor the existing private-fact loop into:

```python
def rule_disclosure_evidence(run: HiddenBenchRawRun) -> dict[str, RuleDisclosureEvidence]:
    ...
```

Call the same helper from `score_hiddenbench_run()` so prior metric values and
tests remain unchanged.

- [ ] **Step 4: Write failing consensus tests**

```python
def test_ambiguous_multi_option_message_has_no_position() -> None:
    assert extract_expressed_position(
        "West City is supplied, but East Town is safer.",
        ("West City", "East Town", "North Hill"),
    ) is None


def test_stable_consensus_and_flip_are_counted() -> None:
    result = analyze_consensus_dynamics(
        messages=CONSENSUS_THEN_FLIP_MESSAGES,
        possible_answers=("West City", "East Town", "North Hill"),
        correct_answer="West City",
        new_rule_disclosures_by_message={},
    )
    assert result.first_consensus_turn == 4
    assert result.first_stable_consensus_turn == 4
    assert result.consensus_flips == 1
```

- [ ] **Step 5: Run consensus tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_consensus.py -q
```

Expected: import failure because the consensus module does not exist.

- [ ] **Step 6: Implement deterministic position and consensus analysis**

`extract_expressed_position()` returns an answer only when:

- exactly one possible answer is present and a recommendation cue appears; or
- a recommendation cue is within 80 characters of exactly one answer.

Supported cues include `choose`, `select`, `recommend`, `support`, `agree on`,
`vote for`, and their common inflections. Multiple competing recommended
answers return `None`.

Track each agent's latest unambiguous position after each public message.
Consensus exists only when all four agents have a position and all four match.
A stable consensus requires the same unanimous position through the next four
public speeches. A post-stable-consensus message is a repeated confirmation
when it supports the stable answer and contains no first-time rule disclosure.

- [ ] **Step 7: Run targeted and regression tests**

Run:

```powershell
python -m pytest tests/test_hiddenbench_consensus.py tests/test_hiddenbench_metrics.py -q
```

Expected: all tests pass and existing metric snapshots remain unchanged.

- [ ] **Step 8: Commit Task 3**

```powershell
git add src/mas_experiment/hiddenbench_metrics.py `
  src/mas_experiment/hiddenbench_consensus.py `
  tests/test_hiddenbench_consensus.py `
  tests/test_hiddenbench_metrics.py
git commit -m "feat: analyze disclosure evidence and consensus"
```

---

### Task 4: Resumable Paired Study Runner

**Files:**
- Create: `src/mas_experiment/hiddenbench_stability_protocol.py`
- Create: `tests/test_hiddenbench_stability_protocol.py`

**Interfaces:**
- Consumes: `run_hiddenbench_task()`, `run_hiddenbench_dynamic_task()`, `score_hiddenbench_run()`, `derive_pair_seed()`, task loader, and provider factories.
- Produces: `expected_study_keys()`, `run_study_pair()`, `read_completed_study_records()`, and `run_stability_study()`.

- [ ] **Step 1: Write failing complete-matrix and pairing tests**

```python
def test_expected_matrix_has_eighty_unique_keys() -> None:
    keys = expected_study_keys(CONFIG)
    assert len(keys) == 80
    assert len({key.value for key in keys}) == 80


@pytest.mark.asyncio
async def test_pair_reuses_seed_assignment_and_budget() -> None:
    fixed, dynamic = await run_study_pair(
        task=TASK,
        repetition=2,
        config=CONFIG,
        fixed_provider=ScriptedPromptProvider(FIXED_SCRIPT),
        dynamic_provider=ScriptedPromptProvider(DYNAMIC_SCRIPT),
    )
    assert fixed.pair_seed == dynamic.pair_seed
    assert fixed.assignment_fingerprint == dynamic.assignment_fingerprint
    assert len(fixed.run.discussion_messages) == 60
    assert len(dynamic.run.discussion_messages) == 60
    assert Counter(m.agent_id for m in dynamic.run.discussion_messages) == {
        agent: 15 for agent in AGENT_IDS
    }
```

- [ ] **Step 2: Run runner tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_protocol.py -q
```

Expected: import failure because the stability protocol does not exist.

- [ ] **Step 3: Implement paired execution**

For each task/repetition:

1. derive one pair seed;
2. run fixed with `run_hiddenbench_task()`;
3. score fixed with `score_hiddenbench_run()`;
4. pass the fixed assignment and run ID to `run_hiddenbench_dynamic_task()`;
5. validate equal assignment fingerprints and budgets;
6. return two immutable `StudyRunRecord` instances.

Execute the two conditions sequentially inside a pair: the frozen fixed run is
completed first so its exact assignment and run ID can be bound into the dynamic
record. Parallelism is allowed only across different task/repetition pairs, and
each run receives a fresh provider from an independent provider factory call.

- [ ] **Step 4: Write failing resume and atomic-append tests**

```python
@pytest.mark.asyncio
async def test_resume_skips_complete_pair_and_runs_missing_pair(tmp_path) -> None:
    output = tmp_path / "study.jsonl"
    write_pair(output, COMPLETE_PAIR)
    calls = await run_stability_study(..., output=output, resume=True)
    assert COMPLETE_PAIR_KEY not in calls.executed_pairs
    assert MISSING_PAIR_KEY in calls.executed_pairs


def test_partial_pair_is_rejected_on_resume(tmp_path) -> None:
    output = tmp_path / "study.jsonl"
    write_one_condition(output)
    with pytest.raises(ValueError, match="partial pair"):
        read_completed_study_records(output)
```

- [ ] **Step 5: Implement bounded concurrency and resume**

Use an `asyncio.Semaphore(config.experiment_workers)`. A pair is appended only
after both conditions validate. Existing complete pairs are skipped; partial,
duplicate, or malformed pairs stop before any new API call.

- [ ] **Step 6: Run protocol tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_protocol.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add src/mas_experiment/hiddenbench_stability_protocol.py `
  tests/test_hiddenbench_stability_protocol.py
git commit -m "feat: run resumable paired HiddenBench study"
```

---

### Task 5: AI-Rule Comparison, Gate, and Stability Reporting

**Files:**
- Create: `src/mas_experiment/hiddenbench_stability_gate.py`
- Create: `src/mas_experiment/hiddenbench_stability_reporting.py`
- Create: `tests/test_hiddenbench_stability_gate.py`
- Create: `tests/test_hiddenbench_stability_reporting.py`

**Interfaces:**
- Consumes: 80 study records, 80 disclosure audits, rule evidence, and consensus analyses.
- Produces: `build_stability_gate()`, `build_fact_comparisons()`, `summarize_stability()`, and `write_stability_bundle()`.

- [ ] **Step 1: Write failing gate tests**

```python
def test_complete_gate_passes() -> None:
    gate = build_stability_gate(CONFIG, COMPLETE_RECORDS, COMPLETE_AUDITS)
    assert gate.passed
    assert all(gate.checks.values())


def test_gate_fails_missing_audit_or_budget_mismatch() -> None:
    gate = build_stability_gate(CONFIG, BAD_RECORDS, MISSING_ONE_AUDIT)
    assert not gate.passed
    assert not gate.checks["complete_ai_audits"]
    assert not gate.checks["equal_speech_budgets"]
```

- [ ] **Step 2: Run gate tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_gate.py -q
```

Expected: import failure because the gate module does not exist.

- [ ] **Step 3: Implement the formal gate**

Required boolean checks:

- exact 80-key run matrix;
- exact 80-key audit matrix;
- unique keys;
- task and dataset hashes;
- paired seeds and assignments;
- provider settings;
- 60 speeches per run;
- 15 speeches per agent;
- sequential visibility;
- zero selector LLM calls;
- AI evidence validity;
- no secrets;
- deterministic artifact row ordering.

- [ ] **Step 4: Write failing comparison and report tests**

```python
def test_fact_comparison_exposes_disagreement() -> None:
    rows = build_fact_comparisons(RUN, AUDIT)
    row = next(item for item in rows if item.fact_id == "fact-2")
    assert row.ai_disclosed is True
    assert row.rule_disclosed is False
    assert row.requires_manual_review is True


def test_summary_contains_stability_and_boundary_language(tmp_path) -> None:
    paths = write_stability_bundle(...)
    report = paths.report.read_text(encoding="utf-8")
    assert "10 repetitions" in report
    assert "wrong consensus" in report
    assert "AI-rule agreement" in report
    assert "does not establish general superiority" in report
```

- [ ] **Step 5: Implement summaries and artifact bundle**

Write:

- run JSONL in sorted task/condition/repetition order;
- trace JSONL;
- AI-audit JSONL;
- disagreement CSV;
- summary CSV;
- Markdown report;
- gate JSON;
- final SHA-256 manifest.

Compute per task-condition means, standard deviations, counts out of 10, final
answer distributions, consensus timing, repetition rates, AI-rule agreement,
and paired fixed/dynamic differences.

- [ ] **Step 6: Run reporting tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hiddenbench_stability_gate.py `
  tests/test_hiddenbench_stability_reporting.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add src/mas_experiment/hiddenbench_stability_gate.py `
  src/mas_experiment/hiddenbench_stability_reporting.py `
  tests/test_hiddenbench_stability_gate.py `
  tests/test_hiddenbench_stability_reporting.py
git commit -m "feat: report HiddenBench stability study"
```

---

### Task 6: Offline Provider, CLI, and Reproduction Documentation

**Files:**
- Modify: `src/mas_experiment/providers.py`
- Modify: `src/mas_experiment/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `docs/hiddenbench-reproduction.md`

**Interfaces:**
- Produces: `StabilityOfflineProvider` and `mas-experiment hiddenbench-stability`.
- Consumes: study config, provider factories, runner, auditor, gate, and writer.

- [ ] **Step 1: Write a failing deterministic offline-provider test**

```python
@pytest.mark.asyncio
async def test_stability_offline_provider_returns_valid_vote_discussion_and_audit() -> None:
    provider = StabilityOfflineProvider()
    vote = await provider.complete(..., json_response=True)
    message = await provider.complete(..., json_response=False)
    audit = await provider.complete(
        agent_id="disclosure-auditor",
        system_prompt=AUDIT_SYSTEM,
        user_prompt=AUDIT_USER,
        seed=1,
        json_response=True,
    )
    assert parse_hiddenbench_vote(TASK, vote.text)
    assert message.text
    assert json.loads(audit.text)["facts"]
```

- [ ] **Step 2: Run the offline-provider test and verify RED**

Run:

```powershell
python -m pytest tests/test_cli.py -k stability_offline_provider -q
```

Expected: failure because `StabilityOfflineProvider` is undefined.

- [ ] **Step 3: Implement the deterministic offline provider**

Generate valid vote JSON from possible answers parsed from the prompt,
discussion text with one unambiguous recommendation, and audit JSON by reading
the fact/message blocks. Return zero API requests and stable metadata.

- [ ] **Step 4: Write failing CLI help and small-matrix end-to-end tests**

```python
def test_hiddenbench_stability_help_lists_resume_workers_and_judge() -> None:
    result = runner.invoke(app, ["hiddenbench-stability", "--help"])
    assert result.exit_code == 0
    assert "--resume" in result.output
    assert "--experiment-workers" in result.output
    assert "--judge-workers" in result.output
    assert "--skip-ai-judge" in result.output


def test_hiddenbench_stability_offline_writes_gated_bundle(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "hiddenbench-stability",
            "--offline",
            "--config",
            str(SMALL_STABILITY_CONFIG),
            "--output",
            str(tmp_path / "stability.jsonl"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "gate passed" in result.output
    assert (tmp_path / "stability.ai-disclosure.jsonl").exists()
    assert (tmp_path / "stability.summary.csv").exists()
```

- [ ] **Step 5: Implement the CLI command**

The command:

1. loads and validates config;
2. checks output/resume state;
3. creates independent provider factories;
4. runs or resumes all pairs;
5. audits every run not already audited;
6. builds consensus and rule comparisons;
7. runs the gate;
8. writes the bundle only after the gate passes;
9. reports logical response slots, formal requests, audit requests, repair
   requests, and selector calls separately.

- [ ] **Step 6: Update usage documentation**

Document offline smoke test, real DeepSeek run, resume command, outputs, AI
audit limitations, and the equal-speech/not-equal-token distinction.

- [ ] **Step 7: Run CLI and full regression tests**

Run:

```powershell
python -m pytest tests/test_cli.py -k hiddenbench_stability -q
python -m pytest -q
```

Expected: targeted and full suites pass.

- [ ] **Step 8: Commit Task 6**

```powershell
git add src/mas_experiment/providers.py src/mas_experiment/cli.py `
  tests/test_cli.py README.md docs/hiddenbench-reproduction.md
git commit -m "feat: add HiddenBench stability CLI"
```

---

### Task 7: Formal DeepSeek Execution and Stability Analysis

**Files:**
- Create: `artifacts/hiddenbench-stability-20260729.jsonl`
- Create: `artifacts/hiddenbench-stability-20260729.trace.jsonl`
- Create: `artifacts/hiddenbench-stability-20260729.ai-disclosure.jsonl`
- Create: `artifacts/hiddenbench-stability-20260729.disagreements.csv`
- Create: `artifacts/hiddenbench-stability-20260729.summary.csv`
- Create: `artifacts/hiddenbench-stability-20260729.md`
- Create: `artifacts/hiddenbench-stability-20260729.gate.json`
- Create: `artifacts/hiddenbench-stability-20260729.manifest.json`

**Interfaces:**
- Consumes: validated CLI and configured DeepSeek environment.
- Produces: the formal 80-run, 80-audit study bundle.

- [ ] **Step 1: Run full tests before spending API budget**

```powershell
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run offline end-to-end**

```powershell
mas-experiment hiddenbench-stability `
  --offline `
  --config configs/hiddenbench-ai-disclosure-stability.json `
  --output artifacts/hiddenbench-stability-offline.jsonl `
  --no-resume
```

Expected: 80 run keys, 80 audits, 4,800 speeches, and a passing gate.

- [ ] **Step 3: Verify DeepSeek configuration without printing the key**

Run a script that prints only `SET`/`MISSING` for `OPENAI_API_KEY`, plus the
base URL and model. Require:

```text
OPENAI_API_KEY=SET
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_CHAT_COMPLETION_MODEL=deepseek-v4-flash
```

- [ ] **Step 4: Execute the real resumable study**

```powershell
mas-experiment hiddenbench-stability `
  --config configs/hiddenbench-ai-disclosure-stability.json `
  --output artifacts/hiddenbench-stability-20260729.jsonl `
  --resume `
  --experiment-workers 4 `
  --judge-workers 8
```

If interrupted, rerun the identical command. Never delete validated completed
pairs to restart.

- [ ] **Step 5: Validate formal artifact counts and hashes**

Use a standalone read-only Python check to assert:

- 80 unique study records;
- 80 unique audits;
- 4,800 public messages;
- 40 fixed and 40 dynamic runs;
- 10 repetitions per task-condition;
- every dynamic run has 15 speeches per agent;
- all gate checks are true;
- every manifest hash matches.

- [ ] **Step 6: Review the analysis**

For each task, record:

- fixed and dynamic correct-majority counts out of 10;
- fixed and dynamic wrong-consensus counts out of 10;
- AI and rule disclosure means;
- AI-rule disagreement facts;
- final answer distributions;
- first/stable consensus timing;
- consensus flips;
- post-consensus repetition.

Write only claims supported by the 10-run distributions.

- [ ] **Step 7: Commit formal artifacts**

```powershell
git add artifacts/hiddenbench-stability-20260729*
git commit -m "exp: record HiddenBench stability study"
```

---

### Task 8: Official Per-Task Comparison and Word Report Revision

**Files:**
- Create: `reports/hiddenbench-official-task-comparison-20260729.csv`
- Create: `reports/hiddenbench-official-task-comparison-20260729.md`
- Create outside repository: `C:\Users\liuli\Desktop\给彭老师的HiddenBench_MAF复现实验最终报告_2026-07-29_AI披露与稳定性修订版.docx`
- Modify: `docs/hiddenbench-reproduction.md`

**Interfaces:**
- Consumes: official HiddenBench result bundle, the formal stability bundle, and the retained teacher report.
- Produces: a task-level official comparison and revised Word deliverable.

- [ ] **Step 1: Extract official task-level results**

Use the official `Yassellee/HiddenBench_ICML` code and
`YuxuanLi1225/HiddenBench-results` bundle. Extract GPT-4.1 task-level results
for IDs `1`, `5`, `7`, and `25`, including session count and pre/post/full
accuracy. Preserve the official file paths and hashes in the Markdown report.

- [ ] **Step 2: State comparison boundaries**

The comparison must say:

- the original implementation is a custom Python simulator, not MAF;
- the paper evaluates 15 models from GPT, Gemini, Qwen, and Llama families;
- GPT-4.1 is the primary verification/ablation model;
- DeepSeek is not a same-model reproduction;
- task-level behavior can be compared, but numeric gaps cannot be attributed
  solely to MAF.

- [ ] **Step 3: Revise the Word report from the retained source**

Use the `documents:documents` skill and bundled workspace Python. Preserve the
source DOCX and insert:

- original framework/model clarification;
- official per-task comparison;
- 15-round ablation rationale and early-consensus metrics;
- exact confirmed MAST mappings with task/agent/message evidence;
- the distinction between round-one disclosure, Reveal-All, and Full Profile;
- AI disclosure method and AI-rule disagreement;
- 10-repetition stability results and interpretation.

- [ ] **Step 4: Run structural and visual QA**

Run:

```powershell
python render_docx.py <final.docx> --output_dir <qa-dir> --emit_pdf
```

If Word/LibreOffice remains unavailable, run section, heading, table geometry,
package-part, source-hash, placeholder, and reopen checks, then disclose the
missing visual render in the final handoff.

- [ ] **Step 5: Commit repository reports and documentation**

```powershell
git add reports/hiddenbench-official-task-comparison-20260729.csv `
  reports/hiddenbench-official-task-comparison-20260729.md `
  docs/hiddenbench-reproduction.md
git commit -m "docs: analyze HiddenBench stability results"
```

---

### Task 9: Final Verification and PR Update

**Files:**
- Verify all changed source, tests, artifacts, reports, and documentation.
- Update existing Draft PR #4; do not create a second PR.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: pushed branch, updated PR description, and verified Word report.

- [ ] **Step 1: Run fresh complete verification**

```powershell
python -m pytest -q
python -m compileall -q src tests
git diff --check master...HEAD
git status --short
```

Expected: all tests pass, compilation succeeds, diff check is empty, and the
working tree is clean after final commits.

- [ ] **Step 2: Revalidate formal study artifacts**

Run the standalone 80-run/80-audit/4,800-message/hash validation from Task 7
against the committed files.

- [ ] **Step 3: Push the current branch**

```powershell
git push origin codex/budget-matched-dynamic
```

- [ ] **Step 4: Update Draft PR #4**

Update the PR body with:

- AI disclosure auditor;
- 4 × 2 × 10 study;
- formal request and token totals;
- stability results;
- official per-task comparison;
- fresh test count;
- Word report path as a local deliverable, not a repository link.

- [ ] **Step 5: Report verified outcomes**

Provide:

- PR #4 URL;
- formal artifact/report links;
- final Word document link;
- test and gate evidence;
- the exact stability conclusion and its limits.
