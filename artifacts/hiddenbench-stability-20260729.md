# HiddenBench AI Disclosure and Stability Study

Design: 4 representative tasks, 2 speaking conditions, and 10 repetitions per task-condition.

Both conditions use 60 public speeches and exactly 15 speeches per agent. The dynamic selector makes zero LLM calls.

## Stability summary

| Task | Condition | N | AI disclosure mean | AI disclosure SD | Majority correct | Unanimous | wrong consensus | Stable consensus | AI-rule agreement |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | fixed | 10 | 0.900 | 0.122 | 10/10 | 10/10 | 0/10 | 9/10 | 0.950 |
| 1 | dynamic | 10 | 0.850 | 0.166 | 6/10 | 10/10 | 4/10 | 7/10 | 0.875 |
| 5 | fixed | 10 | 0.025 | 0.075 | 0/10 | 10/10 | 10/10 | 10/10 | 0.875 |
| 5 | dynamic | 10 | 0.000 | 0.000 | 0/10 | 10/10 | 10/10 | 9/10 | 0.925 |
| 7 | fixed | 10 | 0.000 | 0.000 | 2/10 | 10/10 | 8/10 | 7/10 | 0.500 |
| 7 | dynamic | 10 | 0.000 | 0.000 | 0/10 | 9/10 | 9/10 | 6/10 | 0.125 |
| 25 | fixed | 10 | 0.675 | 0.195 | 8/10 | 10/10 | 2/10 | 6/10 | 0.800 |
| 25 | dynamic | 10 | 0.675 | 0.251 | 8/10 | 9/10 | 1/10 | 8/10 | 0.850 |

## Paired fixed-minus-dynamic differences

| Task | Majority-correct rate difference | Wrong-consensus rate difference | AI disclosure mean difference |
|---:|---:|---:|---:|
| 1 | +0.400 | -0.400 | +0.050 |
| 5 | +0.000 | +0.000 | +0.025 |
| 7 | +0.200 | -0.100 | +0.000 |
| 25 | +0.000 | +0.100 | +0.000 |

## AI-rule agreement

The AI auditor and lexical-semantic-v2 disagreed on 84 fact-level judgments. Every disagreement is exported with both evidence trails for manual review.

## Interpretation boundary

This representative repeated study is descriptive. It does not establish general superiority of either speaking mechanism, and it is not a same-model reproduction of the original HiddenBench paper.
