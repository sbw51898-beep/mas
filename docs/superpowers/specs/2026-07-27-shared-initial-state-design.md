# Shared Initial State for Fair Multi-Agent Comparison

## Objective

Make the independent, round-robin, and dynamic orchestration modes start
from exactly the same three model responses. This removes one avoidable
source of DeepSeek variability from the mechanism comparison while
preserving nine logical responses per mode.

The change applies first to the formal hidden-information pilot. Existing
callers that run one orchestration directly remain compatible.

## Experimental Semantics

The formal pilot performs one shared initialization:

1. Agent A, Agent B, and Agent C each receive the public task and only
   their own private information.
2. All three calls have an empty visible history.
3. The three calls run once and form an immutable initial-state snapshot.
4. Each orchestration receives a copy of that snapshot and executes six
   additional mode-specific calls.

The resulting accounting is:

- one optional connectivity probe;
- three real shared-initialization requests;
- six real follow-up requests per mode, eighteen total;
- twenty-one real formal-pilot discussion requests;
- nine logical responses per mode, twenty-seven logical response slots.

Reports and CLI output must distinguish real API requests from logical
response slots.

## Selected Architecture

Add an immutable `InitialState` domain record containing:

- a stable `initial_state_id`;
- the three initial `AgentResponse` values;
- the three corresponding `Message` values;
- initialization errors, if any.

Add:

```python
async def prepare_initial_state(
    question: Question,
    roles: tuple[AgentRole, ...],
    provider: ModelProvider,
    *,
    seed: int,
) -> InitialState:
    ...
```

Each orchestration runner accepts:

```python
initial_state: InitialState | None = None
```

When an initial state is supplied, the runner validates and copies its
messages and responses and does not make initialization calls. When it is
omitted, the runner prepares its own initial state so existing direct
callers retain the current nine-call behavior.

An explicit shared-state parameter is preferred over a provider cache.
It makes experimental reuse visible in the API, avoids accidentally
caching later calls, and gives tests a direct object to validate.

## Validation Rules

A usable shared initial state must satisfy all of the following:

- it contains exactly one response and one message for every configured
  Agent;
- every response has `round_index == 0`;
- every initial message has an empty `visible_history_ids` tuple;
- message speakers and response Agent IDs match the configured roles;
- probability vectors pass the existing probability contract;
- no initialization errors are present;
- the question identity and ordered Agent identity set match the runner.

`InitialState` stores the question ID and ordered Agent IDs so a snapshot
cannot be reused with a different task or team.

If validation fails, the formal pilot aborts before any mode starts. It
must not create a new JSONL result file or a Markdown report.

## Mode Behavior

### Independent

Each Agent begins from only its own message in the shared snapshot. Two
self-reflection rounds follow. Peer messages from the snapshot or later
rounds never enter that Agent's visible history.

### Round Robin

All three shared initial messages become public after initialization.
The six follow-up turns use the fixed order A, B, C, A, B, C, with public
history growing after each turn.

### Dynamic

All three shared initial responses seed the selector's probability state
and last-spoken state. The selector performs six decisions and logs three
candidate scores per decision. Every selected Agent receives the complete
public history.

## Trace and Report Changes

Every `ExperimentResult` produced from a shared snapshot records:

- `initial_state_id`;
- `shared_initial_state: true`;
- `logical_response_count: 9`;
- mode-specific real API-request totals.

The formal-pilot CLI and report expose:

- connectivity request count;
- shared-initialization request count;
- follow-up request count;
- total real discussion request count;
- total logical response-slot count.

The initial responses appear inside all three mode results for
standalone auditability. Their repeated serialization does not imply
repeated API calls.

## Output Preservation

The existing real-run artifacts remain unchanged as evidence for the
independently initialized version.

The shared-initialization rerun uses new filenames:

- `artifacts/deepseek-formal-pilot-shared-initial.jsonl`;
- `artifacts/deepseek-formal-pilot-shared-initial.md`.

Generated artifacts and credentials remain ignored by Git.

## Error Handling

- Any missing, duplicate, mismatched, or failed initial response aborts
  the formal pilot before mode execution.
- A follow-up failure remains attached to its mode under the existing
  result error behavior.
- A formal mode with fewer than nine logical responses remains invalid.
- The CLI refuses to overwrite an existing shared-initial output unless
  `--overwrite` is explicitly supplied.

## Test Strategy

Use test-driven development.

Add tests proving:

1. `prepare_initial_state` makes exactly three mutually invisible calls.
2. The formal pilot makes twenty-one real discussion calls.
3. Each mode still contains nine logical responses.
4. The first three responses and their raw payloads are identical across
   all three mode results.
5. All results share one `initial_state_id`.
6. Independent histories remain self-only.
7. Round-robin visibility still grows from three to eight prior messages.
8. Dynamic mode still records six selection steps and eighteen candidate
   score rows.
9. A runner cannot mutate the snapshot used by another runner.
10. A mismatched or incomplete snapshot is rejected.
11. Initialization failure prevents mode execution and result-file
    creation.
12. Direct runner calls without `initial_state` retain nine provider
    calls for backward compatibility.

Run focused orchestration and CLI tests, then the complete test suite,
offline acceptance, whitespace checks, and one new real DeepSeek pilot.

## Research Boundaries

Shared initialization improves internal validity but does not make one
question or one run sufficient evidence of mechanism superiority. Remote
model behavior can remain nondeterministic at temperature zero. Repeated
runs across multiple hidden-information tasks are still required before
making comparative research claims.
