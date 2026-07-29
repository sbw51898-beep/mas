# HiddenBench AI Disclosure and Stability Study Design

## Purpose

This study extends the frozen HiddenBench comparison in PR #4 to answer
three follow-up questions:

1. Can an LLM auditor estimate private-fact disclosure directly from the
   transcript and provide auditable evidence for every judgment?
2. Are the observed fixed-round-robin and content-aware dynamic outcomes
   stable across repeated runs rather than artifacts of one seed?
3. Which information-process mechanisms explain success, failure, early
   consensus, and consensus reversal?

The study is descriptive. Ten repetitions per task and condition do not
support a general superiority or significance claim.

## Scope

The task set is frozen before execution:

| Task | Reason for inclusion |
|---|---|
| HiddenBench ID 1 | Dynamic speaking prevented the prior wrong consensus |
| HiddenBench ID 5 | Critical private information remained undisclosed |
| HiddenBench ID 7 | Correct counterevidence was disclosed but ignored or misinterpreted |
| HiddenBench ID 25 | Correct consensus formed early and later turns were mostly repetitive |

Each task runs under two mechanisms:

- fixed A-B-C-D round robin;
- deterministic content-aware dynamic selection.

Each task-mechanism pair runs 10 repetitions, producing 80 task-condition
runs. Repetition indices are `0..9`.

## Experimental Controls

For a given task and repetition, fixed and dynamic runs must share:

- the same HiddenBench dataset hash;
- the same task text and correct answer;
- the same DeepSeek model, endpoint, temperature, and thinking setting;
- the same base seed and derived assignment seed;
- the same four agent identities;
- the same private-information assignment;
- the same initial voting protocol;
- the same sequential public-message visibility;
- exactly 15 public speeches per agent and 60 total speeches;
- the same post-discussion and Full Profile voting protocol.

The only treatment difference is speaker order.

The fixed condition uses A-B-C-D round robin. The dynamic condition uses
the frozen five-factor selector:

```text
S_i = 0.30 D_i + 0.30 E_i + 0.15 G_i + 0.15 Q_i + 0.10 W_i
```

The selector makes zero LLM calls. Equal speech count is the experimental
budget control; token consumption is reported separately and is not
claimed to be equal.

## Repetition and Seed Policy

The study configuration stores one base seed. For repetition `r`, the
pair seed is derived deterministically from the base seed, task ID, and
repetition index. Fixed and dynamic conditions consume the same derived
assignment seed.

The seed derivation is recorded in every run. A preflight gate rejects:

- duplicated pair keys;
- missing task-condition repetitions;
- unequal assignment fingerprints within a pair;
- unequal speech counts;
- provider-setting drift;
- task or dataset hash drift;
- nonzero dynamic selector LLM calls.

## LLM Disclosure Auditor

### Role

Disclosure auditing happens after the experiment. It cannot affect
speaker selection, model prompts, votes, or stopping behavior.

The auditor is a separate DeepSeek API call with isolated context and
temperature `0`. It may use the same underlying provider model as the
agents, so the report must call it an **independent audit call**, not an
independent model.

### Input

One audit request receives:

- task ID and task name;
- the four private facts;
- the owner agent for each private fact;
- all 60 public messages with immutable message IDs, speaker IDs, turn
  indices, and text;
- a strict definition of disclosure.

It does not receive rule-based disclosure labels.

### Disclosure Definition

A private fact is disclosed only when its owner states the decision-relevant
claim in a public message.

- Exact quotation is not required; a faithful paraphrase counts.
- Mentioning only the entity without the private claim does not count.
- A polarity reversal does not count.
- A statement by a non-owner does not count as owner disclosure.
- A guess that happens to match the fact does not count.
- Partial disclosure counts only when the expressed portion contains an
  independently decision-relevant atomic claim.

### Output Contract

The auditor returns strict JSON with one item per private fact:

```json
{
  "task_id": 1,
  "condition": "dynamic",
  "repetition": 0,
  "facts": [
    {
      "fact_id": "fact-1",
      "owner_agent_id": "agent-a",
      "disclosed": true,
      "evidence_message_ids": ["task-1-dynamic-r0-turn-3"],
      "evidence_quote": "short exact excerpt",
      "reason": "why the message expresses the private claim",
      "confidence": 0.97
    }
  ]
}
```

The application rejects an audit when:

- a fact is missing or duplicated;
- an evidence message ID does not exist;
- an evidence message belongs to a non-owner;
- `disclosed=true` has no evidence;
- `disclosed=false` includes evidence;
- the evidence quote is not a substring of the referenced public message;
- confidence is outside `[0, 1]`.

One repair request is allowed for invalid JSON or schema violations. The
repair call count is recorded separately.

### Aggregate AI Disclosure Rate

For a run:

```text
ai_disclosure_rate =
    number of private facts judged disclosed
    / total number of private facts
```

The value is reported as both a fraction and percentage.

## Rule Cross-Check

The existing `lexical-semantic-v2` matcher remains unchanged and runs on
the same transcripts.

For each run the study records:

- AI disclosure rate;
- rule disclosure rate;
- fact-level agreement count;
- fact-level disagreement count;
- Cohen's kappa when both label sets have enough variation;
- a review queue containing every disagreement with both evidence sets.

The AI result does not silently replace the rule result. The report shows
both and describes disagreements as items requiring human review.

## Consensus and Stability Metrics

### Outcome Metrics

Per run:

- `Y_pre`: fraction of four agents correct before discussion;
- `Y_post`: fraction correct after discussion;
- integration gain: `Y_post - Y_pre`;
- majority correctness;
- unanimous consensus;
- wrong consensus;
- Full Profile accuracy.

### Conversation Dynamics

Votes are not collected after every public message, so consensus timing
cannot be inferred from final votes alone. The study therefore measures
**expressed position consensus** from public messages only when a message
contains an unambiguous current recommendation.

Per run:

- first turn at which all four agents' latest expressed positions agree;
- whether that consensus is correct;
- first turn at which the same unanimous position remains unchanged for
  a complete four-agent speech cycle;
- number of subsequent consensus flips;
- fraction of speeches after stable consensus;
- repeated-confirmation rate after stable consensus.

If one or more agents have not expressed an unambiguous position, the
consensus turn is null rather than guessed.

### Stability Summary

For each task and condition across 10 repetitions:

- mean and standard deviation of `Y_pre`, `Y_post`, integration gain,
  AI disclosure rate, and rule disclosure rate;
- count out of 10 with correct majority;
- count out of 10 with unanimous wrong consensus;
- distribution of final answers;
- median and range of first and stable consensus turns;
- mean post-consensus repetition rate;
- AI-rule fact-level agreement.

For each task, paired fixed-minus-dynamic differences use matching
repetition seeds. The report gives paired counts and descriptive
intervals but does not present a confirmatory p-value.

## Execution Efficiency

The runner may execute independent task-repetition pairs concurrently,
subject to a configurable worker limit. Fixed and dynamic runs within a
pair may execute concurrently because they share immutable assignments
and do not exchange state.

Rate-limit and transient provider failures use bounded retries with
recorded attempt metadata. Completed pair records are append-only, and a
resume command skips already validated pair keys. This prevents a long
study from restarting after interruption.

LLM disclosure audits run only after all 60-message transcripts exist.
They may also run concurrently with a separate worker limit.

## Data Model and Outputs

### Configuration

Create `configs/hiddenbench-ai-disclosure-stability.json` containing:

- task IDs `[1, 5, 7, 25]`;
- repetitions `10`;
- base seed;
- provider settings;
- fixed and dynamic speech budgets;
- selector weights;
- experiment and judge worker limits;
- auditor model and prompt version;
- frozen dataset and baseline identifiers.

### Artifacts

The formal run writes:

- `artifacts/hiddenbench-stability-20260729.jsonl`
  - one validated record per task, condition, and repetition;
- `artifacts/hiddenbench-stability-20260729.trace.jsonl`
  - all public messages and dynamic selector scores;
- `artifacts/hiddenbench-stability-20260729.ai-disclosure.jsonl`
  - one AI audit per run;
- `artifacts/hiddenbench-stability-20260729.disagreements.csv`
  - AI-rule fact-level disagreements;
- `artifacts/hiddenbench-stability-20260729.summary.csv`
  - task-condition stability metrics;
- `artifacts/hiddenbench-stability-20260729.md`
  - reader-facing analysis;
- `artifacts/hiddenbench-stability-20260729.gate.json`
  - control and completeness checks;
- `artifacts/hiddenbench-stability-20260729.manifest.json`
  - file sizes and SHA-256 hashes.

The date token is an artifact label, not a hidden input to the study.

## CLI

Add:

```text
mas-experiment hiddenbench-stability
```

Key options:

- `--config`;
- `--output`;
- `--resume/--no-resume`;
- `--experiment-workers`;
- `--judge-workers`;
- `--offline`;
- `--skip-ai-judge`.

Offline mode uses deterministic fake clients and must produce the same
pair keys, budgets, schemas, gate structure, and report columns without
calling an external model.

## Analysis Boundaries

The report must state:

- the four tasks were deliberately selected as mechanism-diverse cases;
- ten repetitions assess within-case stability, not population-level
  generalization;
- DeepSeek is not one of the four model families in the HiddenBench paper;
- the LLM auditor may share a model family with the acting agents;
- AI disclosure percentages are evidence-backed judgments, not ground
  truth;
- rule and AI disagreements remain visible;
- equal speech counts do not imply equal tokens;
- early consensus can be wrong, and later repetition is not automatically
  beneficial.

## Word Report Update

Update the retained report:

`C:\Users\liuli\Desktop\给彭老师的HiddenBench_MAF复现实验最终报告_2026-07-29_修订版.docx`

The revised copy must:

- explain the original paper's custom Python evaluator and model families;
- add task-level official-result comparison where public result files
  support it;
- explain why the 15-round protocol was retained;
- map confirmed MAST cases to exact task, agent, and message evidence;
- explain why round-one disclosure is not identical to Full Profile;
- replace the single-run dynamic table with the 10-repetition stability
  summary;
- describe the AI auditor and its limitations;
- link all new reproducibility artifacts.

The source report remains unchanged. The output receives a new dated
filename.

## Test Strategy

Use test-driven development for every new production behavior.

Required tests include:

- deterministic pair-seed derivation;
- complete 4 × 2 × 10 run matrix;
- fixed/dynamic assignment equality within a pair;
- exact 60-speech and 15-per-agent budgets;
- AI audit schema validation;
- rejection of nonexistent, non-owner, and non-substring evidence;
- disclosure percentage calculation;
- AI-rule agreement and disagreement rows;
- null consensus timing when positions are ambiguous;
- stable consensus and flip counting;
- resume behavior;
- gate failure for missing or mismatched pairs;
- Markdown and CSV summary content;
- offline CLI end-to-end execution.

Before formal execution:

- run the full test suite;
- run offline end-to-end;
- inspect gate and manifest outputs;
- verify no API key or authorization header can enter artifacts.

After formal execution:

- validate all 80 run records and all 80 AI audits;
- verify 4,800 public speeches in total;
- verify every task-condition-repetition key appears exactly once;
- verify all file hashes;
- rerun the full test suite;
- update and structurally validate the Word report.
