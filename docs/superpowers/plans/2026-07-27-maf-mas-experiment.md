# MAF Multi-Agent Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible three-agent experiment that compares independent concurrent, sequential round-robin, and deterministic dynamic-speaker orchestration while producing uniform JSONL traces and metrics.

**Architecture:** Keep domain objects, metrics, selection policy, logging, and experiment semantics independent of Microsoft Agent Framework. Add a thin MAF adapter for real agents and use a deterministic offline provider for the default test and demonstration path.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 8, Microsoft Agent Framework 1.12, Microsoft Agent Framework OpenAI provider, JSONL.

## Global Constraints

- The default test suite and offline experiment require no network or API key.
- Pin `agent-framework>=1.12.1,<2` and `agent-framework-openai>=1.12.1,<2`.
- Read model credentials only from `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_CHAT_COMPLETION_MODEL`.
- Never serialize an API key, authorization header, or complete environment mapping.
- Use three agents, three round-robin rounds, nine dynamic turns, ten built-in multiple-choice questions, and a default seed of `20260727`.
- Dynamic score is `0.45 * disagreement + 0.30 * waiting + 0.25 * uncertainty`.
- Equal dynamic scores are resolved by ascending agent ID.
- Tests must observe the expected failure before production code is added.

---

## File Map

- `pyproject.toml`: package metadata, dependencies, pytest and CLI configuration.
- `.gitignore`: local environments, caches, generated logs and secrets.
- `README.md`: installation, offline run, real-model run and output explanation.
- `src/mas_experiment/domain.py`: validated domain records and provider protocol.
- `src/mas_experiment/datasets.py`: ten deterministic questions and three agent roles.
- `src/mas_experiment/voting.py`: final-answer selection and tie handling.
- `src/mas_experiment/metrics.py`: experiment metrics.
- `src/mas_experiment/selectors.py`: deterministic three-factor speaker selector.
- `src/mas_experiment/providers.py`: offline provider and OpenAI-compatible configuration.
- `src/mas_experiment/traces.py`: secret-safe JSONL serialization.
- `src/mas_experiment/orchestrations.py`: framework-independent experiment semantics.
- `src/mas_experiment/maf_adapter.py`: MAF imports, clients, agents and workflow smoke paths.
- `src/mas_experiment/cli.py`: command-line entry point and batch runner.
- `tests/`: focused unit and integration tests.

---

### Task 1: Project foundation and domain contracts

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/mas_experiment/__init__.py`
- Create: `src/mas_experiment/domain.py`
- Create: `src/mas_experiment/datasets.py`
- Test: `tests/test_domain.py`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Produces: `Question`, `AgentRole`, `AgentResponse`, `Message`, `SelectionScore`, `ExperimentResult`, `ModelProvider.generate()`, `QUESTIONS`, and `AGENT_ROLES`.

- [ ] **Step 1: Write failing validation and dataset tests**

```python
def test_response_rejects_confidence_outside_unit_interval():
    with pytest.raises(ValidationError):
        AgentResponse(
            response_id="r1", agent_id="agent-a", round_index=0,
            answer="A", confidence=1.1, reasoning="x",
            raw_text='{"answer":"A"}', changed_from_previous=False,
        )

def test_dataset_has_ten_answerable_questions():
    assert len(QUESTIONS) == 10
    assert all(q.correct_answer in q.options for q in QUESTIONS)
    assert [r.agent_id for r in AGENT_ROLES] == ["agent-a", "agent-b", "agent-c"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_domain.py tests/test_datasets.py -v`

Expected: collection fails because `mas_experiment.domain` and `mas_experiment.datasets` do not exist.

- [ ] **Step 3: Add package configuration and validated records**

Use Pydantic frozen models. Define:

```python
class Question(BaseModel):
    model_config = ConfigDict(frozen=True)
    question_id: str
    prompt: str
    options: dict[str, str]
    correct_answer: str

class AgentResponse(BaseModel):
    response_id: str
    agent_id: str
    round_index: int = Field(ge=0)
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    raw_text: str
    changed_from_previous: bool

class ModelProvider(Protocol):
    async def generate(
        self, *, question: Question, role: AgentRole, round_index: int,
        visible_messages: tuple[Message, ...], seed: int,
    ) -> AgentResponse:
        raise NotImplementedError
```

Create ten short questions covering arithmetic, logic and common knowledge. Each question must have exactly four options `A` through `D`. Create three roles: skeptical analyst, evidence checker and alternative-solution explorer.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_domain.py tests/test_datasets.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml .gitignore src/mas_experiment tests/test_domain.py tests/test_datasets.py
git commit -m "feat: add experiment domain and dataset"
```

---

### Task 2: Voting and metrics

**Files:**
- Create: `src/mas_experiment/voting.py`
- Create: `src/mas_experiment/metrics.py`
- Test: `tests/test_voting.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Question`, `AgentResponse`.
- Produces: `VoteResult`, `majority_vote(question, responses)`, and `calculate_metrics(question, responses, final_answer, speaker_counts)`.

- [ ] **Step 1: Write failing voting and metric tests**

```python
def test_majority_vote_uses_question_order_for_tie():
    result = majority_vote(question, [response("B"), response("A")])
    assert result.answer == "A"
    assert result.tie_break is True

def test_wrong_consensus_requires_unanimous_incorrect_answer():
    metrics = calculate_metrics(
        question=question_with_answer("A"),
        responses=[response("B", "a"), response("B", "b"), response("B", "c")],
        final_answer="B",
        speaker_counts={"a": 1, "b": 1, "c": 1},
    )
    assert metrics.wrong_consensus is True
    assert metrics.consensus_rate == 1.0

def test_normalized_entropy_is_one_for_uniform_four_way_split():
    responses = [response("A", "a"), response("B", "b"),
                 response("C", "c"), response("D", "d")]
    metrics = calculate_metrics(
        question=question_with_answer("A"),
        responses=responses,
        final_answer="A",
        speaker_counts={"a": 1, "b": 1, "c": 1, "d": 1},
    )
    assert metrics.answer_entropy == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_voting.py tests/test_metrics.py -v`

Expected: imports fail because voting and metrics modules do not exist.

- [ ] **Step 3: Implement deterministic voting and formulas**

Implement majority vote with `Counter`, valid-option filtering and question-order tie breaking. Raise `NoValidAnswerError` when no valid answers remain.

Metric formulas:

```python
consensus_rate = max(answer_counts.values()) / sum(answer_counts.values())
pairwise_disagreement = disagreeing_pairs / total_pairs
flip_rate = changed_transitions / comparable_transitions
answer_entropy = -sum(p * log(p) for p in probabilities) / log(option_count)
speaker_share = {agent: count / total_speeches for agent, count in counts.items()}
```

For final-state metrics, use each agent's last valid response. Use the complete per-agent trajectory only for `flip_rate`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_voting.py tests/test_metrics.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mas_experiment/voting.py src/mas_experiment/metrics.py tests/test_voting.py tests/test_metrics.py
git commit -m "feat: add deterministic voting and metrics"
```

---

### Task 3: Three-factor dynamic speaker selection

**Files:**
- Create: `src/mas_experiment/selectors.py`
- Test: `tests/test_selectors.py`

**Interfaces:**
- Consumes: agent IDs, previous responses, last-spoken steps and current step.
- Produces: `score_candidates(agent_ids, latest_responses, last_spoken_steps, current_step) -> tuple[SelectionScore, ...]` and `select_next_speaker(agent_ids, latest_responses, last_spoken_steps, current_step) -> SelectionScore`.

- [ ] **Step 1: Write failing selector tests**

```python
def test_unseen_agents_start_with_maximum_score():
    scores = score_candidates(
        agent_ids=("agent-a", "agent-b"), latest_responses={},
        last_spoken_steps={}, current_step=0,
    )
    assert scores[0].total == pytest.approx(1.0)

def test_selector_prefers_disagreement_when_waiting_is_equal():
    chosen = select_next_speaker(
        agent_ids=("agent-a", "agent-b", "agent-c"),
        latest_responses={
            "agent-a": response("A", confidence=.8),
            "agent-b": response("A", confidence=.8),
            "agent-c": response("B", confidence=.8),
        },
        last_spoken_steps={"agent-a": 0, "agent-b": 0, "agent-c": 0},
        current_step=1,
    )
    assert chosen.agent_id == "agent-c"

def test_equal_scores_use_ascending_agent_id():
    chosen = select_next_speaker(
        agent_ids=("agent-b", "agent-a"),
        latest_responses={},
        last_spoken_steps={},
        current_step=0,
    )
    assert chosen.agent_id == "agent-a"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_selectors.py -v`

Expected: module import fails.

- [ ] **Step 3: Implement selector**

Compute the current majority from each agent's latest valid answer. For an unseen agent use `1.0` for every component. Normalize waiting by the largest current waiting value, with a denominator floor of `1`. Return scores sorted by descending total and ascending agent ID.

```python
total = 0.45 * disagreement + 0.30 * waiting + 0.25 * (1.0 - confidence)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_selectors.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mas_experiment/selectors.py tests/test_selectors.py
git commit -m "feat: add dynamic speaker selector"
```

---

### Task 4: Deterministic provider and secret-safe traces

**Files:**
- Create: `src/mas_experiment/providers.py`
- Create: `src/mas_experiment/traces.py`
- Test: `tests/test_providers.py`
- Test: `tests/test_traces.py`

**Interfaces:**
- Consumes: domain records.
- Produces: `DeterministicProvider`, `OpenAICompatibleSettings.from_env()`, `append_result(path, result)`, and `read_results(path)`.

- [ ] **Step 1: Write failing determinism and redaction tests**

```python
@pytest.mark.asyncio
async def test_offline_provider_is_deterministic():
    role = AgentRole(agent_id="agent-a", name="Analyst", system_prompt="Check logic.")
    first = await provider.generate(
        question=QUESTIONS[0], role=role, round_index=0,
        visible_messages=(), seed=20260727,
    )
    second = await provider.generate(
        question=QUESTIONS[0], role=role, round_index=0,
        visible_messages=(), seed=20260727,
    )
    assert first.model_dump(exclude={"response_id"}) == second.model_dump(exclude={"response_id"})

def test_settings_require_key_model_and_endpoint(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        OpenAICompatibleSettings.from_env()

def test_trace_does_not_contain_secret(tmp_path):
    result = result_with_metadata({"api_key": "secret-value"})
    append_result(tmp_path / "trace.jsonl", result)
    assert "secret-value" not in (tmp_path / "trace.jsonl").read_text("utf-8")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_providers.py tests/test_traces.py -v`

Expected: module imports fail.

- [ ] **Step 3: Implement deterministic generation, env settings and trace sanitization**

The deterministic provider hashes `seed|question_id|agent_id|round_index|visible_message_ids` with SHA-256, maps the first byte to one of the question options, and maps the second byte to confidence in `[0.50, 0.95]`. Use stable hash output, not Python's randomized `hash()`.

Environment mapping:

```python
OpenAICompatibleSettings(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
    model=os.environ["OPENAI_CHAT_COMPLETION_MODEL"],
)
```

Before serialization recursively replace values of keys matching `api_key`, `authorization`, `token`, or `secret` with `"[REDACTED]"`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_providers.py tests/test_traces.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mas_experiment/providers.py src/mas_experiment/traces.py tests/test_providers.py tests/test_traces.py
git commit -m "feat: add deterministic provider and safe traces"
```

---

### Task 5: Framework-independent orchestration semantics

**Files:**
- Create: `src/mas_experiment/orchestrations.py`
- Test: `tests/test_orchestrations.py`

**Interfaces:**
- Consumes: `Question`, roles, `ModelProvider`, selector, voting and metrics.
- Produces: `run_concurrent(question, roles, provider, seed)`, `run_round_robin(question, roles, provider, rounds, seed)`, and `run_dynamic(question, roles, provider, turns, seed)`, each returning `ExperimentResult`.

- [ ] **Step 1: Write failing visibility and result-shape tests**

```python
@pytest.mark.asyncio
async def test_concurrent_agents_see_no_peer_messages():
    result = await run_concurrent(question, roles, recording_provider, seed=1)
    assert all(message.visible_history_ids == () for message in result.messages)

@pytest.mark.asyncio
async def test_round_robin_visibility_grows_after_each_turn():
    result = await run_round_robin(question, roles, recording_provider, rounds=1, seed=1)
    assert [len(m.visible_history_ids) for m in result.messages] == [0, 1, 2]

@pytest.mark.asyncio
async def test_dynamic_has_nine_selected_turns_and_scores():
    result = await run_dynamic(question, roles, deterministic_provider, turns=9, seed=1)
    assert len(result.messages) == 9
    assert len(result.selection_scores) == 9
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_orchestrations.py -v`

Expected: module import fails.

- [ ] **Step 3: Implement three orchestration loops**

- Concurrent: call all three providers with the same empty visible history using `asyncio.gather`.
- Round robin: iterate rounds then roles; snapshot the current public history before each call.
- Dynamic: calculate all candidate scores, select one speaker, call it with current public history, append immediately, and repeat for nine turns.

Each function must use `build_result(question, mode, roles, messages, responses, selection_scores, seed, errors)` for final vote, metrics, version metadata and error collection.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_orchestrations.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mas_experiment/orchestrations.py tests/test_orchestrations.py
git commit -m "feat: add three experiment orchestrations"
```

---

### Task 6: MAF adapter, CLI, documentation and acceptance run

**Files:**
- Create: `src/mas_experiment/maf_adapter.py`
- Create: `src/mas_experiment/cli.py`
- Create: `tests/test_maf_adapter.py`
- Create: `tests/test_cli.py`
- Create: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: experiment core and environment settings.
- Produces: `create_maf_agents(settings, roles)`, `build_maf_concurrent(agents)`, `build_maf_group_chat(agents, selection_func)`, and CLI command `mas-experiment`.

- [ ] **Step 1: Write failing MAF import and CLI tests**

```python
def test_maf_adapter_imports_current_builder_api():
    from agent_framework.orchestrations import ConcurrentBuilder, GroupChatBuilder
    assert ConcurrentBuilder is not None
    assert GroupChatBuilder is not None

def test_cli_offline_run_creates_thirty_records(tmp_path):
    result = runner.invoke(app, ["run", "--provider", "offline",
                                 "--output", str(tmp_path / "results.jsonl")])
    assert result.exit_code == 0
    assert len(read_results(tmp_path / "results.jsonl")) == 30
```

- [ ] **Step 2: Install declared dependencies and verify RED**

Run: `python -m pip install -e ".[dev,maf]"`

Run: `python -m pytest tests/test_maf_adapter.py tests/test_cli.py -v`

Expected: tests fail because `maf_adapter.py` and `cli.py` do not exist.

- [ ] **Step 3: Implement the MAF adapter**

Use current provider imports:

```python
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from agent_framework.orchestrations import ConcurrentBuilder, GroupChatBuilder
```

Create the provider client with:

```python
client = OpenAIChatCompletionClient(
    model=settings.model,
    api_key=settings.api_key,
    base_url=settings.base_url,
)
```

Create one `Agent` per role. Use `ConcurrentBuilder(participants=agents).build()` for the MAF concurrent smoke path. Use the following termination and selection functions for the group-chat smoke paths:

```python
termination = lambda messages: sum(m.role == "assistant" for m in messages) >= 9
round_robin = lambda state: list(state.participants)[
    state.current_round % len(state.participants)
]
workflow = GroupChatBuilder(
    participants=agents,
    termination_condition=termination,
    selection_func=round_robin,
).build()
```

For dynamic selection, adapt `GroupChatState` into the core selector inputs and return the selected participant name.

The research batch continues to use the framework-independent loops so that prompts, visible histories and metrics remain exactly controlled. The MAF adapter demonstrates equivalent MAF construction and provides the real-model execution path.

- [ ] **Step 4: Implement CLI and README**

Commands:

```text
mas-experiment run --provider offline --output artifacts/results.jsonl
mas-experiment run --provider openai-compatible --mode concurrent --limit 1
mas-experiment summarize artifacts/results.jsonl
mas-experiment maf-smoke --mode concurrent
mas-experiment maf-smoke --mode group-chat
```

`run` defaults to all ten questions and all three modes. `summarize` prints record count and mean accuracy, consensus, disagreement and entropy grouped by mode.

README must explain that the offline provider validates mechanics only, not scientific effectiveness, and must document the three environment variables without sample secret values.

- [ ] **Step 5: Run targeted tests**

Run: `python -m pytest tests/test_maf_adapter.py tests/test_cli.py -v`

Expected: all tests pass.

- [ ] **Step 6: Run the full suite and offline acceptance experiment**

Run:

```powershell
python -m pytest -v
mas-experiment run --provider offline --output artifacts/results.jsonl
mas-experiment summarize artifacts/results.jsonl
```

Expected:

- pytest reports zero failures;
- the run command reports 30 completed records;
- `artifacts/results.jsonl` contains 30 lines;
- summary contains rows for `concurrent`, `round_robin`, and `dynamic`.

- [ ] **Step 7: Verify deterministic replay**

Run the offline command twice with the same seed into two separate files, then compare normalized JSON records after excluding `run_id` and timestamps.

Expected: normalized records are identical.

- [ ] **Step 8: Commit**

```powershell
git add pyproject.toml README.md src/mas_experiment/maf_adapter.py src/mas_experiment/cli.py tests/test_maf_adapter.py tests/test_cli.py
git commit -m "feat: add MAF adapter and experiment CLI"
```

---

## Final Review Checklist

- [ ] Every production function was introduced after a failing test.
- [ ] All tests pass in a fresh full-suite run.
- [ ] Offline run produces exactly 30 JSONL records.
- [ ] Logs contain prompts and visible message IDs but no secrets.
- [ ] Dynamic turns include all candidate scores and the chosen speaker.
- [ ] MAF 1.12 imports and both workflow builders are exercised.
- [ ] README distinguishes offline mechanics from scientific evidence.
- [ ] `git diff --check` reports no whitespace errors.
