# Shared Initial State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all three formal-pilot orchestration modes reuse one validated three-Agent initial snapshot so they begin from identical model outputs while retaining nine logical responses per mode.

**Architecture:** Introduce an immutable `InitialState` record and an explicit `prepare_initial_state` function. Runners accept the snapshot as an optional keyword argument, preserving current direct-call behavior, while the formal CLI prepares it once and passes it to all modes. Request reporting deduplicates shared response IDs so serialized copies count as twenty-seven logical slots but only twenty-one real discussion requests.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 8, asyncio, Typer, JSONL, Microsoft Agent Framework, DeepSeek V4 Flash.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-27-shared-initial-state-design.md`.
- Use test-driven development and observe every new test fail for the intended reason before adding production behavior.
- Make exactly three mutually invisible real initialization calls for the formal pilot.
- Make exactly six real follow-up calls per mode, eighteen total.
- Record exactly nine logical responses per mode, twenty-seven total.
- Count exactly twenty-one real formal-pilot discussion requests before format repairs.
- Preserve direct runner compatibility: a runner without `initial_state` still makes nine provider calls.
- Abort before creating JSONL or Markdown output if shared initialization is incomplete or invalid.
- Preserve the existing real-run artifacts; write the new run to `artifacts/deepseek-formal-pilot-shared-initial.*`.
- Never serialize credentials, authorization headers, client objects, or the complete environment.
- Keep temperature at `0`, model `deepseek-v4-flash`, and thinking disabled for every real request.
- Do not treat a single shared-initial run as evidence that one mechanism is superior.

---

### Task 1: Immutable Initial-State Contract

**Files:**
- Modify: `src/mas_experiment/domain.py`
- Modify: `src/mas_experiment/orchestrations.py`
- Modify: `tests/test_orchestrations.py`

**Interfaces:**
- Consumes: `Question`, `AgentRole`, `AgentResponse`, `Message`, and `ModelProvider`.
- Produces: `InitialState`, `InitialStateValidationError`, `prepare_initial_state(...)`, and `validate_initial_state(...)`.

- [ ] **Step 1: Add a recording provider failure option and write failing preparation tests**

Extend the test provider without changing its successful default:

```python
class RecordingProvider:
    def __init__(self, *, fail_agent_id: str | None = None) -> None:
        self.fail_agent_id = fail_agent_id
        self.visible_histories: list[tuple[str, ...]] = []
        self.calls: list[tuple[str, tuple[Message, ...]]] = []

    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        self.visible_histories.append(
            tuple(message.message_id for message in visible_messages)
        )
        self.calls.append((role.agent_id, visible_messages))
        if role.agent_id == self.fail_agent_id:
            raise RuntimeError("initial failure")
        answer = next(iter(question.options))
        probabilities = {
            option: 0.7 if option == answer else 0.1
            for option in question.options
        }
        payload = {
            "answer": answer,
            "probabilities": probabilities,
            "reasoning": f"{role.agent_id} response",
        }
        return AgentResponse(
            response_id=(
                f"{role.agent_id}-{round_index}-"
                f"{len(visible_messages)}"
            ),
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            probabilities=probabilities,
            reasoning=payload["reasoning"],
            raw_text=json.dumps(payload),
            changed_from_previous=False,
            provider_metadata={"api_requests": 1},
            timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
```

Add:

```python
@pytest.mark.asyncio
async def test_prepare_initial_state_makes_three_mutually_invisible_calls():
    provider = RecordingProvider()

    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert provider.call_count == 3
    assert provider.visible_histories == [(), (), ()]
    assert state.question_id == FORMAL_PILOT_QUESTION.question_id
    assert state.agent_ids == tuple(
        role.agent_id for role in FORMAL_PILOT_ROLES
    )
    assert len(state.messages) == 3
    assert len(state.responses) == 3
    assert state.errors == ()


@pytest.mark.asyncio
async def test_prepare_initial_state_preserves_failures_for_validation():
    provider = RecordingProvider(fail_agent_id="agent-b")

    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    assert len(state.responses) == 2
    assert state.errors == (
        "agent-b: RuntimeError: initial failure",
    )
```

- [ ] **Step 2: Run the preparation tests and verify RED**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -k "prepare_initial_state" -v
```

Expected: collection fails because `InitialState` and `prepare_initial_state` do not exist.

- [ ] **Step 3: Add the immutable domain record**

In `domain.py`, add:

```python
class InitialState(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_state_id: str
    question_id: str
    agent_ids: tuple[str, ...]
    messages: tuple[Message, ...]
    responses: tuple[AgentResponse, ...]
    errors: tuple[str, ...] = ()
```

Place it after `Message`, so every referenced type is already defined.

- [ ] **Step 4: Refactor initialization into a public preparation function**

In `orchestrations.py`, replace `_initial_stage` with:

```python
class InitialStateValidationError(ValueError):
    """Raised when a shared initial snapshot cannot seed a run."""


def _initial_state_id(
    question: Question,
    roles: tuple[AgentRole, ...],
    responses: Sequence[AgentResponse],
) -> str:
    identity = "|".join(
        (
            question.question_id,
            *(role.agent_id for role in roles),
            *(response.response_id for response in responses),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


async def prepare_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
) -> InitialState:
    visible_messages: tuple[Message, ...] = ()
    outcomes = await asyncio.gather(
        *(
            provider.generate(
                question=question,
                role=role,
                round_index=0,
                visible_messages=visible_messages,
                seed=seed,
            )
            for role in roles
        ),
        return_exceptions=True,
    )
    responses: list[AgentResponse] = []
    messages: list[Message] = []
    errors: list[str] = []
    for role, outcome in zip(roles, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            errors.append(
                f"{role.agent_id}: {type(outcome).__name__}: {outcome}"
            )
            continue
        responses.append(outcome)
        messages.append(
            _message_for(
                mode="initial",
                index=len(messages),
                response=outcome,
                visible_messages=visible_messages,
                user_prompt=_prompt_for(
                    question,
                    role,
                    visible_messages,
                ),
            )
        )
    return InitialState(
        initial_state_id=_initial_state_id(question, roles, responses),
        question_id=question.question_id,
        agent_ids=tuple(role.agent_id for role in roles),
        messages=tuple(messages),
        responses=tuple(responses),
        errors=tuple(errors),
    )
```

Import `hashlib` and `InitialState`.

- [ ] **Step 5: Run the preparation tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -k "prepare_initial_state" -v
```

Expected: both preparation tests pass.

- [ ] **Step 6: Write failing validation tests**

Add:

```python
def test_validate_initial_state_rejects_a_different_question():
    state = InitialState(
        initial_state_id="shared-1",
        question_id="other-question",
        agent_ids=tuple(role.agent_id for role in FORMAL_PILOT_ROLES),
        messages=(),
        responses=(),
    )

    with pytest.raises(
        InitialStateValidationError,
        match="question",
    ):
        validate_initial_state(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            state,
        )


@pytest.mark.asyncio
async def test_validate_initial_state_rejects_an_incomplete_snapshot():
    provider = RecordingProvider(fail_agent_id="agent-b")
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )

    with pytest.raises(
        InitialStateValidationError,
        match="initialization errors",
    ):
        validate_initial_state(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            state,
        )
```

- [ ] **Step 7: Run validation tests and verify RED**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -k "validate_initial_state" -v
```

Expected: collection fails because `validate_initial_state` does not exist.

- [ ] **Step 8: Implement exact snapshot validation**

Add:

```python
def validate_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    state: InitialState,
) -> None:
    role_ids = tuple(role.agent_id for role in roles)
    if state.question_id != question.question_id:
        raise InitialStateValidationError(
            "initial state question does not match"
        )
    if state.agent_ids != role_ids:
        raise InitialStateValidationError(
            "initial state agent order does not match"
        )
    if state.errors:
        raise InitialStateValidationError(
            "initial state contains initialization errors: "
            + "; ".join(state.errors)
        )
    if len(state.responses) != len(roles):
        raise InitialStateValidationError(
            "initial state must contain exactly one response per agent"
        )
    if len(state.messages) != len(roles):
        raise InitialStateValidationError(
            "initial state must contain exactly one message per agent"
        )
    response_ids = tuple(
        response.agent_id for response in state.responses
    )
    message_ids = tuple(message.speaker for message in state.messages)
    if response_ids != role_ids or message_ids != role_ids:
        raise InitialStateValidationError(
            "initial state response and message agents do not match"
        )
    if any(response.round_index != 0 for response in state.responses):
        raise InitialStateValidationError(
            "initial responses must use round_index 0"
        )
    if any(message.round_index != 0 for message in state.messages):
        raise InitialStateValidationError(
            "initial messages must use round_index 0"
        )
    if any(message.visible_history_ids for message in state.messages):
        raise InitialStateValidationError(
            "initial messages must have empty visible history"
        )
```

The existing `AgentResponse` model continues to validate the probability
contract when the snapshot is constructed or deserialized.

- [ ] **Step 9: Run focused and regression tests**

Run:

```powershell
python -m pytest tests/test_orchestrations.py tests/test_domain.py -v
```

Expected: all selected tests pass.

- [ ] **Step 10: Commit the contract**

```powershell
git add src/mas_experiment/domain.py src/mas_experiment/orchestrations.py tests/test_orchestrations.py
git commit -m "feat: add shared initial state contract"
```

---

### Task 2: Runner Reuse and Logical Metadata

**Files:**
- Modify: `src/mas_experiment/orchestrations.py`
- Modify: `tests/test_orchestrations.py`

**Interfaces:**
- Consumes: `InitialState`, `prepare_initial_state(...)`, and `validate_initial_state(...)`.
- Produces: optional `initial_state: InitialState | None` on `run_independent`, `run_round_robin`, `run_dynamic`, and `run_concurrent`; shared-state metadata in `ExperimentResult.metadata`.

- [ ] **Step 1: Write failing shared-runner tests**

Add:

```python
@pytest.mark.asyncio
async def test_three_modes_reuse_one_initial_state_without_provider_calls():
    preparation_provider = RecordingProvider()
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        preparation_provider,
        seed=20260727,
    )
    mode_provider = RecordingProvider()

    results = [
        await runner(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            mode_provider,
            seed=20260727,
            initial_state=state,
        )
        for runner in (run_independent, run_round_robin, run_dynamic)
    ]

    assert preparation_provider.call_count == 3
    assert mode_provider.call_count == 18
    assert all(len(result.responses) == 9 for result in results)
    assert all(
        result.responses[:3] == state.responses
        for result in results
    )
    assert all(
        result.metadata["initial_state_id"]
        == state.initial_state_id
        for result in results
    )
    assert all(
        result.metadata["shared_initial_state"] is True
        for result in results
    )


@pytest.mark.asyncio
async def test_runner_reuse_does_not_mutate_initial_state():
    provider = RecordingProvider()
    state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
    )
    original = state.model_dump(mode="json")

    await run_round_robin(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=20260727,
        initial_state=state,
    )

    assert state.model_dump(mode="json") == original
```

- [ ] **Step 2: Run the shared-runner tests and verify RED**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -k "reuse" -v
```

Expected: calls fail because runners do not accept `initial_state`.

- [ ] **Step 3: Add a resolver that copies the snapshot**

Add:

```python
async def _resolve_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None,
) -> tuple[list[Message], list[AgentResponse], InitialState, bool]:
    shared = initial_state is not None
    state = initial_state or await prepare_initial_state(
        question,
        roles,
        provider,
        seed=seed,
    )
    validate_initial_state(question, roles, state)
    return (
        list(state.messages),
        list(state.responses),
        state,
        shared,
    )
```

The list conversion is the only copy needed because Pydantic records are
frozen and runners only append to the lists.

- [ ] **Step 4: Add the optional parameter to every runner**

Use:

```python
async def run_independent(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
    initial_state: InitialState | None = None,
) -> ExperimentResult:
```

Apply the same keyword-only parameter to `run_concurrent`,
`run_round_robin`, and `run_dynamic`. Replace each `_initial_stage` call
with `_resolve_initial_state`. Make `run_concurrent` forward the supplied
snapshot.

- [ ] **Step 5: Attach shared-state metadata to results**

Change `_build_result` to consume:

```python
initial_state: InitialState
shared_initial_state: bool
```

Extend metadata with:

```python
"shared_initialization_api_requests": sum(
    int(
        response.provider_metadata.get("api_requests", 0)
        or 0
    )
    for response in initial_state.responses
),
"mode_follow_up_api_requests": sum(
    int(
        response.provider_metadata.get("api_requests", 0)
        or 0
    )
    for response in responses[len(initial_state.responses):]
),
"initial_state_id": initial_state.initial_state_id,
"shared_initial_state": shared_initial_state,
"logical_response_count": len(responses),
```

Pass the resolved state and flag from every runner.

- [ ] **Step 6: Run shared-runner tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -k "reuse" -v
```

Expected: both reuse tests pass and the combined provider count is
three initialization calls plus eighteen follow-up calls.

- [ ] **Step 7: Verify backward compatibility and visibility**

Run:

```powershell
python -m pytest tests/test_orchestrations.py -v
```

Expected:

- direct runner parametrization still reports nine provider calls each;
- initial histories remain empty;
- independent histories remain self-only;
- round-robin history lengths remain `0,0,0,3,4,5,6,7,8`;
- dynamic mode retains six selection steps and eighteen score rows.

- [ ] **Step 8: Commit runner reuse**

```powershell
git add src/mas_experiment/orchestrations.py tests/test_orchestrations.py
git commit -m "feat: reuse shared initial state across modes"
```

---

### Task 3: Formal CLI Accounting, Abort Behavior, and Report

**Files:**
- Modify: `src/mas_experiment/cli.py`
- Modify: `src/mas_experiment/reporting.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_reporting.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `prepare_initial_state(...)`, the three shared-state runners, serialized `response_id`, and existing provider metadata.
- Produces: one shared formal-pilot initialization, unique-request accounting, logical-slot reporting, and pre-output abort semantics.

- [ ] **Step 1: Write failing formal-pilot sharing and count tests**

Add to `test_cli.py`:

```python
def test_formal_pilot_reuses_one_initial_snapshot(tmp_path) -> None:
    output = tmp_path / "pilot.jsonl"

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = read_results(output)
    initial_ids = {
        record["metadata"]["initial_state_id"]
        for record in records
    }
    assert len(initial_ids) == 1
    assert all(
        record["metadata"]["shared_initial_state"] is True
        for record in records
    )
    assert records[0]["responses"][:3] == records[1]["responses"][:3]
    assert records[1]["responses"][:3] == records[2]["responses"][:3]
    assert "shared initialization API requests=3" in result.output
    assert "follow-up API requests=18" in result.output
    assert "discussion API requests=21" in result.output
    assert "logical response slots=27" in result.output
```

Use a failing provider factory:

```python
class FailingInitialProvider(RecordingProvider):
    async def generate(self, **kwargs):
        if kwargs["role"].agent_id == "agent-b":
            raise RuntimeError("initial failure")
        return await super().generate(**kwargs)


def test_formal_pilot_initial_failure_creates_no_output(
    monkeypatch,
    tmp_path,
) -> None:
    output = tmp_path / "pilot.jsonl"
    monkeypatch.setattr(
        "mas_experiment.cli.create_formal_provider",
        lambda provider_name: FailingInitialProvider(),
    )

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "initialization errors" in str(result.exception)
    assert not output.exists()
    assert not output.with_suffix(".md").exists()
```

If importing the orchestration test provider would couple test modules,
define the small provider locally in `test_cli.py` with the same valid
`AgentResponse` factory.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_cli.py -k "formal_pilot" -v
```

Expected: sharing assertions and new output text fail because the CLI
still prepares each mode independently.

- [ ] **Step 3: Prepare and validate the snapshot before opening output**

In `_run_formal_pilot`, after the optional connectivity probe and before
`output.parent.mkdir`, add:

```python
initial_state = await prepare_initial_state(
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    provider,
    seed=seed,
)
validate_initial_state(
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    initial_state,
)
```

Pass `initial_state=initial_state` to every runner. Do not create, clear,
or append the output until validation returns successfully.

- [ ] **Step 4: Add unique provider-request accounting**

In `reporting.py`, replace `_provider_totals` with a public helper that
deduplicates serialized copies by response ID:

```python
def provider_request_totals(
    results: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    seen_response_ids: set[str] = set()
    api_requests = 0
    repairs = 0
    for result in results:
        for response in result.get("responses", []):
            response_id = str(response.get("response_id", ""))
            if not response_id or response_id in seen_response_ids:
                continue
            seen_response_ids.add(response_id)
            metadata = response.get("provider_metadata", {})
            api_requests += int(metadata.get("api_requests", 0) or 0)
            repairs += int(metadata.get("repair_requests", 0) or 0)
    return api_requests, repairs
```

For offline responses whose metadata has no `api_requests`, count logical
provider calls in CLI tests with an injected provider that supplies
`api_requests=1`; the real DeepSeek path already records this field.

In `_run_formal_pilot`, calculate:

```python
discussion_requests, _ = provider_request_totals(records)
shared_initialization_requests = sum(
    int(response.provider_metadata.get("api_requests", 0) or 0)
    for response in initial_state.responses
)
follow_up_requests = (
    discussion_requests - shared_initialization_requests
)
logical_response_slots = sum(
    len(record["responses"]) for record in records
)
```

Return a frozen internal record:

```python
class FormalPilotCounts(NamedTuple):
    connectivity: int
    shared_initialization: int
    follow_up: int
    discussion: int
    logical_slots: int
```

For the offline CLI, derive the same call counts from response identity
even when provider metadata is empty:

```python
if provider_name == "offline":
    shared_initialization_requests = len(initial_state.responses)
    follow_up_requests = (
        len({response["response_id"]
             for record in records
             for response in record["responses"]})
        - shared_initialization_requests
    )
    discussion_requests = (
        shared_initialization_requests + follow_up_requests
    )
```

- [ ] **Step 5: Print the unambiguous count breakdown**

Change command output to:

```python
typer.echo(
    f"Completed formal pilot -> {output}; "
    f"report -> {output.with_suffix('.md')}; "
    f"connectivity API requests={counts.connectivity}; "
    "shared initialization API requests="
    f"{counts.shared_initialization}; "
    f"follow-up API requests={counts.follow_up}; "
    f"discussion API requests={counts.discussion}; "
    f"logical response slots={counts.logical_slots}"
)
```

- [ ] **Step 6: Write failing report-accounting tests**

Extend the fixture to contain one shared response with the same
`response_id` in two results and one unique follow-up response per result:

```python
def test_report_deduplicates_shared_initial_api_requests():
    shared = {
        "response_id": "shared-a",
        "provider_metadata": {
            "api_requests": 1,
            "repair_requests": 0,
        },
    }
    first = {
        **FIXTURE_RESULTS[0],
        "responses": [
            shared,
            {
                "response_id": "follow-up-1",
                "provider_metadata": {
                    "api_requests": 1,
                    "repair_requests": 0,
                },
            },
        ],
    }
    second = {
        **FIXTURE_RESULTS[0],
        "mode": "round_robin",
        "responses": [
            shared,
            {
                "response_id": "follow-up-2",
                "provider_metadata": {
                    "api_requests": 1,
                    "repair_requests": 0,
                },
            },
        ],
    }

    report = build_pilot_report([first, second])

    assert "实际API请求：3" in report
    assert "逻辑响应位置：4" in report
```

- [ ] **Step 7: Run report test and verify RED**

Run:

```powershell
python -m pytest tests/test_reporting.py -k "deduplicates" -v
```

Expected: the report counts the repeated shared response twice or omits
logical response slots.

- [ ] **Step 8: Update the report without changing research claims**

Use `provider_request_totals(results)` and:

```python
logical_slots = sum(
    len(result.get("responses", [])) for result in results
)
shared_ids = {
    str(result.get("metadata", {}).get("initial_state_id", ""))
    for result in results
    if result.get("metadata", {}).get("initial_state_id")
}
```

Add engineering-observation lines for:

- unique real API requests;
- logical response positions;
- shared initialization state ID when exactly one exists.

Keep the MAST candidate sections and the fixed single-run limitation
unchanged.

- [ ] **Step 9: Update README commands and count semantics**

Document:

```powershell
mas-experiment formal-pilot `
  --output artifacts/deepseek-formal-pilot-shared-initial.jsonl
```

State that the command performs one optional connectivity request,
three shared initial calls, eighteen follow-up calls, twenty-one real
discussion requests, and twenty-seven serialized logical response slots.

- [ ] **Step 10: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_cli.py tests/test_reporting.py tests/test_orchestrations.py -v
python -m pytest -q
git diff --check
```

Expected: all tests pass and no whitespace error is reported.

- [ ] **Step 11: Commit CLI and reporting changes**

```powershell
git add src/mas_experiment/cli.py src/mas_experiment/reporting.py tests/test_cli.py tests/test_reporting.py README.md
git commit -m "feat: share formal pilot initialization"
```

---

### Task 4: Offline Acceptance, Real DeepSeek Rerun, and PR Update

**Files:**
- Generated and ignored: `artifacts/formal-pilot-shared-initial-offline.jsonl`
- Generated and ignored: `artifacts/formal-pilot-shared-initial-offline.md`
- Generated and ignored: `artifacts/deepseek-formal-pilot-shared-initial.jsonl`
- Generated and ignored: `artifacts/deepseek-formal-pilot-shared-initial.md`

**Interfaces:**
- Consumes: the completed shared formal-pilot CLI and locally configured DeepSeek environment variables.
- Produces: acceptance evidence, one new shared-initial real run, a result comparison, and updated Draft PR content.

- [ ] **Step 1: Run complete local verification**

Run:

```powershell
python -m pytest -v
mas-experiment formal-pilot `
  --provider offline `
  --skip-connectivity `
  --overwrite `
  --output artifacts/formal-pilot-shared-initial-offline.jsonl
git diff --check
git status -sb
```

Expected:

- all tests pass;
- three mode records exist;
- every mode has nine logical responses;
- the three records have one `initial_state_id`;
- the output reports three shared initialization calls, eighteen follow-up
  calls, twenty-one discussion calls, and twenty-seven logical slots;
- generated artifacts remain ignored.

- [ ] **Step 2: Audit the offline trace structurally**

Run a Python audit that asserts:

```python
assert len(records) == 3
assert {len(record["responses"]) for record in records} == {9}
assert len({
    record["metadata"]["initial_state_id"]
    for record in records
}) == 1
assert records[0]["responses"][:3] == records[1]["responses"][:3]
assert records[1]["responses"][:3] == records[2]["responses"][:3]
assert all(
    not message["visible_history_ids"]
    for record in records
    for message in record["messages"][:3]
)
assert len(records[2]["selection_scores"]) == 18
```

Expected: the audit exits with status zero.

- [ ] **Step 3: Verify credentials without printing them**

Load user-scoped values into the process and print only `SET` or
`MISSING` for:

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_CHAT_COMPLETION_MODEL
```

Stop before network calls if any value is missing or if the URL/model do
not match the approved DeepSeek configuration.

- [ ] **Step 4: Run one safe connectivity probe**

Call one Agent with empty visible history and print only:

```json
{
  "structured_response_valid": true,
  "model": "deepseek-v4-flash",
  "thinking": "disabled",
  "temperature": 0,
  "api_requests": 1,
  "repair_requests": 0
}
```

Allow one explicitly counted repair request. Abort the real pilot if the
probe fails.

- [ ] **Step 5: Run the new real shared-initial pilot**

Run:

```powershell
mas-experiment formal-pilot `
  --skip-connectivity `
  --overwrite `
  --output artifacts/deepseek-formal-pilot-shared-initial.jsonl
```

Expected: three shared initialization requests plus eighteen follow-up
requests, with any repairs counted separately.

- [ ] **Step 6: Audit real output and credentials**

Verify:

- three mode records;
- nine logical responses per mode;
- identical first-three responses across modes;
- one shared `initial_state_id`;
- empty initial visible histories;
- independent self-only visibility;
- six dynamic selection steps and eighteen score rows;
- twenty-one unique discussion API requests before repairs;
- no literal configured key match;
- no raw authorization header;
- no output overwrite of the earlier independently initialized run.

The secret comparison must print only `KEY_LEAK=True|False`, never the
key itself.

- [ ] **Step 7: Compare the two real runs**

Write a concise engineering comparison covering:

- independently initialized result versus shared-initial result;
- each mode's pooled and majority answers;
- wrong-consensus status;
- probability and `b_i` changes;
- FM-2.4, FM-2.5, and FM-2.6 candidate signals;
- request and repair counts;
- the limitation that differences between the two single runs may still
  reflect remote-model nondeterminism.

- [ ] **Step 8: Verify Git state and push the source commits**

Run:

```powershell
python -m pytest -v
git diff --check
git status -sb
git push -u origin codex/maf-experiment
```

Expected: the source tree is clean, generated artifacts remain ignored,
and the remote branch matches local `HEAD`.

- [ ] **Step 9: Update Draft PR #1**

Update the existing PR instead of creating another one. Add:

- shared initialization design and implementation;
- twenty-one real request versus twenty-seven logical-slot distinction;
- fresh test count;
- offline and real shared-initial acceptance results;
- the single-run research limitation.

Keep the PR in Draft state.

---

## Final Verification Checklist

- [ ] The formal pilot makes one shared three-call initialization.
- [ ] Three modes receive byte-equivalent initial raw responses.
- [ ] Each mode still has nine logical responses.
- [ ] The three modes make eighteen total follow-up calls.
- [ ] Unique real discussion calls total twenty-one before repairs.
- [ ] Direct runner calls without a snapshot still make nine calls.
- [ ] Invalid shared initialization creates no output.
- [ ] Dynamic mode still logs six steps and eighteen candidate scores.
- [ ] All probability vectors remain complete and normalized.
- [ ] Runtime selection never receives the answer key.
- [ ] Real requests use DeepSeek V4 Flash, temperature zero, and thinking disabled.
- [ ] The new JSONL and Markdown contain no credentials.
- [ ] The old independently initialized artifacts remain unchanged.
- [ ] The report distinguishes engineering observations from research claims.
