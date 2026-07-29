# Budget-Matched HiddenBench Dynamic Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and execute an auditable three-task HiddenBench pilot that compares the frozen fixed round-robin baseline with a content-aware dynamic order while holding every agent to 15 speeches and every task to 60 discussion calls.

**Architecture:** Keep the faithful baseline runner unchanged. Add a pure selector module, a separate dynamic protocol wrapper, a frozen-baseline validator, and a dedicated artifact/report layer. The CLI performs all baseline and configuration checks before constructing a real provider, then writes dynamic runs, 180 selector events, a paired report, a protocol gate, and a manifest.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest, existing Microsoft Agent Framework provider adapter, DeepSeek OpenAI-compatible API.

## Global Constraints

- Pilot task IDs are exactly `1, 5, 7`.
- Baseline Git commit is `2b9b0a9`.
- Baseline JSONL SHA-256 is `e3064a90e7fff6313821240828bc28afeed44500be47c60eb6d195799672e4eb`.
- Baseline report SHA-256 is `c819658f1cbe72126ef403c29cfbcd7904fc5f05f1f11c989cc8ae21e99e8108`.
- Baseline config SHA-256 is `f1769b2b92f117aa56699747833a091727e7db050d75b1738ddb05f168424ce`.
- Dataset SHA-256 is `2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3`.
- Provider model must report `deepseek-v4-flash`, temperature `0`, and thinking `disabled` for a real run.
- Prompt version remains `hiddenbench-appendix-a4-v1`.
- Every task has four agents, 15 speeches per agent, and 60 discussion speeches total.
- Speaker selection makes zero LLM calls and does not use the correct answer, hidden-post votes, or full-profile votes.
- The selector score is exactly `0.30 * disagreement + 0.30 * undisclosed + 0.15 * related_discussion + 0.15 * response_due + 0.10 * waiting`.
- Dynamic `round_index` is `turn_index // 4 + 1`; it is a reporting block, not a balanced round.
- The pilot is descriptive and cannot support a significance or superiority claim.

---

## File structure

- Create `configs/hiddenbench-dynamic-pilot.json`: immutable pilot task, baseline, provider, quota, and selector settings.
- Create `src/mas_experiment/hiddenbench_dynamic_domain.py`: selector candidate/event and dynamic-run Pydantic models.
- Create `src/mas_experiment/hiddenbench_dynamic_selector.py`: atomization, stance extraction, five-factor scoring, and deterministic selection.
- Create `src/mas_experiment/hiddenbench_dynamic_gate.py`: frozen baseline/config/hash validation and protocol gate evaluation.
- Create `src/mas_experiment/hiddenbench_dynamic_protocol.py`: 72-slot dynamic task runner using the pure selector.
- Create `src/mas_experiment/hiddenbench_dynamic_reporting.py`: dynamic bundle, trace, paired report, gate, and manifest writer.
- Modify `src/mas_experiment/cli.py`: add `hiddenbench-dynamic-pilot`.
- Create `tests/test_hiddenbench_dynamic_domain.py`.
- Create `tests/test_hiddenbench_dynamic_selector.py`.
- Create `tests/test_hiddenbench_dynamic_gate.py`.
- Create `tests/test_hiddenbench_dynamic_protocol.py`.
- Create `tests/test_hiddenbench_dynamic_reporting.py`.
- Modify `tests/test_cli.py`.
- Modify `README.md` and `docs/hiddenbench-reproduction.md`.

### Task 1: Lock the pilot configuration and audit models

**Files:**
- Create: `configs/hiddenbench-dynamic-pilot.json`
- Create: `src/mas_experiment/hiddenbench_dynamic_domain.py`
- Create: `tests/test_hiddenbench_dynamic_domain.py`

**Interfaces:**
- Produces: `DynamicSelectorConfig`, `SelectorCandidateScore`, `SelectorEvent`, `DynamicHiddenBenchRun`, and `load_dynamic_pilot_config(path: Path)`.
- Consumes later: selector, protocol, gate, reporting, and CLI tasks all use these exact models.

- [ ] **Step 1: Write failing configuration and model tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicSelectorConfig,
    SelectorCandidateScore,
    load_dynamic_pilot_config,
)


ROOT = Path(__file__).parents[1]


def test_committed_dynamic_config_locks_budget_and_weights() -> None:
    config = load_dynamic_pilot_config(
        ROOT / "configs" / "hiddenbench-dynamic-pilot.json"
    )
    assert config.pilot_task_ids == (1, 5, 7)
    assert config.total_speeches == 60
    assert config.speeches_per_agent == 15
    assert sum(config.selector_weights.values()) == pytest.approx(1.0)
    assert config.selector_llm_calls == 0
    assert config.baseline_jsonl_sha256 == (
        "e3064a90e7fff6313821240828bc28afe"
        "ed44500be47c60eb6d195799672e4eb"
    )


def test_candidate_score_rejects_out_of_range_factor() -> None:
    with pytest.raises(ValidationError):
        SelectorCandidateScore(
            agent_id="agent-a",
            disagreement=1.1,
            undisclosed=0,
            related_discussion=0,
            response_due=0,
            waiting=0,
            weighted_total=0,
            remaining_quota=15,
            raw_waiting=1,
            latest_stance="West City",
            evidence_atom_ids=(),
            selected=False,
            tie_break_reason=None,
        )


def test_selector_config_rejects_weights_not_summing_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        DynamicSelectorConfig(
            disagreement=0.5,
            undisclosed=0.5,
            related_discussion=0.5,
            response_due=0,
            waiting=0,
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_dynamic_domain.py -q
```

Expected: collection fails because `hiddenbench_dynamic_domain` does not exist.

- [ ] **Step 3: Add the exact pilot configuration**

```json
{
  "configuration_version": "hiddenbench-dynamic-pilot-v1",
  "pilot_task_ids": [1, 5, 7],
  "base_seed": 20260728,
  "dataset_sha256": "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3",
  "prompt_version": "hiddenbench-appendix-a4-v1",
  "total_speeches": 60,
  "speeches_per_agent": 15,
  "selector_llm_calls": 0,
  "selector_weights": {
    "disagreement": 0.3,
    "undisclosed": 0.3,
    "related_discussion": 0.15,
    "response_due": 0.15,
    "waiting": 0.1
  },
  "evidence_rule_version": "lexical-semantic-v2",
  "provider": {
    "model": "deepseek-v4-flash",
    "temperature": 0,
    "thinking": "disabled"
  },
  "frozen_baseline": {
    "git_commit": "2b9b0a9",
    "jsonl": "artifacts/hiddenbench-screening-20260728-v2.jsonl",
    "jsonl_sha256": "e3064a90e7fff6313821240828bc28afeed44500be47c60eb6d195799672e4eb",
    "report": "artifacts/hiddenbench-screening-20260728-v2.md",
    "report_sha256": "c819658f1cbe72126ef403c29cfbcd7904fc5f05f1f11c989cc8ae21e99e8108",
    "config": "configs/hiddenbench-screening.json",
    "config_sha256": "f1769b2b92f117aa56699747833a091727e7db050d75b1738ddb05f168424ce"
  }
}
```

- [ ] **Step 4: Implement frozen Pydantic models**

`DynamicPilotConfig` must expose flattened read-only properties for the
baseline hashes and validate:

```python
if self.total_speeches != len(AGENT_IDS) * self.speeches_per_agent:
    raise ValueError("total speech budget must equal per-agent quotas")
if self.selector_llm_calls != 0:
    raise ValueError("speaker selection must not call an LLM")
```

`SelectorEvent` contains `task_id`, `turn_index`, `round_index`,
`selected_agent_id`, and a tuple of candidate scores. `DynamicHiddenBenchRun`
contains one scored `HiddenBenchRun`, 60 events, the baseline run ID, the
dynamic configuration fingerprint, and `orchestration_mode="dynamic"`.

- [ ] **Step 5: Run the domain tests and full suite**

Run:

```powershell
python -m pytest tests/test_hiddenbench_dynamic_domain.py -q
python -m pytest -q
```

Expected: new tests pass and the full suite remains green.

- [ ] **Step 6: Commit**

```powershell
git add configs/hiddenbench-dynamic-pilot.json src/mas_experiment/hiddenbench_dynamic_domain.py tests/test_hiddenbench_dynamic_domain.py
git commit -m "feat: define budget-matched dynamic pilot models"
```

### Task 2: Implement the deterministic content-aware selector

**Files:**
- Create: `src/mas_experiment/hiddenbench_dynamic_selector.py`
- Create: `tests/test_hiddenbench_dynamic_selector.py`

**Interfaces:**
- Consumes: `HiddenBenchTask`, `HiddenBenchAssignment`, hidden-pre votes, public messages, remaining quotas, last-spoken turns, and `DynamicSelectorConfig`.
- Produces:
  - `atomize_private_information(assignment) -> dict[str, tuple[InformationAtom, ...]]`
  - `extract_stance(task, text, previous) -> str | None`
  - `score_dynamic_candidates(...) -> tuple[SelectorCandidateScore, ...]`
  - `select_dynamic_speaker(...) -> tuple[str, tuple[SelectorCandidateScore, ...]]`

- [ ] **Step 1: Read the project test-quality rules**

Read:

```powershell
Get-Content -Raw C:\Users\liuli\.codex\plugins\cache\openai-curated-remote\superpowers\6.2.0\skills\test-driven-development\writing-good-tests.md
```

- [ ] **Step 2: Write failing atomization tests**

Cover all three pilot shapes:

```python
def test_atomizer_keeps_heading_on_criterion_lines() -> None:
    atoms = atomize_private_text(
        "Starlight Incorporated:\n- (e) Y\n- (h) Y"
    )
    assert [atom.text for atom in atoms] == [
        "Starlight Incorporated: (e) Y",
        "Starlight Incorporated: (h) Y",
    ]


def test_atomizer_keeps_candidate_heading_on_biographical_bullets() -> None:
    atoms = atomize_private_text(
        "Stevens' information:\n"
        "- Left before raising funds\n"
        "Roberts' information:\n"
        "- Increased faculty diversity"
    )
    assert [atom.text for atom in atoms] == [
        "Stevens' information: Left before raising funds",
        "Roberts' information: Increased faculty diversity",
    ]


def test_atomizer_treats_single_sentence_as_one_atom() -> None:
    atoms = atomize_private_text(
        "A mudslide covered the driveway to North Hill."
    )
    assert len(atoms) == 1
```

- [ ] **Step 3: Run atomization tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_dynamic_selector.py -q
```

Expected: import failure because selector functions do not exist.

- [ ] **Step 4: Implement minimal atomization**

Use stable atom IDs:

```python
atom_id = hashlib.sha256(
    f"{owner}|{index}|{text}".encode("utf-8")
).hexdigest()[:16]
```

Ignore blank lines and heading-only lines. Prefix each bullet or criterion
line with the most recent heading. Preserve source order.

- [ ] **Step 5: Run atomization tests and verify GREEN**

Run the selector test file. Expected: atomization tests pass.

- [ ] **Step 6: Write failing stance and factor tests**

```python
def test_stance_updates_only_for_one_exact_possible_answer() -> None:
    assert extract_stance(TASK_1, "West City is safest.", "East Town") == (
        "West City"
    )
    assert extract_stance(
        TASK_1,
        "West City is open but East Town has volunteers.",
        "North Hill",
    ) == "North Hill"


def test_unique_plurality_gives_dissenter_disagreement_one() -> None:
    scores = score_dynamic_candidates(
        task=TASK_1,
        assignment=ASSIGNMENT_1,
        pre_stances={
            "agent-a": "West City",
            "agent-b": "East Town",
            "agent-c": "East Town",
            "agent-d": "East Town",
        },
        public_messages=(),
        remaining_quotas={agent: 15 for agent in AGENT_IDS},
        last_spoken_turns={agent: -1 for agent in AGENT_IDS},
        config=SELECTOR_CONFIG,
        turn_index=0,
    )
    by_agent = {score.agent_id: score for score in scores}
    assert by_agent["agent-a"].disagreement == 1
    assert by_agent["agent-b"].disagreement == 0


def test_agents_with_zero_quota_are_not_scored() -> None:
    scores = score_dynamic_candidates(
        **selector_state(remaining_quotas={
            "agent-a": 0,
            "agent-b": 15,
            "agent-c": 15,
            "agent-d": 15,
        })
    )
    assert {score.agent_id for score in scores} == {
        "agent-b", "agent-c", "agent-d"
    }
```

Add focused cases for:

- no unique plurality gives disagreement `0.5`;
- owner disclosure reduces `undisclosed`;
- a new message naming an answer in a candidate's undisclosed atom triggers
  `related_discussion`;
- another owner's newly disclosed atom triggers `response_due`;
- waiting is normalized among eligible agents;
- exact ties use remaining quota, raw waiting, then lexical agent ID;
- selecting never uses `task.correct_answer`.

- [ ] **Step 7: Run factor tests and verify RED**

Expected: failures identify the missing score/selection behavior.

- [ ] **Step 8: Implement the five factors and tie-break**

Use `lexical_fact_match` for atom disclosure and use only exact
case-insensitive `task.possible_answers` phrases for stance and related-answer
matching. Sort candidates with:

```python
key=lambda item: (
    -item.weighted_total,
    -item.remaining_quota,
    -item.raw_waiting,
    item.agent_id,
)
```

Set `selected=True` only on the winner and record one of
`highest_score`, `remaining_quota`, `raw_waiting`, or `agent_id` as the
tie-break reason.

- [ ] **Step 9: Run selector tests and full suite**

```powershell
python -m pytest tests/test_hiddenbench_dynamic_selector.py -q
python -m pytest -q
```

- [ ] **Step 10: Commit**

```powershell
git add src/mas_experiment/hiddenbench_dynamic_selector.py tests/test_hiddenbench_dynamic_selector.py
git commit -m "feat: add deterministic HiddenBench speaker selector"
```

### Task 3: Validate the frozen baseline before provider creation

**Files:**
- Create: `src/mas_experiment/hiddenbench_dynamic_gate.py`
- Create: `tests/test_hiddenbench_dynamic_gate.py`

**Interfaces:**
- Produces:
  - `load_and_validate_frozen_baseline(root, config) -> dict[int, HiddenBenchRun]`
  - `validate_dynamic_protocol(dynamic_runs, selection_events, config) -> PilotGate`
- The CLI must call the first function before `create_hiddenbench_provider`.

- [ ] **Step 1: Write failing happy-path and tamper tests**

```python
def test_committed_frozen_baseline_validates() -> None:
    runs = load_and_validate_frozen_baseline(ROOT, CONFIG)
    assert set(runs) >= {1, 5, 7}
    assert all(len(runs[task_id].discussion_messages) == 60 for task_id in (1,5,7))


def test_tampered_baseline_is_rejected_before_json_parse(tmp_path: Path) -> None:
    copied = copy_frozen_files(tmp_path)
    copied.jsonl.write_bytes(copied.jsonl.read_bytes() + b" ")
    with pytest.raises(ValueError, match="baseline JSONL SHA-256 mismatch"):
        load_and_validate_frozen_baseline(tmp_path, copied.config)


def test_wrong_fixed_speaker_order_is_rejected(tmp_path: Path) -> None:
    copied = copy_frozen_files(tmp_path, recompute_hashes=True)
    mutate_first_record_speaker(copied.jsonl, "agent-d")
    with pytest.raises(ValueError, match="fixed round-robin"):
        load_and_validate_frozen_baseline(tmp_path, copied.config)
```

Also test rejection of:

- wrong config hash;
- wrong report hash;
- missing pilot task;
- assignment different from `assign_hidden_information(task, seed)`;
- baseline post votes not unanimous wrong for IDs 1, 5, and 7;
- provider metadata not reporting the frozen model, temperature, or thinking.

- [ ] **Step 2: Run gate tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hiddenbench_dynamic_gate.py -q
```

- [ ] **Step 3: Implement byte-hash validation and structural checks**

Validate hashes before loading JSON. Parse each JSONL line through
`HiddenBenchRun.model_validate_json`. Check the ten baseline task IDs, then
return the three pilot records by ID. Validate all 60 speakers against:

```python
tuple(AGENT_IDS[index % 4] for index in range(60))
```

Never rewrite frozen files.

- [ ] **Step 4: Implement the post-run protocol gate**

`PilotGate` contains named boolean checks and `passed`. Verify:

- 3 runs and task IDs `1,5,7`;
- 60 messages/run and 15 messages/agent;
- 60 events/run;
- selected candidate is eligible and is the logged deterministic winner;
- visibility length equals turn index;
- selected event agent equals actual message agent;
- selector LLM calls are zero;
- provider settings match the frozen DeepSeek settings for a real run; scripted
  runs explicitly identify `scripted-offline` and are never compared as model
  outcomes;
- assignments match the frozen baseline.

- [ ] **Step 5: Run gate tests and full suite**

```powershell
python -m pytest tests/test_hiddenbench_dynamic_gate.py -q
python -m pytest -q
```

- [ ] **Step 6: Commit**

```powershell
git add src/mas_experiment/hiddenbench_dynamic_gate.py tests/test_hiddenbench_dynamic_gate.py
git commit -m "feat: gate dynamic pilot against frozen baseline"
```

### Task 4: Run a 60-turn quota-matched dynamic protocol

**Files:**
- Create: `src/mas_experiment/hiddenbench_dynamic_protocol.py`
- Create: `tests/test_hiddenbench_dynamic_protocol.py`

**Interfaces:**
- Consumes: task, provider, seed, frozen assignment, frozen baseline run ID,
  and pilot config.
- Produces:
  - `run_hiddenbench_dynamic_task(...) -> DynamicHiddenBenchRun`
- Reuses: `complete_hiddenbench_vote`, existing prompt builders,
  `score_hiddenbench_run`, and the pure selector.

- [ ] **Step 1: Write the failing 72-slot protocol test**

```python
@pytest.mark.asyncio
async def test_dynamic_protocol_has_72_slots_and_exact_15_each() -> None:
    provider = ScriptedPromptProvider(protocol_script())
    dynamic = await run_hiddenbench_dynamic_task(
        TASK,
        provider,
        seed=20260728,
        assignment=ASSIGNMENT,
        baseline_run_id="frozen-run",
        config=CONFIG,
    )

    assert len(provider.calls) == 72
    assert len(dynamic.run.discussion_messages) == 60
    assert Counter(
        message.agent_id for message in dynamic.run.discussion_messages
    ) == {agent: 15 for agent in AGENT_IDS}
    assert len(dynamic.selection_events) == 60
    assert dynamic.run.provider_metadata["selector_llm_calls"] == 0
```

- [ ] **Step 2: Run the protocol test and verify RED**

Expected: import failure for the missing dynamic protocol.

- [ ] **Step 3: Write failing visibility and quota-exhaustion tests**

Assert every message sees exactly all earlier message IDs, and an agent never
appears again after its recorded remaining quota reaches zero. Assert
`round_index == turn_index // 4 + 1`.

- [ ] **Step 4: Implement the dynamic runner**

Follow the baseline phase order:

```python
pre votes -> 60 selected discussion calls -> post votes -> full votes
```

At each discussion turn:

1. score candidates from current public history;
2. append one `SelectorEvent`;
3. call the selected agent exactly once;
4. append one `HiddenBenchMessage`;
5. decrement only that agent's quota;
6. update last-spoken turn.

Do not pass selector scores or other agents' private information into the
model prompt.

- [ ] **Step 5: Add failure tests**

Cover:

- empty discussion completion aborts without consuming a later slot;
- provider error identifies task, agent, and turn;
- assignment task ID mismatch fails before the first provider call;
- a selector event cannot select an exhausted agent;
- post-vote prompts contain all 60 dynamic messages.

- [ ] **Step 6: Run protocol tests and full suite**

```powershell
python -m pytest tests/test_hiddenbench_dynamic_protocol.py -q
python -m pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/hiddenbench_dynamic_protocol.py tests/test_hiddenbench_dynamic_protocol.py
git commit -m "feat: run quota-matched HiddenBench dynamic protocol"
```

### Task 5: Export the selector trace and paired comparison

**Files:**
- Create: `src/mas_experiment/hiddenbench_dynamic_reporting.py`
- Create: `tests/test_hiddenbench_dynamic_reporting.py`

**Interfaces:**
- Produces:
  - `build_paired_dynamic_report(baseline, dynamic) -> str`
  - `write_dynamic_pilot_bundle(...) -> DynamicBundlePaths`
- Consumes the validated three baseline runs, three dynamic runs, and a
  `PilotGate`.

- [ ] **Step 1: Write failing artifact-completeness test**

```python
def test_bundle_writes_runs_trace_report_gate_and_manifest(tmp_path: Path) -> None:
    paths = write_dynamic_pilot_bundle(
        baseline_runs=BASELINE_RUNS,
        dynamic_runs=DYNAMIC_RUNS,
        gate=PASSING_GATE,
        output=tmp_path / "hiddenbench-dynamic-pilot-20260729.jsonl",
    )
    assert paths.runs.exists()
    assert paths.trace.exists()
    assert paths.report.exists()
    assert paths.gate.exists()
    assert paths.manifest.exists()
    assert len(paths.trace.read_text(encoding="utf-8").splitlines()) == 180
```

- [ ] **Step 2: Run reporting tests and verify RED**

- [ ] **Step 3: Write failing comparison-content tests**

Require the Markdown report to contain, for each ID:

- baseline and dynamic `Y_pre`, `Y_post`, and integration gain;
- majority correctness, unanimity, wrong consensus;
- disclosure and cross-use rates;
- MAST candidate counts by mode;
- 60/60 discussion calls and 15/15/15/15 per-agent counts;
- prompt, completion, and total tokens;
- selector call count zero;
- provider-drift limitation;
- a blank manual-review status marked `pending`, never copied from baseline.

- [ ] **Step 4: Implement JSONL and Markdown serialization**

Use UTF-8 JSON with `ensure_ascii=False`. Run the existing secret scanner or
move it to a shared public helper before writing. Write to temporary files and
replace destinations only after all content validates.

The manifest must cover runs, trace, report, and gate. The gate file is
written only when every structural check has executed; it records `passed`
independently of outcome quality.

- [ ] **Step 5: Add a token-budget diagnostic test**

Construct unequal baseline/dynamic usage and assert the report says speech
budgets are controlled but token budgets differ. It must not describe token
usage as controlled.

- [ ] **Step 6: Run reporting tests and full suite**

```powershell
python -m pytest tests/test_hiddenbench_dynamic_reporting.py -q
python -m pytest -q
```

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/hiddenbench_dynamic_reporting.py tests/test_hiddenbench_dynamic_reporting.py
git commit -m "feat: report paired HiddenBench dynamic pilot"
```

### Task 6: Add a preflight-safe CLI and offline end-to-end test

**Files:**
- Modify: `src/mas_experiment/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `docs/hiddenbench-reproduction.md`

**Interfaces:**
- Produces command:
  - `python -m mas_experiment.cli hiddenbench-dynamic-pilot`

- [ ] **Step 1: Write the failing CLI help test**

```python
def test_dynamic_pilot_help_lists_frozen_baseline_and_output() -> None:
    result = runner.invoke(app, ["hiddenbench-dynamic-pilot", "--help"])
    assert result.exit_code == 0
    assert "--frozen-baseline" in result.output
    assert "--config" in result.output
    assert "--output" in result.output
```

- [ ] **Step 2: Run the help test and verify RED**

- [ ] **Step 3: Write the failing preflight-order test**

Monkeypatch `create_hiddenbench_provider` to raise if called. Supply a
tampered baseline and assert the CLI reports the hash failure without invoking
the provider factory.

- [ ] **Step 4: Write the failing scripted end-to-end test**

Use one strict script containing 216 logical outputs:

```text
3 tasks * (4 pre + 60 discussion + 4 post + 4 full) = 216
```

Assert the CLI writes all five artifact types, reports 3 records and 216
logical slots, and the gate passes.

- [ ] **Step 5: Implement the command**

Exact defaults:

```text
--config configs/hiddenbench-dynamic-pilot.json
--frozen-baseline artifacts/hiddenbench-screening-20260728-v2.jsonl
--output artifacts/hiddenbench-dynamic-pilot-20260729.jsonl
--provider deepseek
--base-seed 20260728
```

Also accept `--provider scripted --script <path>` and `--skip-connectivity`.
Refuse any existing output bundle unless `--overwrite` is explicit. Do not
include the optional connectivity probe in the formal call count.

- [ ] **Step 6: Document reproducible commands**

Add scripted validation:

```powershell
python -m mas_experiment.cli hiddenbench-dynamic-pilot `
  --provider scripted `
  --script tests/fixtures/hiddenbench_dynamic_script.json `
  --skip-connectivity `
  --output artifacts/hiddenbench-dynamic-pilot-offline.jsonl
```

Add real execution:

```powershell
python -m mas_experiment.cli hiddenbench-dynamic-pilot `
  --provider deepseek `
  --skip-connectivity `
  --output artifacts/hiddenbench-dynamic-pilot-20260729.jsonl
```

- [ ] **Step 7: Run targeted and full tests**

```powershell
python -m pytest tests/test_cli.py -q
python -m pytest -q
python -m mas_experiment.cli hiddenbench-dynamic-pilot --help
```

- [ ] **Step 8: Commit**

```powershell
git add src/mas_experiment/cli.py tests/test_cli.py README.md docs/hiddenbench-reproduction.md tests/fixtures/hiddenbench_dynamic_script.json
git commit -m "feat: add HiddenBench dynamic pilot command"
```

### Task 7: Run the offline audit gate

**Files:**
- Generate outside Git or under a disposable `artifacts/` prefix first.

- [ ] **Step 1: Execute the scripted pilot**

```powershell
python -m mas_experiment.cli hiddenbench-dynamic-pilot `
  --provider scripted `
  --script tests/fixtures/hiddenbench_dynamic_script.json `
  --skip-connectivity `
  --output artifacts/hiddenbench-dynamic-pilot-offline.jsonl `
  --overwrite
```

- [ ] **Step 2: Independently inspect counts**

Run a Python audit that asserts:

```python
len(runs) == 3
len(trace_events) == 180
all(len(run["run"]["discussion_messages"]) == 60 for run in runs)
all(Counter(m["agent_id"] for m in run["run"]["discussion_messages"])
    == {"agent-a": 15, "agent-b": 15, "agent-c": 15, "agent-d": 15}
    for run in runs)
gate["passed"] is True
```

- [ ] **Step 3: Verify artifact hashes**

Recompute SHA-256 for each manifest entry and compare byte-for-byte.

- [ ] **Step 4: Run the full test suite**

```powershell
python -m pytest -q
git diff --check
```

- [ ] **Step 5: Commit only stable fixtures or documentation changes**

Do not commit disposable offline result bundles unless they are explicitly
referenced as test fixtures.

### Task 8: Execute the real three-task DeepSeek pilot

**Files:**
- Generate:
  - `artifacts/hiddenbench-dynamic-pilot-20260729.jsonl`
  - `artifacts/hiddenbench-dynamic-pilot-20260729.trace.jsonl`
  - `artifacts/hiddenbench-dynamic-pilot-20260729.md`
  - `artifacts/hiddenbench-dynamic-pilot-20260729.gate.json`
  - `artifacts/hiddenbench-dynamic-pilot-20260729.manifest.json`

- [ ] **Step 1: Verify environment without printing secrets**

Check only presence and non-secret settings:

```powershell
@(
  'OPENAI_API_KEY',
  'OPENAI_BASE_URL',
  'OPENAI_CHAT_COMPLETION_MODEL'
) | ForEach-Object {
  if (-not [Environment]::GetEnvironmentVariable($_)) {
    throw "Missing $_"
  }
}
```

Print base URL and model only. Never print the API key.

- [ ] **Step 2: Run the real pilot**

```powershell
python -m mas_experiment.cli hiddenbench-dynamic-pilot `
  --provider deepseek `
  --skip-connectivity `
  --output artifacts/hiddenbench-dynamic-pilot-20260729.jsonl
```

Expected without vote repairs: 3 records, 216 logical slots, 216 formal API
requests, 180 discussion speeches, and 180 selector events.

- [ ] **Step 3: Validate the real gate and manifest**

Require gate `passed=true`, exact 15 speeches per agent in all three tasks,
selector calls zero, and every manifest hash correct. If any check fails,
preserve the failed artifacts with a `failed-<timestamp>` suffix and do not
label the pilot complete.

- [ ] **Step 4: Manually code the dynamic transcripts**

For every dynamic turn in IDs 1, 5, and 7, assign the same three observable
mechanism severities used for the baseline:

- information not disclosed;
- disclosed information ignored;
- correct evidence misinterpreted.

Write
`reports/HiddenBench_动态机制逐发言编码_ID1_ID5_ID7_2026-07-29.csv`
with exactly 180 turn rows and a matching Markdown interpretation. Do not
copy baseline labels. Include source message IDs and representative quotes.

- [ ] **Step 5: Finalize the paired report**

Replace each `manual review: pending` section with the reviewed dynamic
finding, while retaining the original frozen baseline finding. State whether
wrong consensus was prevented, delayed, unchanged, or changed to another
wrong answer.

- [ ] **Step 6: Commit the audited real artifacts**

```powershell
git add artifacts/hiddenbench-dynamic-pilot-20260729* `
  reports/HiddenBench_动态机制逐发言编码_ID1_ID5_ID7_2026-07-29.csv `
  reports/HiddenBench_动态机制逐发言编码_ID1_ID5_ID7_2026-07-29.md
git commit -m "exp: record budget-matched HiddenBench dynamic pilot"
```

### Task 9: Final verification and handoff

**Files:**
- Review all files changed since design commit `5cbfb6e`.

- [ ] **Step 1: Run all automated verification**

```powershell
python -m pytest -q
python -m compileall -q src tests
git diff --check 5cbfb6e..HEAD
git status --short
```

- [ ] **Step 2: Run the requirement audit**

Create a checklist showing evidence for:

- frozen hash validation before provider creation;
- exact IDs 1, 5, 7;
- same task assignments;
- model/temperature/thinking match;
- 60 speeches and 15 per agent;
- zero selector model calls;
- no early stop;
- complete score trace;
- token diagnostic;
- manual dynamic transcript review;
- no superiority claim.

- [ ] **Step 3: Review generated artifacts**

Confirm JSONL files parse, Markdown is UTF-8, trace has 180 lines, gate passes,
and every manifest path is relative and hash-correct.

- [ ] **Step 4: Prepare merge handoff**

Report branch, commits, test count, API request count, result summary, and any
remaining provider-drift limitation. Do not merge or push unless the user
requests it.
