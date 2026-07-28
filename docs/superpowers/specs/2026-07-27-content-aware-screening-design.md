# Content-Aware Screening Experiment Design

## Objective

Test whether a content-aware decentralized speaker selector improves hidden-profile information integration beyond independent work, fixed round-robin discussion, and a matched random-order discussion.

This is a screening experiment, not confirmatory evidence. Three task difficulties and two shared-initial-state repeats are used to identify whether the mechanism produces enough separation to justify a larger powered study.

## Experimental conditions

Every condition receives one mutually invisible initial response per agent and exactly six follow-up model calls.
Initial responses are retained as the shared private baseline but are not inserted into the public channel. Only follow-up messages can expose private information to other agents.

1. `independent`: each agent sees only its own prior messages.
2. `round_robin`: every agent speaks twice in fixed A-B-C order.
3. `random_order`: every agent speaks twice, with the six slots shuffled by a seeded PRNG.
4. `dynamic`: six speakers are selected one at a time by a closed-form five-factor score.

All four conditions reuse the same immutable initial state within one task-repeat pair. There is no passive belief update and no adaptive termination.

## Five-factor selector

The dynamic score is:

```text
score =
    0.30 * disagreement
  + 0.25 * information_exposure
  + 0.20 * dependency_trigger
  + 0.15 * uncertainty
  + 0.10 * waiting
```

- `disagreement`: Jensen-Shannon divergence between the agent distribution and pooled group distribution.
- `information_exposure`: proportion of that agent's declared private-information keywords not yet stated by their owning agent in public messages.
- `dependency_trigger`: 1 when information declared as relevant to this agent was stated by its owning agent since the candidate last spoke, otherwise 0.
- `uncertainty`: one minus the agent's maximum option probability.
- `waiting`: normalized time since the agent last spoke.

Task metadata explicitly declares information and dependency keywords. Missing metadata produces zero for the two content-aware factors, so ordinary benchmark questions remain supported.
Keyword aliases tolerate a model omitting a dimension prefix such as `ACCESS_`, but ownership checks prevent an identical numeric alias from another dimension being counted as disclosure or cross-agent use.

## Tasks

Three new weighted hidden-profile tasks use the same three generic expert roles. Each agent receives the complete raw scores for one dimension, while weights and decision rules are public.

- Easy: a wide winning margin and a weak misleading anchor.
- Medium: a moderate winning margin with conflicting dimensions.
- Hard: a narrow winning margin and a strong public anchor favoring a fast but inferior option.

The tasks use new scenarios and numbers and do not copy the `meeting-room` task data.

## Measures

Existing measures remain primary:

- pooled-answer accuracy;
- group Brier score;
- majority share and unanimity;
- wrong consensus;
- pairwise and Jensen-Shannon disagreement;
- answer entropy and flip rate;
- speaker share.

New trace-derived screening measures:

- `information_coverage`: fraction of declared private-information keywords that appeared in the public transcript;
- `cross_agent_input_use_rate`: fraction of follow-up messages that cite at least one keyword originating from another agent;
- `ignored_input_candidate_rate`: fraction of follow-up messages that had visible cross-agent information available but did not cite any such keyword. This is a candidate flag for manual FM-2.5 review, not an automatic diagnosis.

## Reproducibility and audit

Each record stores:

- task difficulty;
- shared initial-state ID;
- base seed and derived task-repeat seed;
- provider/model request metadata;
- exact logical and API request counts;
- a SHA-256 configuration fingerprint.
- the Git commit used for the run.

The screening command writes one JSONL result file, one Markdown report, and one SHA-256 manifest covering both files.

## Screening budget

For one task-repeat pair:

- shared initialization: 3 calls;
- four conditions × 6 follow-up calls: 24 calls;
- total: 27 calls.

For three tasks × two repeats:

- 6 shared initial states;
- 24 result records;
- 162 discussion API calls;
- an optional one-call connectivity probe is reported separately.

No confirmatory statistical claim will be made from two repeats.
