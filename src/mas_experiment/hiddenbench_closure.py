"""Derive bounded, traceable closure evidence from frozen HiddenBench runs.

This module deliberately reports only evidence that can be reconstructed from
the frozen confirmatory run and atomic-disclosure audit files.  It does not
turn model-based disclosure judgments into human-review conclusions.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


CONFIRMATORY_RECORDS = Path("artifacts/hiddenbench-confirmatory-20260804.jsonl")
CONFIRMATORY_AUDITS = Path("artifacts/hiddenbench-confirmatory-20260804.audits.jsonl")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _correct_count(
    records: list[dict[str, Any]],
    *,
    condition: str,
    vote_field: str,
) -> dict[int, tuple[int, int]]:
    totals: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        key = record["key"]
        if key["condition"] != condition:
            continue
        run = record["run"]
        votes = run[vote_field]
        if votes is None:
            raise ValueError(f"missing {vote_field} for {key}")
        task_id = key["task_id"]
        correct_answer = run["task"]["correct_answer"]
        totals[task_id][0] += sum(
            vote["vote"] == correct_answer for vote in votes
        ) > len(votes) / 2
        totals[task_id][1] += 1
    return {task_id: (value[0], value[1]) for task_id, value in totals.items()}


def _format_count(value: tuple[int, int]) -> str:
    return f"{value[0]}/{value[1]}"


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    half = (
        z
        * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
        / denominator
    )
    return max(0.0, centre - half), min(1.0, centre + half)


def _single_agent_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    local = _correct_count(
        records,
        condition="single-local",
        vote_field="hidden_post_votes",
    )
    full_profile = _correct_count(
        records,
        condition="single-local",
        vote_field="full_profile_votes",
    )
    fixed_60 = _correct_count(
        records,
        condition="fixed-60",
        vote_field="hidden_post_votes",
    )
    task_ids = (1, 2, 3)
    if set(local) != set(task_ids) or set(full_profile) != set(task_ids) or set(fixed_60) != set(task_ids):
        raise ValueError("frozen matrix does not contain the expected three tasks")
    by_task = [
        {
            "task_id": task_id,
            "single_local": _format_count(local[task_id]),
            "single_full_profile": _format_count(full_profile[task_id]),
            "fixed_60_multi_agent": _format_count(fixed_60[task_id]),
        }
        for task_id in task_ids
    ]

    def total(values: dict[int, tuple[int, int]]) -> str:
        return _format_count(
            (sum(item[0] for item in values.values()), sum(item[1] for item in values.values()))
        )

    model_names = {
        vote["provider_metadata"].get("model")
        for record in records
        if record["key"]["condition"] == "single-local"
        for vote_phase in (
            record["run"]["hidden_post_votes"],
            record["run"]["full_profile_votes"],
        )
        for vote in vote_phase
    }
    if model_names != {"deepseek-v4-flash"}:
        raise ValueError(f"unexpected single-agent model set: {model_names!r}")
    return {
        "scope": {
            "task_ids": list(task_ids),
            "repetitions": 10,
            "model": "deepseek-v4-flash",
        },
        "overall": {
            "single_local": total(local),
            "single_full_profile": total(full_profile),
            "fixed_60_multi_agent": total(fixed_60),
        },
        "by_task": by_task,
        "interpretation_boundary": (
            "single_full_profile is the no-discussion full-information vote "
            "stored inside each single-local run, not a separate new API run"
        ),
    }


def _ordinary_60_disclosure(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the model-assisted atomic audit for ordinary 60-turn chats."""
    conditions = ("fixed-60", "dynamic-60")
    task_ids = (1, 2, 3)
    totals: dict[str, dict[int, list[int]]] = {
        condition: {task_id: [0, 0, 0] for task_id in task_ids}
        for condition in conditions
    }

    for audit in audits:
        key = audit["study_key"]
        condition = key["condition"]
        if condition not in totals:
            continue
        task_id = key["task_id"]
        if task_id not in totals[condition]:
            raise ValueError(f"unexpected ordinary-disclosure task: {key!r}")
        fact_count = len(audit["facts"])
        disclosed_count = sum(judgment["disclosed"] for judgment in audit["judgments"])
        if fact_count != len(audit["judgments"]):
            raise ValueError(f"atomic audit fact/judgment mismatch for {key!r}")
        bucket = totals[condition][task_id]
        bucket[0] += disclosed_count
        bucket[1] += fact_count
        bucket[2] += 1

    by_condition: list[dict[str, Any]] = []
    for condition in conditions:
        by_task: list[dict[str, Any]] = []
        disclosed_total = 0
        fact_total = 0
        for task_id in task_ids:
            disclosed, facts, runs = totals[condition][task_id]
            if (facts, runs) != (40, 10):
                raise ValueError(
                    f"ordinary-disclosure matrix drift for {condition}/ID{task_id}: "
                    f"{facts} facts across {runs} runs"
                )
            by_task.append(
                {
                    "task_id": task_id,
                    "disclosed": disclosed,
                    "total": facts,
                    "rate": disclosed / facts,
                }
            )
            disclosed_total += disclosed
            fact_total += facts
        by_condition.append(
            {
                "condition": condition,
                "by_task": by_task,
                "overall": {
                    "disclosed": disclosed_total,
                    "total": fact_total,
                    "rate": disclosed_total / fact_total,
                },
            }
        )

    return {
        "scope": {
            "conditions": list(conditions),
            "task_ids": list(task_ids),
            "repetitions": 10,
            "atomic_facts_per_run": 4,
            "audit_type": "model-assisted atomic disclosure audit",
        },
        "by_condition": by_condition,
    }


def _ai_disclosure_crosscheck(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the audit model's stored rate with deterministic recomputation."""
    conditions = ("fixed-60", "dynamic-60")
    task_ids = (1, 2, 3)
    buckets: dict[str, dict[int, list[float | int]]] = {
        condition: {task_id: [0.0, 0.0, 0, 0] for task_id in task_ids}
        for condition in conditions
    }
    for audit in audits:
        key = audit["study_key"]
        condition = key["condition"]
        if condition not in buckets or key["task_id"] not in task_ids:
            continue
        judgments = audit["judgments"]
        if not judgments:
            raise ValueError(f"empty disclosure audit: {key!r}")
        ai_rate = float(audit["disclosure_rate"])
        recomputed_rate = sum(
            bool(judgment["disclosed"]) for judgment in judgments
        ) / len(judgments)
        bucket = buckets[condition][key["task_id"]]
        bucket[0] += ai_rate * len(judgments)
        bucket[1] += recomputed_rate * len(judgments)
        bucket[2] += len(judgments)
        bucket[3] += int(abs(ai_rate - recomputed_rate) > 1e-12)

    by_condition: list[dict[str, Any]] = []
    for condition in conditions:
        by_task: list[dict[str, Any]] = []
        ai_total = recomputed_total = fact_total = mismatched_runs = 0
        for task_id in task_ids:
            ai_sum, recomputed_sum, facts, mismatches = buckets[condition][task_id]
            if facts != 40 or mismatches > 0:
                raise ValueError(
                    f"AI disclosure cross-check drift for {condition}/ID{task_id}"
                )
            by_task.append(
                {
                    "task_id": task_id,
                    "ai_reported_rate": ai_sum / facts,
                    "program_recomputed_rate": recomputed_sum / facts,
                    "rate_difference": (ai_sum - recomputed_sum) / facts,
                    "audit_runs": 10,
                    "mismatched_runs": int(mismatches),
                }
            )
            ai_total += ai_sum
            recomputed_total += recomputed_sum
            fact_total += int(facts)
            mismatched_runs += int(mismatches)
        by_condition.append(
            {
                "condition": condition,
                "by_task": by_task,
                "overall": {
                    "ai_reported_rate": ai_total / fact_total,
                    "program_recomputed_rate": recomputed_total / fact_total,
                    "rate_difference": (ai_total - recomputed_total) / fact_total,
                    "audit_runs": 30,
                    "mismatched_runs": mismatched_runs,
                },
            }
        )
    return {
        "scope": {
            "conditions": list(conditions),
            "task_ids": list(task_ids),
            "repetitions": 10,
            "audit_model_field": "disclosure_rate",
            "program_rule": "sum(disclosed=true) / number_of_judgments",
        },
        "by_condition": by_condition,
    }


def _correctness_stratified_disclosure(
    records: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe disclosure rates separately for correct and incorrect runs."""
    record_map = {
        (
            record["key"]["task_id"],
            record["key"]["condition"],
            record["key"]["repetition"],
        ): record
        for record in records
    }
    buckets: dict[str, dict[bool, list[float]]] = {
        condition: {True: [], False: []}
        for condition in ("fixed-60", "dynamic-60")
    }
    for audit in audits:
        key = audit["study_key"]
        condition = key["condition"]
        if condition not in buckets:
            continue
        record = record_map[(key["task_id"], condition, key["repetition"])]
        correct = bool(record["run"]["metrics"]["post_majority_correct"])
        buckets[condition][correct].append(float(audit["disclosure_rate"]))

    by_condition: list[dict[str, Any]] = []
    for condition, groups in buckets.items():
        correct_rates = groups[True]
        incorrect_rates = groups[False]
        if not correct_rates or not incorrect_rates:
            raise ValueError(f"missing correctness stratum for {condition}")
        by_condition.append(
            {
                "condition": condition,
                "correct_runs": len(correct_rates),
                "correct_mean_disclosure_rate": sum(correct_rates) / len(correct_rates),
                "incorrect_runs": len(incorrect_rates),
                "incorrect_mean_disclosure_rate": sum(incorrect_rates)
                / len(incorrect_rates),
            }
        )
    return {
        "scope": {
            "conditions": ["fixed-60", "dynamic-60"],
            "task_ids": [1, 2, 3],
            "repetitions": 10,
            "stratifier": "run.metrics.post_majority_correct",
        },
        "by_condition": by_condition,
    }


def _selector_formula() -> dict[str, Any]:
    """Expose the exact deterministic five-factor selector used in the runs."""
    return {
        "score_formula": (
            "S_i = 0.30 d_i + 0.30 u_i + 0.15 r_i + 0.15 q_i + 0.10 w_i"
        ),
        "factors": [
            {
                "symbol": "d_i",
                "name": "disagreement",
                "weight": 0.30,
                "definition": "1 if the agent's latest stance differs from the current plurality; 0.5 if no unique plurality exists; otherwise 0",
            },
            {
                "symbol": "u_i",
                "name": "undisclosed",
                "weight": 0.30,
                "definition": "fraction of the agent's private atoms not yet matched in its owner-authored public messages",
            },
            {
                "symbol": "r_i",
                "name": "related_discussion",
                "weight": 0.15,
                "definition": "1 when new messages mention an answer option related to one of the agent's undisclosed atoms; otherwise 0",
            },
            {
                "symbol": "q_i",
                "name": "response_due",
                "weight": 0.15,
                "definition": "1 when another owner has newly disclosed a cross-agent atom since this agent last spoke; otherwise 0",
            },
            {
                "symbol": "w_i",
                "name": "waiting",
                "weight": 0.10,
                "definition": "normalized turns since the agent last spoke",
            },
        ],
        "tie_break_order": [
            "weighted_total descending",
            "remaining_quota descending",
            "raw_waiting descending",
            "agent_id ascending",
        ],
        "normalization": "All five factor values are in [0,1]; weights sum to 1.0.",
    }


def _disclosure_timing(
    records: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize first owner-authored disclosure rounds for labeled facts."""
    record_map = {
        (
            record["key"]["task_id"],
            record["key"]["condition"],
            record["key"]["repetition"],
        ): record
        for record in records
    }
    grouped: dict[str, list[int]] = {"fixed-60": [], "dynamic-60": []}
    for audit in audits:
        key = audit["study_key"]
        condition = key["condition"]
        if condition not in grouped:
            continue
        record = record_map[(key["task_id"], condition, key["repetition"])]
        message_round = {
            message["message_id"]: message["round_index"]
            for message in record["run"]["discussion_messages"]
        }
        for judgment in audit["judgments"]:
            if not judgment["disclosed"]:
                continue
            rounds = [
                message_round[message_id]
                for message_id in judgment["evidence_message_ids"]
                if message_id in message_round
            ]
            if not rounds:
                raise ValueError(
                    f"disclosed judgment lacks message-round evidence: {audit['study_key']!r}"
                )
            grouped[condition].append(min(rounds))

    result: list[dict[str, Any]] = []
    for condition in ("fixed-60", "dynamic-60"):
        rounds = grouped[condition]
        if not rounds:
            raise ValueError(f"no disclosure timing observations for {condition}")
        counts: dict[int, int] = {}
        for round_index in rounds:
            counts[round_index] = counts.get(round_index, 0) + 1
        result.append(
            {
                "condition": condition,
                "disclosed_facts": len(rounds),
                "first_round_count": counts.get(1, 0),
                "later_round_count": len(rounds) - counts.get(1, 0),
                "mean_first_disclosure_round": sum(rounds) / len(rounds),
                "median_first_disclosure_round": sorted(rounds)[len(rounds) // 2]
                if len(rounds) % 2
                else (sorted(rounds)[len(rounds) // 2 - 1] + sorted(rounds)[len(rounds) // 2]) / 2,
                "first_round_counts": [
                    {"round": round_index, "count": counts[round_index]}
                    for round_index in sorted(counts)
                ],
            }
        )
    return {
        "definition": (
            "Timing is conditional on a fact already labeled disclosed=true; "
            "the first round is the minimum round_index among cited owner-authored evidence messages."
        ),
        "by_condition": result,
    }


def _paired_comparisons(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify matched inputs and expose discordant counts for paired tests."""
    comparisons = (
        ("fixed-60", "dynamic-60"),
        ("fixed-reveal-all", "dynamic-reveal-all"),
        ("fixed-12", "structured-12"),
    )
    result: list[dict[str, Any]] = []
    for left_condition, right_condition in comparisons:
        left = {
            (record["key"]["task_id"], record["key"]["repetition"]): record
            for record in records
            if record["key"]["condition"] == left_condition
        }
        right = {
            (record["key"]["task_id"], record["key"]["repetition"]): record
            for record in records
            if record["key"]["condition"] == right_condition
        }
        if set(left) != set(right) or len(left) != 30:
            raise ValueError(f"paired matrix drift for {left_condition} vs {right_condition}")
        a_only = 0
        b_only = 0
        left_successes = 0
        right_successes = 0
        same_pair_seed = 0
        same_assignment = 0
        for pair_key in sorted(left):
            left_record = left[pair_key]
            right_record = right[pair_key]
            if left_record["pair_seed"] == right_record["pair_seed"]:
                same_pair_seed += 1
            if left_record["assignment_fingerprint"] == right_record["assignment_fingerprint"]:
                same_assignment += 1
            left_votes = left_record["run"]["hidden_post_votes"]
            right_votes = right_record["run"]["hidden_post_votes"]
            correct_answer = left_record["run"]["task"]["correct_answer"]
            left_correct = sum(vote["vote"] == correct_answer for vote in left_votes) > len(left_votes) / 2
            right_correct = sum(vote["vote"] == correct_answer for vote in right_votes) > len(right_votes) / 2
            left_successes += left_correct
            right_successes += right_correct
            if left_correct and not right_correct:
                a_only += 1
            if right_correct and not left_correct:
                b_only += 1
        result.append(
            {
                "condition_a": left_condition,
                "condition_b": right_condition,
                "pairs": len(left),
                "same_pair_seed": same_pair_seed,
                "same_assignment_fingerprint": same_assignment,
                "a_only": a_only,
                "b_only": b_only,
                "discordant": a_only + b_only,
                "a_correct": left_successes,
                "b_correct": right_successes,
                "test": "two-sided exact McNemar (binomial test on discordant pairs)",
            }
        )
    return {
        "pair_key": "task_id + repetition",
        "result": result,
        "generation_note": (
            "Pairing controls task, fact assignment, and protocol inputs; the model backend does not receive a synchronized generation seed."
        ),
    }


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repeat_stability(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the ten frozen repetitions task by task.

    The summary deliberately reports the observed sequence of correct/incorrect
    majority outcomes rather than collapsing all runs into one overall rate.
    This makes it possible to distinguish a consistently correct task from a
    task whose aggregate rate is driven by mixed outcomes.
    """
    conditions = ("fixed-60", "dynamic-60")
    task_ids = (1, 2, 3)
    by_condition: list[dict[str, Any]] = []
    for condition in conditions:
        by_task: list[dict[str, Any]] = []
        for task_id in task_ids:
            subset = sorted(
                (
                    record
                    for record in records
                    if record["key"]["condition"] == condition
                    and record["key"]["task_id"] == task_id
                ),
                key=lambda record: record["key"]["repetition"],
            )
            if [record["key"]["repetition"] for record in subset] != list(range(10)):
                raise ValueError(
                    f"expected repetitions 0..9 for {condition}/ID{task_id}"
                )
            outcomes: list[bool] = []
            for record in subset:
                votes = record["run"]["hidden_post_votes"]
                correct_answer = record["run"]["task"]["correct_answer"]
                outcomes.append(
                    sum(vote["vote"] == correct_answer for vote in votes)
                    > len(votes) / 2
                )
            correct_runs = sum(outcomes)
            wilson_low, wilson_high = _wilson_interval(correct_runs, len(outcomes))
            by_task.append(
                {
                    "task_id": task_id,
                    "correct_runs": correct_runs,
                    "incorrect_runs": len(outcomes) - correct_runs,
                    "total_runs": len(outcomes),
                    "rate": correct_runs / len(outcomes),
                    "wilson_95_low": wilson_low,
                    "wilson_95_high": wilson_high,
                    "outcome_sequence": ["C" if outcome else "I" for outcome in outcomes],
                }
            )
        total_correct = sum(item["correct_runs"] for item in by_task)
        total_runs = sum(item["total_runs"] for item in by_task)
        overall_low, overall_high = _wilson_interval(total_correct, total_runs)
        by_condition.append(
            {
                "condition": condition,
                "by_task": by_task,
                "overall": {
                    "correct_runs": total_correct,
                    "incorrect_runs": total_runs - total_correct,
                    "total_runs": total_runs,
                    "rate": total_correct / total_runs,
                    "wilson_95_low": overall_low,
                    "wilson_95_high": overall_high,
                },
            }
        )
    return {
        "scope": {
            "conditions": list(conditions),
            "task_ids": list(task_ids),
            "repetitions_per_task": 10,
            "vote_field": "hidden_post_votes",
            "outcome_encoding": "C=majority correct, I=majority incorrect",
        },
        "by_condition": by_condition,
    }


def _public_speech_budget(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe the public-message match and the intentionally unmatched calls.

    The fixed and dynamic conditions both expose 60 public messages to the
    participants.  fixed-60 additionally collects four private diagnostic
    votes after each of 15 rounds; these are never appended to public history.
    """
    conditions = ("fixed-60", "dynamic-60")
    expected_task_ids = {1, 2, 3}
    by_condition: list[dict[str, Any]] = []
    for condition in conditions:
        subset = [
            record
            for record in records
            if record["key"]["condition"] == condition
        ]
        if len(subset) != 30:
            raise ValueError(
                f"expected 30 {condition} records, got {len(subset)}"
            )
        if {record["key"]["task_id"] for record in subset} != expected_task_ids:
            raise ValueError(f"unexpected task matrix for {condition}")

        public_message_counts = {
            len(record["run"]["discussion_messages"])
            for record in subset
        }
        per_agent_counts = {
            tuple(
                sum(
                    message["agent_id"] == agent_id
                    for message in record["run"]["discussion_messages"]
                )
                for agent_id in ("agent-a", "agent-b", "agent-c", "agent-d")
            )
            for record in subset
        }
        logical_slots = {
            int(record["run"]["provider_metadata"]["logical_response_slots"])
            for record in subset
        }
        api_distribution: dict[int, int] = {}
        for record in subset:
            api_requests = int(
                record["run"]["provider_metadata"]["api_requests"]
            )
            api_distribution[api_requests] = (
                api_distribution.get(api_requests, 0) + 1
            )
        selector_calls = {
            int(record["run"]["provider_metadata"].get("selector_llm_calls", 0))
            for record in subset
        }
        shadow_counts = {
            len(record.get("shadow_checkpoints", []))
            for record in subset
        }
        if public_message_counts != {60} or per_agent_counts != {(15, 15, 15, 15)}:
            raise ValueError(f"public speech budget drift for {condition}")
        if len(logical_slots) != 1 or selector_calls != {0} or len(shadow_counts) != 1:
            raise ValueError(f"response accounting drift for {condition}")

        checkpoints = next(iter(shadow_counts))
        expected_shadow_calls = checkpoints * 4
        by_condition.append(
            {
                "condition": condition,
                "runs": len(subset),
                "logical_response_slots_per_run": next(iter(logical_slots)),
                "shadow_vote_calls_per_run": expected_shadow_calls,
                "selector_llm_calls_per_run": next(iter(selector_calls)),
                "api_request_distribution": dict(sorted(api_distribution.items())),
            }
        )

    if by_condition != [
        {
            "condition": "fixed-60",
            "runs": 30,
            "logical_response_slots_per_run": 132,
            "shadow_vote_calls_per_run": 60,
            "selector_llm_calls_per_run": 0,
            "api_request_distribution": {132: 29, 133: 1},
        },
        {
            "condition": "dynamic-60",
            "runs": 30,
            "logical_response_slots_per_run": 72,
            "shadow_vote_calls_per_run": 0,
            "selector_llm_calls_per_run": 0,
            "api_request_distribution": {72: 30},
        },
    ]:
        raise ValueError("frozen public-speech accounting drifted")

    return {
        "scope": {
            "task_ids": [1, 2, 3],
            "repetitions": 10,
            "agents": 4,
            "public_messages_per_run": 60,
            "public_messages_per_agent": 15,
        },
        "by_condition": by_condition,
    }


def _record_by_run_id(records: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    matches = [record for record in records if record["run"]["run_id"] == run_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frozen record for {run_id}, got {len(matches)}")
    return matches[0]


def _audit_by_study_key(audits: list[dict[str, Any]]) -> dict[tuple[int, str, int], dict[str, Any]]:
    result: dict[tuple[int, str, int], dict[str, Any]] = {}
    for audit in audits:
        key = audit["study_key"]
        study_key = (key["task_id"], key["condition"], key["repetition"])
        if study_key in result:
            raise ValueError(f"duplicate atomic-disclosure audit for {study_key!r}")
        result[study_key] = audit
    return result


def _study_key(record: dict[str, Any]) -> dict[str, Any]:
    key = record["key"]
    return {
        "task_id": key["task_id"],
        "condition": key["condition"],
        "repetition": key["repetition"],
    }


def _audit_for(record: dict[str, Any], audits: dict[tuple[int, str, int], dict[str, Any]]) -> dict[str, Any]:
    key = _study_key(record)
    try:
        return audits[(key["task_id"], key["condition"], key["repetition"])]
    except KeyError as error:
        raise ValueError(f"missing atomic-disclosure audit for {key!r}") from error


def _message(record: dict[str, Any], message_id: str) -> dict[str, Any]:
    messages = [
        message
        for message in record["run"]["discussion_messages"]
        if message["message_id"] == message_id
    ]
    if len(messages) != 1:
        raise ValueError(f"expected one message {message_id}, got {len(messages)}")
    return messages[0]


def _post_rationale(record: dict[str, Any], agent_id: str) -> str:
    votes = [
        vote
        for vote in record["run"]["hidden_post_votes"]
        if vote["agent_id"] == agent_id
    ]
    if len(votes) != 1:
        raise ValueError(f"expected one post vote for {agent_id}")
    return votes[0]["rationale"]


def _facts_from_audit(audit: dict[str, Any], *, disclosed: bool) -> list[dict[str, Any]]:
    fact_by_id = {fact["fact_id"]: fact for fact in audit["facts"]}
    selected: list[dict[str, Any]] = []
    for judgment in audit["judgments"]:
        if judgment["disclosed"] != disclosed:
            continue
        fact = fact_by_id[judgment["fact_id"]]
        selected.append(
            {
                "fact_id": fact["fact_id"],
                "owner_agent_id": fact["owner_agent_id"],
                "fact": fact["text"],
                "disclosed": judgment["disclosed"],
                "evidence_message_ids": judgment["evidence_message_ids"],
                "evidence_quote": judgment["evidence_quote"],
                "audit_reason": judgment["reason"],
            }
        )
    return selected


def _causal_cards(records: list[dict[str, Any]], audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_map = _audit_by_study_key(audits)

    not_disclosed = _record_by_run_id(records, "0d078a3c85f64262")
    not_disclosed_audit = _audit_for(not_disclosed, audit_map)
    undisclosed_facts = _facts_from_audit(not_disclosed_audit, disclosed=False)
    not_disclosed_card = {
        "mechanism": "information_not_disclosed",
        "run_id": not_disclosed["run"]["run_id"],
        "study_key": _study_key(not_disclosed),
        "correct_answer": not_disclosed["run"]["task"]["correct_answer"],
        "final_votes": [vote["vote"] for vote in not_disclosed["run"]["hidden_post_votes"]],
        "facts": undisclosed_facts,
        "undisclosed_fact_count": len(undisclosed_facts),
        "final_rationales": [
            vote["rationale"] for vote in not_disclosed["run"]["hidden_post_votes"]
        ],
        "conclusion_boundary": (
            "The frozen atomic audit finds two route-blocking facts absent from "
            "their owners' public messages. This supports an output-level "
            "non-disclosure observation, not a complete causal attribution."
        ),
        "selection_rule": (
            "固定检索规则：按 task_id=2、condition=fixed-60 的 repetition 升序扫描，选择第一个多数投票错误且至少一条所有者事实被审计为未披露的运行。"
        ),
    }
    if not_disclosed_card["undisclosed_fact_count"] != 2:
        raise ValueError("representative non-disclosure card drifted")

    misinterpreted = _record_by_run_id(records, "e46521e6691a10ca")
    misinterpreted_audit = _audit_for(misinterpreted, audit_map)
    if not all(judgment["disclosed"] for judgment in misinterpreted_audit["judgments"]):
        raise ValueError("representative interpretation card no longer has full disclosure")
    injected_message = _message(misinterpreted, "e0528435edaa8576")
    contradiction_message = _message(misinterpreted, "b5a31c876a93aea6")
    contradictory_final_rationale = _post_rationale(misinterpreted, "agent-b")
    misinterpreted_card = {
        "mechanism": "evidence_misinterpreted",
        "run_id": misinterpreted["run"]["run_id"],
        "study_key": _study_key(misinterpreted),
        "correct_answer": misinterpreted["run"]["task"]["correct_answer"],
        "all_atomic_facts_disclosed": True,
        "injected_evidence_message_id": injected_message["message_id"],
        "injected_evidence_quote": "The supply truck headed to the village from East Town was stuck in the tunnel.",
        "contradictory_message_id": contradiction_message["message_id"],
        "contradictory_message_quote": contradiction_message["content"],
        "contradictory_final_rationale": contradictory_final_rationale,
        "final_votes": [vote["vote"] for vote in misinterpreted["run"]["hidden_post_votes"]],
        "conclusion_boundary": (
            "The outputs contain a direct contradiction between a mechanically "
            "injected fact that the truck was stuck in the tunnel and later "
            "claims that the tunnel was clear. It is an output-level "
            "misinterpretation signal; human coding is still required before "
            "asserting an internal causal mechanism."
        ),
        "selection_rule": (
            "固定检索规则：按 task_id=2、condition=fixed-reveal-all 的 repetition 升序扫描，选择第一个四条事实均披露、最终多数错误且后续输出与注入事实直接矛盾的运行。"
        ),
    }
    if "tunnel is clear" not in contradictory_final_rationale.casefold():
        raise ValueError("representative interpretation rationale drifted")

    not_used = _record_by_run_id(records, "bfba1db7a056ebea")
    not_used_audit = _audit_for(not_used, audit_map)
    if not all(judgment["disclosed"] for judgment in not_used_audit["judgments"]):
        raise ValueError("representative evidence-use card no longer has full disclosure")
    late_evidence = _message(not_used, "d85fde011965a482")
    follow_up = _message(not_used, "b8dd85f9f7bf206d")
    not_used_card = {
        "mechanism": "evidence_not_used_after_disclosure",
        "run_id": not_used["run"]["run_id"],
        "study_key": _study_key(not_used),
        "correct_answer": not_used["run"]["task"]["correct_answer"],
        "all_atomic_facts_disclosed": True,
        "late_evidence_message_id": late_evidence["message_id"],
        "late_evidence_quote": late_evidence["content"],
        "follow_up_message_id": follow_up["message_id"],
        "follow_up_quote": follow_up["content"],
        "final_votes": [vote["vote"] for vote in not_used["run"]["hidden_post_votes"]],
        "final_rationales": [
            vote["rationale"] for vote in not_used["run"]["hidden_post_votes"]
        ],
        "conclusion_boundary": (
            "All four facts were marked disclosed, and late messages jointly "
            "state that both North Hill access routes require verification or are "
            "blocked, yet the final action remains North Hill. This is evidence "
            "that disclosed evidence was not consistently carried into the final "
            "action; human coding must distinguish non-use from misinterpretation."
        ),
        "selection_rule": (
            "固定检索规则：按 task_id=3、condition=fixed-60 的 repetition 升序扫描，选择第一个四条事实均披露、最终多数错误且晚到证据仍指出路径受阻或需验证的运行。"
        ),
    }
    if "walking trails are closed" not in not_used_card["late_evidence_quote"].casefold():
        raise ValueError("representative evidence-use quote drifted")
    return [not_disclosed_card, misinterpreted_card, not_used_card]


def _prompt_example(
    records: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract one filled audit prompt example from the frozen JSONL pair."""
    record = next(
        record
        for record in records
        if record["key"]
        == {"task_id": 2, "condition": "fixed-60", "repetition": 0}
    )
    audit = next(
        audit
        for audit in audits
        if audit["study_key"]
        == {"task_id": 2, "condition": "fixed-60", "repetition": 0}
    )
    private_information = record["run"]["assignment"]["private_information"]
    facts = [
        {
            "fact_id": fact["fact_id"],
            "owner_agent_id": fact["owner_agent_id"],
            "claim": fact["text"],
        }
        for fact in audit["facts"]
    ]
    public_messages = [
        {
            "message_id": message["message_id"],
            "agent_id": message["agent_id"],
            "content": message["content"],
        }
        for message in record["run"]["discussion_messages"][:4]
    ]
    discussion_message = next(
        message
        for message in record["run"]["discussion_messages"]
        if message["agent_id"] == "agent-b" and message["round_index"] == 1
    )
    judgments = [
        {
            "fact_id": judgment["fact_id"],
            "owner_agent_id": judgment["owner_agent_id"],
            "disclosed": judgment["disclosed"],
            "evidence_message_ids": judgment["evidence_message_ids"],
            "evidence_quote": judgment["evidence_quote"],
            "reason": judgment["reason"],
        }
        for judgment in audit["judgments"]
    ]
    if len(facts) != 4 or len(judgments) != 4:
        raise ValueError("filled prompt example must contain four atomic facts and judgments")
    return {
        "study_key": {
            "task_id": 2,
            "condition": "fixed-60",
            "repetition": 0,
        },
        "run_id": record["run"]["run_id"],
        "public_message_count": len(record["run"]["discussion_messages"]),
        "private_facts": facts,
        "private_information_by_owner": private_information,
        "public_messages_excerpt": public_messages,
        "judgments": judgments,
        "audit_disclosure_rate": audit["disclosure_rate"],
        "discussion_turn": {
            "message_id": discussion_message["message_id"],
            "round_index": discussion_message["round_index"],
            "agent_id": discussion_message["agent_id"],
            "system_prompt": discussion_message["system_prompt"],
            "user_prompt": discussion_message["user_prompt"],
            "actual_output": discussion_message["content"],
            "model": discussion_message["provider_metadata"]["model"],
            "temperature": discussion_message["provider_metadata"]["temperature"],
            "thinking": discussion_message["provider_metadata"]["thinking"],
        },
    }


def build_closure_evidence(root: Path) -> dict[str, Any]:
    """Build the bounded closure snapshot from frozen JSONL evidence."""
    root = root.resolve()
    records = _read_jsonl(root / CONFIRMATORY_RECORDS)
    audits = _read_jsonl(root / CONFIRMATORY_AUDITS)
    return {
        "schema_version": "hiddenbench-closure-evidence-v2",
        "source_artifacts": {
            "confirmatory_records": str(CONFIRMATORY_RECORDS).replace("\\", "/"),
            "atomic_disclosure_audits": str(CONFIRMATORY_AUDITS).replace("\\", "/"),
        },
        "single_agent_comparison": _single_agent_comparison(records),
        "ordinary_60_disclosure": _ordinary_60_disclosure(audits),
        "ai_disclosure_crosscheck": _ai_disclosure_crosscheck(audits),
        "repeat_stability": _repeat_stability(records),
        "correctness_stratified_disclosure": _correctness_stratified_disclosure(
            records, audits
        ),
        "disclosure_timing": _disclosure_timing(records, audits),
        "paired_comparisons": _paired_comparisons(records),
        "public_speech_budget": _public_speech_budget(records),
        "causal_cards": _causal_cards(records, audits),
        "prompt_example": _prompt_example(records, audits),
        "selector_formula": _selector_formula(),
        "protocol_clarifications": {
            "ordinary_disclosure": (
                "Under ordinary conditions each agent holds one private fact. "
                "The pair seed randomizes fact assignment and fact order only; "
                "turn order is fixed by the protocol, and disclosure is neither "
                "randomized nor mechanically forced: the model decides whether "
                "and how to mention its fact in a public turn."
            ),
            "reveal_all": (
                "Only Reveal-All mechanically appends private facts to public "
                "messages; it is a diagnostic information-availability condition."
            ),
            "fixed_60_continuation": (
                "fixed-60 retains 15 rounds × 4 agents by design. The frozen data "
                "do not establish a separately measured early-consensus effect; "
                "continuing the diagnostic protocol lets us observe late evidence, "
                "correction, stance changes, and final-vote stability. It is not an "
                "early-stopping policy."
            ),
        },
        "boundaries": {
            "human_review": "pending_real_human_double_blind_review",
            "model_framework_decoupling": "pending_gpt41_or_equivalent_api_access",
            "ai_disclosure_audit": (
                "The frozen disclosure labels were produced by a model-assisted "
                "atomic audit and are not human gold-standard labels."
            ),
        },
        "source_sha256": {
            str(CONFIRMATORY_RECORDS).replace("\\", "/"): _source_sha256(root / CONFIRMATORY_RECORDS),
            str(CONFIRMATORY_AUDITS).replace("\\", "/"): _source_sha256(root / CONFIRMATORY_AUDITS),
        },
    }
