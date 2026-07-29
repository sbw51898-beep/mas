# Budget-Matched HiddenBench Dynamic Speaker Design

## Objective

Compare the frozen HiddenBench fixed round-robin baseline with a
content-aware dynamic speaker mechanism without confusing model-call or
per-agent speech-budget differences with a governance effect.

The first stage is an engineering pilot on task IDs 1, 5, and 7. It tests
protocol integrity and produces descriptive evidence only. It does not make
a statistical superiority claim. Expansion to the existing ten-task screen
is allowed only after the three-task audit gate passes.

## Frozen baseline

The comparison treats the following baseline as immutable:

- Git commit: `2b9b0a9`
- source record:
  `artifacts/hiddenbench-screening-20260728-v2.jsonl`
- source SHA-256:
  `e3064a90e7fff6313821240828bc28afeed44500be47c60eb6d195799672e4eb`
- source report:
  `artifacts/hiddenbench-screening-20260728-v2.md`
- report SHA-256:
  `c819658f1cbe72126ef403c29cfbcd7904fc5f05f1f11c989cc8ae21e99e8108`
- baseline configuration:
  `configs/hiddenbench-screening.json`
- configuration-file SHA-256:
  `f1769b2b92f117aa56699747833a091727e7db050d75b1738ddb05f168424ce`
- dataset SHA-256:
  `2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3`
- base seed: `20260728`
- baseline model reported by the provider: `deepseek-v4-flash`
- temperature: `0`
- thinking mode: `disabled`
- prompt version: `hiddenbench-appendix-a4-v1`

The dynamic runner must validate these hashes and metadata before making any
DeepSeek request. It must not overwrite or regenerate the baseline bundle.

Because the DeepSeek model name is a provider alias rather than a guaranteed
immutable weight snapshot, the report must identify possible provider drift
as a limitation. A matching returned model name is necessary but cannot prove
identical hidden weights.

## Pilot task set

The pilot runs exactly:

- ID 1: `evacuation_west_city`
- ID 5: `baker_2010`
- ID 7: `graetz_et_al_1998`

For every task, the dynamic condition reuses the baseline task data,
assignment seed, shared information, and agent-to-private-information
assignment. A preflight comparison must reject any assignment mismatch.

## Budget matching

Both conditions have:

- four agents;
- exactly 15 public speeches per agent;
- exactly 60 public discussion speeches in total;
- no adaptive termination;
- the same four hidden-pre votes, four hidden-post votes, and four
  full-profile votes as logical phases;
- the same sequential visibility rule: speech `t` sees exactly speeches
  `0..t-1`;
- no model call for speaker selection.

The dynamic condition changes only the order in which the 60 speech slots are
assigned. An agent becomes ineligible after using its fifteenth slot. The
selector therefore cannot change either total budget or per-agent budget.

For compatibility with the existing message model, `turn_index` remains
`0..59` and `round_index` is `turn_index // 4 + 1`. In the dynamic condition,
`round_index` is a four-slot reporting block, not a claim that all four agents
spoke once.

## Selector visibility and interpretation

The selector is a deterministic, centralized, closed-form orchestrator. It
may read:

- the frozen task and private-information assignment;
- hidden-pre votes, used only as each agent's initial stance;
- all public messages produced so far;
- each agent's latest extractable public stance;
- disclosure matches derived from registered private-information atoms;
- previous selection scores and remaining quotas.

The selector may not read:

- hidden-post or full-profile votes before discussion ends;
- the official correct answer;
- future baseline messages;
- provider hidden state or chain-of-thought;
- any new LLM judgment.

The mechanism must be described as content-aware orchestration, not as a
fully private-information-blind or fully decentralized method.

## Private-information atoms

Each assigned private-information block is decomposed deterministically:

- a one-sentence fact is one atom;
- a multi-line heading followed by bullets produces one atom per bullet,
  prefixed with its heading;
- criterion lines such as `(a) N` retain the current company heading;
- blank lines and standalone headings are not atoms.

Disclosure and response-use checks reuse the existing
`lexical-semantic-v2` matcher. The atom list and every match decision are
written to the audit trace. No selector score may depend on an unlogged
semantic judgment.

## Five-factor score

For each eligible agent `i` at turn `t`:

```text
S_i(t) =
    0.30 * disagreement_i(t)
  + 0.30 * undisclosed_i(t)
  + 0.15 * related_discussion_i(t)
  + 0.15 * response_due_i(t)
  + 0.10 * waiting_i(t)
```

All factors are in `[0, 1]`.

### Disagreement

Each agent's initial stance is its hidden-pre vote. Its latest stance is
updated only when exactly one official possible answer can be identified in
its public message. Ambiguous or absent answer mentions leave the previous
stance unchanged.

The public group plurality is computed from the four latest stances. The
factor is:

- `1` when the agent's stance is outside a unique plurality;
- `0.5` when the group has no unique plurality;
- `0` when the agent is in the unique plurality.

The official correct answer is never used.

### Undisclosed information

This is the fraction of the candidate's private-information atoms that have
not yet been disclosed by that candidate in public. It is `0` when the
candidate has no atoms.

### Related discussion

This is `1` when, since the candidate last spoke, another agent has mentioned
an official possible answer that also occurs in one of the candidate's
still-undisclosed atoms. Matching is a case-insensitive exact phrase match
against `task.possible_answers`. Otherwise it is `0`.

This trigger detects an opportunity to correct or enrich a discussion. It
does not assert that the other message is wrong.

### Response due

This is the fraction of other owners' newly disclosed atoms since the
candidate last spoke that the candidate has not yet used in a later public
message. It is capped at `1` and is `0` when no new cross-agent atom is
available.

### Waiting

Waiting is the number of turns since the candidate last spoke divided by the
largest waiting value among eligible agents. Before an agent's first speech,
its last-spoken turn is treated as `-1`.

### Selection and ties

Only agents with remaining quota are scored. The highest score speaks.
Exact ties are resolved by:

1. larger remaining quota;
2. longer raw waiting time;
3. lexical agent ID (`agent-a` before `agent-b`, and so on).

There is no random tie-break and no consecutive-speaker cap. Quota and
waiting are fully visible in the trace, so any concentrated speaking pattern
is auditable rather than silently corrected.

## Runtime flow

For each pilot task:

1. Validate the frozen baseline manifest, configuration, task identity,
   assignment, provider settings, and 60-message baseline structure.
2. Run four hidden-pre votes with the existing prompts.
3. Check that returned provider metadata reports the configured model,
   temperature, and thinking mode.
4. For each of 60 turns, score all eligible agents, record the full score
   table, select one agent, and make exactly one discussion completion.
5. Run four hidden-post votes and four full-profile votes.
6. Compute existing HiddenBench metrics and MAST candidates without changing
   their definitions.
7. Write the dynamic run, selector trace, paired comparison, and SHA-256
   manifest.

A failed provider call aborts the task. Discussion responses are not repaired.
Vote repair behavior remains the existing one-repair maximum and is reported
separately; a repair does not count as a discussion speech.

## Audit artifacts

The pilot writes a new, non-overwriting bundle:

- dynamic JSONL containing three complete runs;
- dynamic Markdown transcript and metric summary;
- selector-trace JSONL with 60 selection events per task;
- paired-comparison Markdown report;
- pilot gate JSON;
- SHA-256 manifest covering all generated artifacts.

Each selector event records:

- task ID and turn index;
- candidate agent ID;
- five factor values and weighted total;
- remaining quota before selection;
- latest stance and group plurality;
- atom IDs supporting disclosure or response triggers;
- raw waiting value;
- selected flag and tie-break reason.

## Comparison measures

The paired report compares baseline and dynamic values for each task:

- `y_pre_average`, `y_post_average`, and `integration_gain`;
- post-discussion majority correctness;
- post-discussion unanimity and wrong consensus;
- private-fact disclosure rate;
- cross-agent use rate;
- MAST FM-2.4, FM-2.5, and FM-2.6 candidate counts;
- exact discussion calls;
- per-agent speech counts;
- prompt tokens, output tokens, and total tokens.

Equal speech counts do not guarantee equal token budgets. Token usage is
therefore reported as a secondary budget diagnostic and must not be described
as controlled unless it is empirically equal.

For IDs 1, 5, and 7, the report also reuses the existing three-category
manual framework:

- information not disclosed;
- disclosed information ignored;
- correct evidence misinterpreted.

Dynamic transcripts require a new human review; baseline labels must not be
copied onto them automatically.

## Pilot gate

The three-task pilot passes only if all of the following hold:

- frozen hashes and baseline metadata validate;
- task IDs are exactly `1, 5, 7`;
- each dynamic run has exactly 60 discussion messages;
- every agent speaks exactly 15 times per task;
- every selection event has four candidates before quotas expire and only
  eligible candidates afterward;
- the selected agent is the deterministic winner under the recorded scores
  and tie-break rules;
- selector LLM calls equal zero;
- discussion logical slots equal 60 per task;
- visibility grows by exactly one message per turn;
- all prompt and assignment isolation checks pass;
- provider model, temperature, and thinking metadata match the frozen
  settings;
- output manifests match generated bytes.

The gate checks protocol integrity, not whether dynamic accuracy improves.
An accuracy decrease still produces a valid experimental result.

## Expansion rule

After the pilot gate passes and the three dynamic transcripts receive manual
review, the same code and weights may run the existing ten-task list:
`1, 5, 7, 9, 13, 14, 16, 25, 47, 62`.

No selector weight, atomization rule, matching rule, prompt, or task list may
change between pilot approval and ten-task execution without creating a new
configuration version and reporting the pilot as exploratory tuning.
