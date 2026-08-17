"""Derive bounded, traceable closure evidence from frozen HiddenBench runs.

This module deliberately reports only evidence that can be reconstructed from
the frozen confirmatory run and atomic-disclosure audit files.  It does not
turn model-based disclosure judgments into human-review conclusions.
"""

from __future__ import annotations

import json
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
    }
    if "walking trails are closed" not in not_used_card["late_evidence_quote"].casefold():
        raise ValueError("representative evidence-use quote drifted")
    return [not_disclosed_card, misinterpreted_card, not_used_card]


def build_closure_evidence(root: Path) -> dict[str, Any]:
    """Build the bounded closure snapshot from frozen JSONL evidence."""
    root = root.resolve()
    records = _read_jsonl(root / CONFIRMATORY_RECORDS)
    audits = _read_jsonl(root / CONFIRMATORY_AUDITS)
    return {
        "schema_version": "hiddenbench-closure-evidence-v1",
        "source_artifacts": {
            "confirmatory_records": str(CONFIRMATORY_RECORDS).replace("\\", "/"),
            "atomic_disclosure_audits": str(CONFIRMATORY_AUDITS).replace("\\", "/"),
        },
        "single_agent_comparison": _single_agent_comparison(records),
        "causal_cards": _causal_cards(records, audits),
        "protocol_clarifications": {
            "ordinary_disclosure": (
                "Under ordinary conditions each agent holds one private fact. "
                "Disclosure is neither randomized nor mechanically forced: the "
                "model decides whether and how to mention its fact in a public "
                "turn."
            ),
            "reveal_all": (
                "Only Reveal-All mechanically appends private facts to public "
                "messages; it is a diagnostic information-availability condition."
            ),
            "fixed_60_continuation": (
                "fixed-60 retains 15 rounds × 4 agents even after early apparent "
                "agreement to observe late evidence, correction, stance changes, "
                "and final-vote stability. It is a diagnostic protocol, not an "
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
    }
