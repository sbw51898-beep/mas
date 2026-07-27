# DeepSeek Formal Multi-Agent Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing MAF experiment so one hidden-information supplier question can run through three equal-budget orchestration modes with DeepSeek V4 Flash, probability beliefs, auditable metrics, and a safe single-run report.

**Architecture:** Keep the experiment semantics independent of Microsoft Agent Framework. Add probability validation and belief mathematics as pure functions, attach private context to the question, update all orchestrations to a shared three-call initialization plus six budget-matched calls, and keep the MAF provider as a thin DeepSeek-compatible transport adapter.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 8, Microsoft Agent Framework Core 1.12, Agent Framework OpenAI provider 1.11, OpenAI Python SDK 2.48, Typer, JSONL.

## Global Constraints

- Use the approved design in `docs/superpowers/specs/2026-07-27-deepseek-formal-pilot-design.md`.
- Use `https://api.deepseek.com` and model `deepseek-v4-flash`.
- Pass `extra_body={"thinking": {"type": "disabled"}}` on every real model request.
- Use temperature `0`, non-streaming requests, and structured JSON output.
- Run exactly 9 valid discussion calls per mode: 3 independent initial calls plus 6 mode-specific calls.
- A format-repair request is logged as an extra API request but does not count as a discussion call.
- Never expose the correct answer to prompts, speaker selection, or runtime belief calculation.
- Never serialize API keys, authorization headers, tokens, secrets, or the complete environment.
- Preserve deterministic offline execution and the existing no-network test suite.
- Use TDD: observe each new test fail before adding production behavior.
- Do not treat one real question as evidence that one orchestration is superior.

---

## File Map

- `src/mas_experiment/domain.py`: probability-aware records, private task context, provider metadata, and expanded metrics.
- `src/mas_experiment/beliefs.py`: probability validation, pooling, Jensen-Shannon divergence, Brier score, `b_i`, and proxy-state calculations.
- `src/mas_experiment/datasets.py`: the approved hidden-information supplier task and its three specialist roles.
- `src/mas_experiment/providers.py`: deterministic probability vectors and DeepSeek-specific settings.
- `src/mas_experiment/selectors.py`: probability-disagreement dynamic score.
- `src/mas_experiment/metrics.py`: three-layer final-state and trajectory metrics.
- `src/mas_experiment/orchestrations.py`: common independent initialization and three equal-budget modes.
- `src/mas_experiment/maf_adapter.py`: structured DeepSeek request, non-thinking toggle, parsing, one repair attempt, and usage metadata.
- `src/mas_experiment/cli.py`: formal-pilot command, connectivity probe, audit, and summary.
- `src/mas_experiment/reporting.py`: safe single-pilot audit report generation.
- `tests/`: focused unit, orchestration, adapter, CLI, and redaction tests.
- `README.md`: formal pilot setup and conclusion boundaries.

---

### Task 1: Probability belief contract

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Create: `src/mas_experiment/beliefs.py`
- Modify: `src/mas_experiment/providers.py`
- Modify: `tests/test_domain.py`
- Modify: `tests/test_providers.py`
- Create: `tests/test_beliefs.py`
- Modify: response factories in `tests/test_metrics.py`, `tests/test_orchestrations.py`, `tests/test_selectors.py`, and `tests/test_traces.py`

**Interfaces:**
- Produces: `AgentResponse.probabilities`, computed `AgentResponse.confidence`, `normalize_probabilities(question, values)`, `validate_answer_matches_probabilities(question, answer, probabilities)`, and deterministic probability output.
- Consumes: existing `Question`, `AgentResponse`, and `DeterministicProvider`.

- [ ] **Step 1: Write failing probability validation tests**

```python
def test_probabilities_are_normalized_within_rounding_tolerance():
    result = normalize_probabilities(
        QUESTION, {"A": 0.50, "B": 0.30, "C": 0.19, "D": 0.009}
    )
    assert sum(result.values()) == pytest.approx(1.0)
    assert set(result) == set(QUESTION.options)


def test_probabilities_reject_missing_option():
    with pytest.raises(ProbabilityValidationError, match="exactly"):
        normalize_probabilities(
            QUESTION, {"A": 0.5, "B": 0.3, "C": 0.2}
        )


def test_probabilities_reject_large_sum_error():
    with pytest.raises(ProbabilityValidationError, match="sum"):
        normalize_probabilities(
            QUESTION, {"A": 0.7, "B": 0.3, "C": 0.2, "D": 0.1}
        )


def test_answer_must_match_highest_probability():
    with pytest.raises(ProbabilityValidationError, match="highest"):
        validate_answer_matches_probabilities(
            QUESTION,
            "A",
            {"A": 0.1, "B": 0.7, "C": 0.1, "D": 0.1},
        )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_beliefs.py tests/test_domain.py -v
```

Expected: collection fails because `mas_experiment.beliefs` and `AgentResponse.probabilities` do not exist.

- [ ] **Step 3: Implement probability normalization**

Create:

```python
class ProbabilityValidationError(ValueError):
    pass


def normalize_probabilities(
    question: Question,
    values: Mapping[str, float],
    *,
    tolerance: float = 0.01,
) -> dict[str, float]:
    if set(values) != set(question.options):
        raise ProbabilityValidationError(
            "probabilities must contain exactly the question options"
        )
    parsed = {key: float(values[key]) for key in question.options}
    if any(not math.isfinite(value) or value < 0 or value > 1
           for value in parsed.values()):
        raise ProbabilityValidationError(
            "probabilities must be finite values from 0 to 1"
        )
    total = sum(parsed.values())
    if abs(total - 1.0) > tolerance or total <= 0:
        raise ProbabilityValidationError(
            "probabilities must sum to 1 within tolerance 0.01"
        )
    return {key: value / total for key, value in parsed.items()}


def validate_answer_matches_probabilities(
    question: Question,
    answer: str,
    probabilities: Mapping[str, float],
) -> tuple[str, bool]:
    maximum = max(probabilities.values())
    winners = [
        key for key in question.options
        if math.isclose(probabilities[key], maximum, abs_tol=1e-12)
    ]
    expected = winners[0]
    if answer != expected:
        raise ProbabilityValidationError(
            "answer must equal the highest-probability option"
        )
    return expected, len(winners) > 1
```

Change `AgentResponse` to store a validated `probabilities: dict[str, float]`, remove the writable `confidence` field, and expose:

```python
@computed_field
@property
def confidence(self) -> float:
    return max(self.probabilities.values())
```

Add `answer_tie_break: bool = False` and `provider_metadata: Mapping[str, Any] = Field(default_factory=dict)`.

- [ ] **Step 4: Update deterministic and test providers**

Derive four positive weights from the existing SHA256 digest, normalize them, select the highest option in question order, and serialize `probabilities` instead of an independent confidence. Update every test response factory to pass a probability map consistent with its answer.

- [ ] **Step 5: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_beliefs.py tests/test_domain.py tests/test_providers.py -v
python -m pytest -q
```

Expected: all tests pass and no test constructs an independent confidence field.

- [ ] **Step 6: Commit**

```powershell
git add src/mas_experiment/domain.py src/mas_experiment/beliefs.py src/mas_experiment/providers.py tests
git commit -m "feat: add probability belief contract"
```

---

### Task 2: Hidden-information supplier task

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Modify: `src/mas_experiment/datasets.py`
- Modify: `tests/test_datasets.py`
- Modify: `tests/test_maf_adapter.py`

**Interfaces:**
- Produces: `Question.public_context`, `Question.private_contexts`, `FORMAL_PILOT_QUESTION`, and supplier specialist `FORMAL_PILOT_ROLES`.
- Consumes: probability-aware `Question` and `AgentRole`.

- [ ] **Step 1: Write failing hidden-profile tests**

```python
def test_formal_pilot_has_one_private_dimension_per_agent():
    assert set(FORMAL_PILOT_QUESTION.private_contexts) == {
        "agent-a", "agent-b", "agent-c"
    }
    assert "95" in FORMAL_PILOT_QUESTION.private_contexts["agent-a"]
    assert "95" in FORMAL_PILOT_QUESTION.private_contexts["agent-b"]
    assert "100" in FORMAL_PILOT_QUESTION.private_contexts["agent-c"]


def test_formal_pilot_answer_requires_combining_private_dimensions():
    assert FORMAL_PILOT_QUESTION.correct_answer == "C"
    totals = supplier_weighted_totals()
    assert totals == {
        "A": pytest.approx(76.00),
        "B": pytest.approx(78.25),
        "C": pytest.approx(86.25),
        "D": pytest.approx(75.50),
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_datasets.py -v
```

Expected: imports or attributes fail because the formal pilot records do not exist.

- [ ] **Step 3: Add private context to the domain**

Add immutable-by-copy fields:

```python
public_context: str = ""
private_contexts: dict[str, str] = Field(default_factory=dict)

def private_context_for(self, agent_id: str) -> str:
    return self.private_contexts.get(agent_id, "")
```

The prompt builder must call `question.private_context_for(role.agent_id)` and never concatenate the entire mapping.

- [ ] **Step 4: Add the approved supplier task and roles**

Use the exact data from the design:

```python
SUPPLIER_WEIGHTS = {"reliability": 0.40, "security": 0.35, "cost": 0.25}
SUPPLIER_SCORES = {
    "reliability": {"A": 95, "B": 75, "C": 85, "D": 65},
    "security": {"A": 55, "B": 95, "C": 85, "D": 70},
    "cost": {"A": 75, "B": 60, "C": 90, "D": 100},
}
```

Create public text with weights only, private role text with exactly one score row, options A through D, and correct answer C.

- [ ] **Step 5: Verify prompt isolation**

Add a fake-agent test that captures the prompt for agent-a and asserts it contains the reliability values but does not contain the security row or cost row.

Run:

```powershell
python -m pytest tests/test_datasets.py tests/test_maf_adapter.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/mas_experiment/domain.py src/mas_experiment/datasets.py tests/test_datasets.py tests/test_maf_adapter.py
git commit -m "feat: add hidden-information pilot task"
```

---

### Task 3: Three-layer metrics and belief proxies

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Modify: `src/mas_experiment/beliefs.py`
- Modify: `src/mas_experiment/voting.py`
- Modify: `src/mas_experiment/metrics.py`
- Modify: `tests/test_beliefs.py`
- Modify: `tests/test_metrics.py`
- Modify: `tests/test_voting.py`

**Interfaces:**
- Produces: `pool_probabilities`, `generalized_js_disagreement`, `brier_score`, `belief_state`, expanded `ExperimentMetrics`, and primary pooled answer.
- Consumes: each Agent's final probability vector and complete answer trajectory.

- [ ] **Step 1: Write failing metric tests**

```python
def test_majority_share_is_not_named_consensus():
    metrics = calculate_metrics(
        question=QUESTION,
        responses=(
            response("A", "a", {"A": .7, "B": .1, "C": .1, "D": .1}),
            response("A", "b", {"A": .6, "B": .2, "C": .1, "D": .1}),
            response("B", "c", {"A": .2, "B": .6, "C": .1, "D": .1}),
        ),
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )
    assert metrics.majority_share == pytest.approx(2 / 3)
    assert metrics.unanimity is False


def test_three_agents_can_reach_unit_answer_entropy():
    metrics = calculate_metrics(
        question=QUESTION,
        responses=(
            response("A", "a", peaked("A")),
            response("B", "b", peaked("B")),
            response("C", "c", peaked("C")),
        ),
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )
    assert metrics.answer_entropy == pytest.approx(1.0)


def test_runtime_and_evaluation_beliefs_use_different_references():
    probabilities = {
        "a": {"A": .6, "B": .2, "C": .1, "D": .1},
        "b": {"A": .5, "B": .2, "C": .2, "D": .1},
        "c": {"A": .4, "B": .2, "C": .3, "D": .1},
    }
    runtime = belief_state(probabilities, reference_option="A")
    evaluation = belief_state(probabilities, reference_option="C")
    assert runtime.reference_option == "A"
    assert evaluation.reference_option == "C"
    assert runtime.mean_b > evaluation.mean_b
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_beliefs.py tests/test_metrics.py tests/test_voting.py -v
```

Expected: failures for missing expanded metrics and pooling functions.

- [ ] **Step 3: Implement pooling and process metrics**

Implement:

```python
def pool_probabilities(
    probabilities_by_agent: Mapping[str, Mapping[str, float]],
    option_order: Sequence[str],
) -> tuple[dict[str, float], str, bool]:
    pooled = {
        option: mean(values[option] for values in probabilities_by_agent.values())
        for option in option_order
    }
    maximum = max(pooled.values())
    winners = [
        option for option in option_order
        if math.isclose(pooled[option], maximum, abs_tol=1e-12)
    ]
    return pooled, winners[0], len(winners) > 1
```

Use natural logarithms consistently. Normalize answer entropy and generalized Jensen-Shannon disagreement by `log(min(K,N))`. Compute multiclass Brier as the unscaled sum of squared errors.

- [ ] **Step 4: Implement proxy state**

Add immutable `BeliefState` with:

```python
reference_option: str
beliefs: dict[str, float]
mean_b: float
order_parameter_r: float
temperature_proxy: float
entropy_proxy: float
disorder_proxy: float
```

Compute `theta_i=(pi/2)b_i`, population standard deviation, five fixed bins on `[-1,1]`, entropy normalized by `log(min(5,N))`, and `F_proxy=(1-R)+T_proxy*H_proxy`.

- [ ] **Step 5: Expand final metrics**

Replace `consensus_rate` with `majority_share`; add `unanimity`, `js_disagreement`, `group_brier`, `pooled_answer`, `majority_answer`, `runtime_belief_state`, and `evaluation_belief_state`. `accuracy` uses `pooled_answer`.

- [ ] **Step 6: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_beliefs.py tests/test_metrics.py tests/test_voting.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/domain.py src/mas_experiment/beliefs.py src/mas_experiment/voting.py src/mas_experiment/metrics.py tests
git commit -m "feat: add belief and governance metrics"
```

---

### Task 4: Equal-budget orchestration

**Files:**
- Modify: `src/mas_experiment/selectors.py`
- Modify: `src/mas_experiment/orchestrations.py`
- Modify: `tests/test_selectors.py`
- Modify: `tests/test_orchestrations.py`

**Interfaces:**
- Produces: `run_independent`, equal-budget `run_round_robin`, equal-budget `run_dynamic`, shared three-Agent initialization, and probability-based dynamic scores.
- Consumes: private question context, probability responses, and all previous public or self-only messages allowed by mode.

- [ ] **Step 1: Write failing visibility and budget tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("runner", [run_independent, run_round_robin, run_dynamic])
async def test_every_mode_uses_exactly_nine_discussion_calls(runner):
    provider = RecordingProvider()
    result = await runner(
        FORMAL_PILOT_QUESTION, FORMAL_PILOT_ROLES, provider, seed=20260727
    )
    assert len(result.responses) == 9
    assert provider.call_count == 9


@pytest.mark.asyncio
async def test_initial_three_calls_are_mutually_invisible():
    provider = RecordingProvider()
    await run_dynamic(
        FORMAL_PILOT_QUESTION, FORMAL_PILOT_ROLES, provider, seed=20260727
    )
    assert provider.visible_histories[:3] == [(), (), ()]


@pytest.mark.asyncio
async def test_independent_mode_sees_only_same_agent_history():
    provider = RecordingProvider()
    await run_independent(
        FORMAL_PILOT_QUESTION, FORMAL_PILOT_ROLES, provider, seed=20260727
    )
    for call in provider.calls[3:]:
        assert all(message.speaker == call.agent_id
                   for message in call.visible_messages)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_orchestrations.py tests/test_selectors.py -v
```

Expected: `run_independent` is missing and current call counts/visibility differ.

- [ ] **Step 3: Add common independent initialization**

Implement an internal helper that concurrently obtains one response from each role with empty visible history. For discussion modes, publish the three completed initial messages only after all three requests finish. For independent mode, retain each message in a separate self-history.

- [ ] **Step 4: Implement equal-budget runners**

- `run_independent`: initial 3 calls, then two self-reflection rounds for A/B/C, total 9.
- `run_round_robin`: initial 3 calls, then A/B/C twice with full public history, total 9.
- `run_dynamic`: initial 3 calls, then 6 selected public turns, total 9.

Rename persisted mode `concurrent` to `independent` for the formal pilot while retaining the old CLI alias only as a compatibility warning.

- [ ] **Step 5: Replace discrete disagreement**

For each candidate, calculate normalized Jensen-Shannon divergence between its latest probability vector and the current group mean. Keep waiting and uncertainty formulas unchanged:

```python
total = 0.45 * disagreement + 0.30 * waiting + 0.25 * uncertainty
```

Log all three candidate scores on each of the six dynamic selection steps.

- [ ] **Step 6: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_orchestrations.py tests/test_selectors.py -v
python -m pytest -q
```

Expected: all tests pass; each mode records 9 responses; dynamic records 18 candidate score rows after initialization.

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/selectors.py src/mas_experiment/orchestrations.py tests/test_selectors.py tests/test_orchestrations.py
git commit -m "feat: equalize multi-agent experiment budgets"
```

---

### Task 5: DeepSeek V4 structured transport

**Files:**
- Modify: `src/mas_experiment/providers.py`
- Modify: `src/mas_experiment/maf_adapter.py`
- Modify: `tests/test_providers.py`
- Modify: `tests/test_maf_adapter.py`
- Modify: `tests/test_traces.py`

**Interfaces:**
- Produces: `DeepSeekSettings`, DeepSeek-compatible `MAFModelProvider.generate`, one repair attempt, request metadata, and explicit non-thinking transport options.
- Consumes: approved model settings, private Agent context, visible messages, and probability validators.

- [ ] **Step 1: Write failing DeepSeek request tests**

```python
@pytest.mark.asyncio
async def test_deepseek_request_disables_thinking_and_temperature_is_zero():
    fake = FakeAgent(
        '{"answer":"C","probabilities":{"A":0.1,"B":0.2,'
        '"C":0.6,"D":0.1},"reasoning":"combined evidence"}'
    )
    provider = MAFModelProvider({"agent-a": fake})
    await provider.generate(
        question=FORMAL_PILOT_QUESTION,
        role=FORMAL_PILOT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )
    assert fake.options["temperature"] == 0
    assert fake.options["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert fake.options["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_invalid_payload_gets_one_repair_request():
    fake = SequencedFakeAgent(
        ['not json',
         '{"answer":"C","probabilities":{"A":0.1,"B":0.2,'
         '"C":0.6,"D":0.1},"reasoning":"repaired"}']
    )
    provider = provider_for(fake)
    response = await provider.generate(
        question=FORMAL_PILOT_QUESTION,
        role=FORMAL_PILOT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )
    assert fake.call_count == 2
    assert response.provider_metadata["repair_requests"] == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_maf_adapter.py tests/test_providers.py tests/test_traces.py -v
```

Expected: fake-agent assertions fail because current calls do not pass DeepSeek options and only parse confidence.

- [ ] **Step 3: Add DeepSeek settings**

Validate:

```python
base_url: str = "https://api.deepseek.com"
model: str = "deepseek-v4-flash"
thinking: Literal["disabled"] = "disabled"
temperature: float = 0.0
```

Reject a model other than `deepseek-v4-flash` for the `formal-pilot` command. Continue to read the key from `OPENAI_API_KEY`; allow the URL and model environment variables but require their values to match the approved protocol.

- [ ] **Step 4: Send structured non-thinking requests**

Call:

```python
result = await agent.run(
    prompt,
    options={
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
    },
)
```

MAF 1.11 copies unknown `options` keys into the OpenAI Chat Completions request, so `extra_body` must be placed in `options`. Do not put it in `client_kwargs`; that mapping is expanded as arguments to MAF's internal response method and is not merged into the OpenAI request body.

The prompt must contain only public context, that Agent's private context, allowed visible history, and the exact JSON schema. It must not contain the correct answer.

- [ ] **Step 5: Parse, repair, and record metadata**

Parse the probability object with Task 1 validators. On the first validation failure, issue one repair prompt containing the invalid output and schema rules but no new task evidence. Record:

```python
{
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "thinking": "disabled",
    "temperature": 0,
    "repair_requests": 0 | 1,
    "usage": safe_usage_mapping,
    "request_id": request_id_if_available,
}
```

Do not include client objects, headers, credentials, or complete response objects.

- [ ] **Step 6: Verify recursive redaction**

Add a nested provider metadata fixture containing fake `api_key`, `authorization`, `token`, and `secret` fields. Serialize it and assert no fake value appears.

Run:

```powershell
python -m pytest tests/test_maf_adapter.py tests/test_providers.py tests/test_traces.py -v
python -m pytest -q
```

Expected: all tests pass with no network calls.

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/providers.py src/mas_experiment/maf_adapter.py tests/test_providers.py tests/test_maf_adapter.py tests/test_traces.py
git commit -m "feat: add DeepSeek structured model transport"
```

---

### Task 6: Formal pilot CLI and audit report

**Files:**
- Modify: `src/mas_experiment/cli.py`
- Create: `src/mas_experiment/reporting.py`
- Modify: `tests/test_cli.py`
- Create: `tests/test_reporting.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `mas-experiment formal-pilot`, connectivity probe, three-record JSONL output, and Markdown audit report.
- Consumes: formal task, formal roles, equal-budget orchestration functions, DeepSeek provider, and safe trace reader.

- [ ] **Step 1: Write failing CLI and report tests**

```python
def test_formal_pilot_writes_three_complete_mode_records(
    runner, monkeypatch, tmp_path
):
    monkeypatch.setattr(cli, "create_formal_provider", fake_provider_factory)
    output = tmp_path / "pilot.jsonl"
    result = runner.invoke(
        app, ["formal-pilot", "--output", str(output), "--skip-connectivity"]
    )
    assert result.exit_code == 0
    records = read_results(output)
    assert {item["mode"] for item in records} == {
        "independent", "round_robin", "dynamic"
    }
    assert all(len(item["responses"]) == 9 for item in records)


def test_report_separates_observations_from_research_claims(tmp_path):
    report = build_pilot_report(FIXTURE_RESULTS)
    assert "工程观察" in report
    assert "研究结论限制" in report
    assert "不能据此认定" in report
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_cli.py tests/test_reporting.py -v
```

Expected: command and reporting module do not exist.

- [ ] **Step 3: Implement the formal-pilot command**

The command must:

1. load and validate approved DeepSeek settings;
2. accept `--provider deepseek|offline`, defaulting to `deepseek`; offline mode must not read a key or make a connectivity request;
3. refuse to overwrite an existing output unless `--overwrite` is passed;
4. make one connectivity request unless `--skip-connectivity` is used by tests;
5. abort before the 27 discussion calls if connectivity or JSON validation fails;
6. run independent, round-robin, and dynamic modes against the one approved question;
7. append one JSONL record after each completed mode;
8. require exactly 9 valid responses per mode;
9. generate a sibling `.md` audit report;
10. print total real API requests, repairs, and output paths.

- [ ] **Step 4: Implement the report**

Include:

- experiment identity and exact DeepSeek configuration;
- per-mode validity and call counts;
- pooled answer, majority answer, accuracy, majority share, unanimity, wrong consensus, flips, JS disagreement, Brier, and speaker share;
- runtime and evaluation belief proxy summaries;
- private-information disclosure observations based on exact score tokens;
- a `MAST候选信号审计` section that separately reports:
  - FM-2.4 candidate: whether each specialist publicly disclosed its private score row;
  - FM-2.5 candidate: whether later responses numerically used score rows disclosed by other specialists;
  - FM-2.6 candidate: whether structured answer and maximum probability disagree, plus a manual-review note for reasoning-versus-answer semantics;
- API/format errors and repair counts;
- a fixed `研究结论限制` section stating that a single question cannot establish superiority, correlation, replication, or physical validity.

- [ ] **Step 5: Update README**

Document:

```powershell
$env:OPENAI_API_KEY="<set locally; do not paste into chat>"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_CHAT_COMPLETION_MODEL="deepseek-v4-flash"
mas-experiment formal-pilot --output artifacts/deepseek-formal-pilot.jsonl
```

Explain that the command performs one uncounted connectivity request followed by 27 discussion calls plus any logged repair requests.

- [ ] **Step 6: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_cli.py tests/test_reporting.py -v
python -m pytest -v
git diff --check
```

Expected: all tests pass and the worktree has no whitespace errors.

- [ ] **Step 7: Commit**

```powershell
git add src/mas_experiment/cli.py src/mas_experiment/reporting.py tests/test_cli.py tests/test_reporting.py README.md
git commit -m "feat: add auditable formal pilot command"
```

---

### Task 7: Offline acceptance and real DeepSeek pilot

**Files:**
- Generated and ignored: `artifacts/formal-pilot-offline.jsonl`
- Generated and ignored: `artifacts/formal-pilot-offline.md`
- Generated and ignored: `artifacts/deepseek-formal-pilot.jsonl`
- Generated and ignored: `artifacts/deepseek-formal-pilot.md`

**Interfaces:**
- Produces: final verification evidence and one real single-question audit.
- Consumes: completed CLI, locally configured DeepSeek credentials, and all tests.

- [ ] **Step 1: Run the complete local verification**

```powershell
python -m pytest -v
mas-experiment formal-pilot --provider offline --skip-connectivity --output artifacts/formal-pilot-offline.jsonl
git diff --check
git status -sb
```

Expected: all tests pass, three offline mode records exist, every mode has 9 valid responses, and generated artifacts remain ignored.

- [ ] **Step 2: Verify credential presence without printing it**

Run a check that prints only `SET` or `MISSING` for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_CHAT_COMPLETION_MODEL`. If the key is missing, stop and ask the user to configure it locally; never ask the user to paste it into chat.

- [ ] **Step 3: Run a connectivity probe**

Execute the formal command's connectivity path. Verify:

- returned content is valid JSON;
- recorded model is `deepseek-v4-flash`;
- request metadata states thinking disabled and temperature zero;
- no discussion output file has been created if the probe fails.

- [ ] **Step 4: Run the real pilot**

```powershell
mas-experiment formal-pilot --output artifacts/deepseek-formal-pilot.jsonl
```

Expected: one connectivity request, 27 valid discussion calls, three JSONL results, and one Markdown report. Extra repair requests are allowed only when explicitly counted.

- [ ] **Step 5: Audit secrets and completeness**

Search the generated files for the literal configured key only through a boolean comparison that never prints the key. Verify:

- no key match;
- no raw authorization header;
- three modes;
- nine valid responses per mode;
- initial visible histories empty;
- independent mode contains no peer-visible messages;
- dynamic mode has six selection steps and 18 candidate score rows.

- [ ] **Step 6: Review the single-run report**

Report:

- what each mode answered;
- whether any wrong consensus occurred;
- whether private score rows were disclosed and used;
- how probabilities and `b_i` changed;
- the exact request and repair counts;
- any engineering failure;
- the fixed conclusion that one run cannot establish mechanism superiority.

- [ ] **Step 7: Commit only source changes**

Do not commit ignored experiment outputs or credentials. If the source tree is already committed and clean, do not create an empty commit.

---

## Final Verification Checklist

- [ ] `python -m pytest -v` passes.
- [ ] Offline formal pilot creates three complete, equal-budget records.
- [ ] DeepSeek V4 Flash is called with thinking disabled and temperature zero.
- [ ] Real pilot completes one connectivity request plus 27 valid discussion calls.
- [ ] All repairs and actual API calls are counted.
- [ ] Generated JSONL and Markdown contain no credentials.
- [ ] Each response has a complete probability vector.
- [ ] Runtime `b_i` never uses the answer key.
- [ ] Evaluation `b_i` never enters prompts or selection.
- [ ] Every proxy metric retains the `_proxy` name.
- [ ] The report keeps engineering observations separate from research claims.
