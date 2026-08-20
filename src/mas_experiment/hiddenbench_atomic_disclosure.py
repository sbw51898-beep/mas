from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_confirmatory_domain import ConfirmatoryStudyKey
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
    HiddenBenchRawRun,
)


REVEAL_ALL_HEADER = "SYSTEM MECHANICAL REVEAL-ALL"


class AtomicPrivateFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str = Field(min_length=12)
    task_id: int
    owner_agent_id: str
    source_packet_index: int = Field(ge=0)
    atomic_index: int = Field(ge=0)
    text: str = Field(min_length=1)


class AtomicDisclosureJudgment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str
    owner_agent_id: str
    disclosed: bool
    evidence_message_ids: tuple[str, ...]
    evidence_quote: str
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class AtomicDisclosureAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_key: ConfirmatoryStudyKey
    judge_model: str
    judge_prompt_version: str
    facts: tuple[AtomicPrivateFact, ...]
    judgments: tuple[AtomicDisclosureJudgment, ...]
    disclosure_rate: float = Field(ge=0, le=1)
    provider_metadata: dict[str, Any]

    @property
    def disclosure_percentage(self) -> float:
        return self.disclosure_rate * 100.0


def _atomic_texts(packet: str) -> tuple[str, ...]:
    lines = tuple(
        line.strip() for line in packet.splitlines() if line.strip()
    )
    if not any(line.startswith("-") for line in lines):
        return (packet.strip(),)

    heading = ""
    atoms: list[str] = []
    for line in lines:
        if line.startswith("-"):
            item = re.sub(r"^-+\s*", "", line).strip()
            text = f"{heading} {item}".strip() if heading else item
            atoms.append(text)
        else:
            heading = line
    return tuple(atoms) or (packet.strip(),)


def _fact_id(
    assignment: HiddenBenchAssignment,
    *,
    owner_agent_id: str,
    source_packet_index: int,
    atomic_index: int,
    text: str,
) -> str:
    payload = {
        "task_id": assignment.task_id,
        "owner_agent_id": owner_agent_id,
        "source_packet_index": source_packet_index,
        "source_packet": assignment.private_information[owner_agent_id],
        "atomic_index": atomic_index,
        "text": text,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "atomic-fact:" + hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()[:20]


def decompose_private_facts(
    assignment: HiddenBenchAssignment,
) -> tuple[AtomicPrivateFact, ...]:
    facts: list[AtomicPrivateFact] = []
    for packet_index, owner_agent_id in enumerate(AGENT_IDS):
        packet = assignment.private_information[owner_agent_id]
        for atomic_index, text in enumerate(_atomic_texts(packet)):
            facts.append(
                AtomicPrivateFact(
                    fact_id=_fact_id(
                        assignment,
                        owner_agent_id=owner_agent_id,
                        source_packet_index=packet_index,
                        atomic_index=atomic_index,
                        text=text,
                    ),
                    task_id=assignment.task_id,
                    owner_agent_id=owner_agent_id,
                    source_packet_index=packet_index,
                    atomic_index=atomic_index,
                    text=text,
                )
            )
    return tuple(facts)


def append_reveal_all_block(
    content: str,
    facts: tuple[AtomicPrivateFact, ...],
) -> tuple[str, tuple[str, ...]]:
    if not facts:
        return content, ()
    lines = [
        content.rstrip(),
        "",
        f"[{REVEAL_ALL_HEADER}]",
        "The following private facts are injected verbatim by the system:",
    ]
    lines.extend(f"- {fact.text}" for fact in facts)
    return "\n".join(lines), tuple(fact.fact_id for fact in facts)


_NEGATION = re.compile(
    r"\b(?:no|not|never|neither|nor|without|cannot|can't|isn't|wasn't|"
    r"doesn't|didn't|won't|wouldn't)\b",
    flags=re.IGNORECASE,
)


def _has_negation(text: str) -> bool:
    return bool(_NEGATION.search(text))


def validate_atomic_evidence(
    run: HiddenBenchRawRun,
    facts: tuple[AtomicPrivateFact, ...],
    judgments: tuple[AtomicDisclosureJudgment, ...],
) -> None:
    expected = {fact.fact_id: fact for fact in facts}
    by_fact = {judgment.fact_id: judgment for judgment in judgments}
    if (
        len(judgments) != len(expected)
        or len(by_fact) != len(judgments)
        or set(by_fact) != set(expected)
    ):
        raise ValueError("audit requires exactly one judgment per atomic fact")

    messages: dict[str, HiddenBenchMessage] = {
        message.message_id: message for message in run.discussion_messages
    }
    for fact_id, fact in expected.items():
        judgment = by_fact[fact_id]
        if judgment.owner_agent_id != fact.owner_agent_id:
            raise ValueError("judgment owner does not match atomic fact owner")
        if not judgment.disclosed:
            if judgment.evidence_message_ids or judgment.evidence_quote:
                raise ValueError("undisclosed judgment must not cite evidence")
            continue
        if not judgment.evidence_message_ids or not judgment.evidence_quote:
            raise ValueError("disclosed judgment requires owner-authored evidence")
        referenced: list[HiddenBenchMessage] = []
        for message_id in judgment.evidence_message_ids:
            message = messages.get(message_id)
            if message is None or message.agent_id != fact.owner_agent_id:
                raise ValueError("disclosed evidence must be owner-authored")
            referenced.append(message)
        if not any(
            judgment.evidence_quote in message.content
            for message in referenced
        ):
            raise ValueError(
                "evidence_quote must be an exact substring of a referenced message"
            )
        if _has_negation(fact.text) != _has_negation(
            judgment.evidence_quote
        ):
            raise ValueError("evidence quote reverses the fact polarity")


def mechanical_reveal_all_audit(
    run: HiddenBenchRawRun,
    *,
    study_key: ConfirmatoryStudyKey,
) -> AtomicDisclosureAudit:
    facts = decompose_private_facts(run.assignment)
    messages_by_fact: dict[str, HiddenBenchMessage] = {}
    for message in run.discussion_messages:
        appended = message.provider_metadata.get("appended_fact_ids", ())
        if not isinstance(appended, (list, tuple)):
            continue
        for fact_id in appended:
            if isinstance(fact_id, str):
                messages_by_fact[fact_id] = message

    judgments: list[AtomicDisclosureJudgment] = []
    for fact in facts:
        message = messages_by_fact.get(fact.fact_id)
        if message is None or fact.text not in message.content:
            raise ValueError(
                f"mechanical reveal evidence missing for {fact.fact_id}"
            )
        judgments.append(
            AtomicDisclosureJudgment(
                fact_id=fact.fact_id,
                owner_agent_id=fact.owner_agent_id,
                disclosed=True,
                evidence_message_ids=(message.message_id,),
                evidence_quote=fact.text,
                reason="System mechanically appended the exact atomic fact.",
                confidence=1.0,
            )
        )
    judgments_tuple = tuple(judgments)
    validate_atomic_evidence(run, facts, judgments_tuple)
    return AtomicDisclosureAudit(
        study_key=study_key,
        judge_model="mechanical-exact-match",
        judge_prompt_version="mechanical-reveal-all-v1",
        facts=facts,
        judgments=judgments_tuple,
        disclosure_rate=1.0,
        provider_metadata={
            "api_requests": 0,
            "repair_requests": 0,
            "mechanical_reveal_all": True,
            "local_evidence_reanchors": 0,
            "audit_code_commit": current_git_commit(),
        },
    )


ATOMIC_JUDGE_PROMPT_VERSION = "hiddenbench-atomic-disclosure-v1"


def build_atomic_disclosure_prompt(
    run: HiddenBenchRawRun,
    facts: tuple[AtomicPrivateFact, ...] | None = None,
) -> str:
    resolved_facts = facts or decompose_private_facts(run.assignment)
    facts_text = "\n".join(
        (
            f"- {fact.fact_id} | owner={fact.owner_agent_id} | "
            f"claim={json.dumps(fact.text, ensure_ascii=False)}"
        )
        for fact in resolved_facts
    )
    messages_text = "\n".join(
        f"{message.message_id} | {message.agent_id} | {message.content}"
        for message in run.discussion_messages
    )
    schema = {
        "facts": [
            {
                "fact_id": "atomic-fact:example",
                "owner_agent_id": "agent-a",
                "disclosed": True,
                "evidence_message_ids": ["message-id"],
                "evidence_quote": "exact substring",
                "reason": "short reason",
                "confidence": 0.95,
            }
        ]
    }
    return (
        "Determine whether every atomic private claim was disclosed in the "
        "public discussion.\n\n"
        "Rules:\n"
        "1. Only an owner-authored message can disclose that owner's fact.\n"
        "2. A faithful paraphrase counts; a polarity reversal, contradiction, "
        "or decision-relevant omission does not.\n"
        "3. For disclosed=true, cite at least one owner-authored message ID "
        "and copy one exact non-empty substring from it.\n"
        "4. For disclosed=false, return an empty message-ID list and quote.\n"
        "5. Return exactly one judgment for every fact ID. Do not calculate "
        "the percentage.\n\n"
        f"ATOMIC PRIVATE FACTS:\n{facts_text}\n\n"
        f"PUBLIC MESSAGES:\n{messages_text}\n\n"
        "Return strict JSON only in this shape:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _json_object(text: str) -> dict[str, Any]:
    candidate = re.sub(
        r"```(?:json)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("judge response does not contain a JSON object")
    try:
        payload = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError("judge response contains invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("judge response JSON must be an object")
    return payload


def parse_atomic_disclosure_audit(
    run: HiddenBenchRawRun,
    text: str,
    *,
    study_key: ConfirmatoryStudyKey,
    judge_model: str,
    judge_prompt_version: str = ATOMIC_JUDGE_PROMPT_VERSION,
    provider_metadata: dict[str, Any] | None = None,
) -> AtomicDisclosureAudit:
    payload = _json_object(text)
    if set(payload) != {"facts"} or not isinstance(payload["facts"], list):
        raise ValueError("judge response must contain only a facts list")
    facts = decompose_private_facts(run.assignment)
    judgments = tuple(
        AtomicDisclosureJudgment.model_validate(item)
        for item in payload["facts"]
    )
    validate_atomic_evidence(run, facts, judgments)
    rate = sum(item.disclosed for item in judgments) / len(judgments)
    return AtomicDisclosureAudit(
        study_key=study_key,
        judge_model=judge_model,
        judge_prompt_version=judge_prompt_version,
        facts=facts,
        judgments=judgments,
        disclosure_rate=rate,
        provider_metadata=provider_metadata or {},
    )


def _aggregate_judge_metadata(
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    usage: dict[str, int | float] = {}
    for item in calls:
        raw_usage = item.get("usage", {})
        if isinstance(raw_usage, dict):
            for key, value in raw_usage.items():
                if isinstance(value, (int, float)) and not isinstance(
                    value, bool
                ):
                    usage[key] = usage.get(key, 0) + value
    return {
        "attempts": len(calls),
        "api_requests": sum(
            int(item.get("api_requests", 0) or 0) for item in calls
        ),
        "repair_requests": max(0, len(calls) - 1),
        "local_evidence_reanchors": 0,
        "audit_code_commit": current_git_commit(),
        "usage": usage,
        "calls": calls,
    }


def _reanchor_atomic_evidence(
    run: HiddenBenchRawRun,
    text: str,
) -> tuple[str, int]:
    payload = _json_object(text)
    items = payload.get("facts")
    if not isinstance(items, list):
        return text, 0
    messages = {
        message.message_id: message for message in run.discussion_messages
    }
    repaired = 0
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("disclosed") is not True
            or not isinstance(item.get("owner_agent_id"), str)
            or not isinstance(item.get("evidence_quote"), str)
            or not isinstance(item.get("evidence_message_ids"), list)
        ):
            continue
        referenced = [
            messages[message_id]
            for message_id in item["evidence_message_ids"]
            if isinstance(message_id, str)
            and message_id in messages
            and messages[message_id].agent_id == item["owner_agent_id"]
        ]
        quote = item["evidence_quote"]
        if not referenced or any(
            quote in message.content for message in referenced
        ):
            continue
        best = ""
        for message in referenced:
            match = SequenceMatcher(
                None,
                quote.casefold(),
                message.content.casefold(),
                autojunk=False,
            ).find_longest_match()
            candidate = message.content[
                match.b : match.b + match.size
            ].strip(" \t\r\n,.;:!?\"'")
            if len(candidate) > len(best):
                best = candidate
        if len(best) < 12 or len(best.split()) < 2:
            best = referenced[0].content
        item["evidence_quote"] = best
        repaired += 1
    return json.dumps(payload, ensure_ascii=False), repaired


async def audit_atomic_disclosure(
    run: HiddenBenchRawRun,
    *,
    provider: Any,
    study_key: ConfirmatoryStudyKey,
    judge_model: str,
    seed: int,
    judge_prompt_version: str = ATOMIC_JUDGE_PROMPT_VERSION,
) -> AtomicDisclosureAudit:
    if run.provider_metadata.get("mechanical_reveal_all") is True:
        return mechanical_reveal_all_audit(run, study_key=study_key)

    prompt = build_atomic_disclosure_prompt(run)
    calls: list[dict[str, Any]] = []
    last_error: ValueError | None = None
    for attempt in range(5):
        repair_note = ""
        if attempt:
            repair_note = (
                "\n\nThe previous output was rejected. Return only complete valid "
                "JSON with one item per fact and exact evidence substrings."
            )
        completion = await provider.complete(
            agent_id="atomic-disclosure-auditor",
            system_prompt=(
                "You are a strict evidence auditor. Return JSON only and "
                "never invent evidence."
            ),
            user_prompt=prompt + repair_note,
            seed=seed + attempt,
            json_response=True,
        )
        calls.append(dict(completion.provider_metadata))
        try:
            return parse_atomic_disclosure_audit(
                run,
                completion.text,
                study_key=study_key,
                judge_model=judge_model,
                judge_prompt_version=judge_prompt_version,
                provider_metadata=_aggregate_judge_metadata(calls),
            )
        except ValueError as error:
            last_error = error
            if "exact substring" in str(error):
                reanchored, count = _reanchor_atomic_evidence(
                    run,
                    completion.text,
                )
                if count:
                    aggregate = _aggregate_judge_metadata(calls)
                    aggregate["local_evidence_reanchors"] = count
                    return parse_atomic_disclosure_audit(
                        run,
                        reanchored,
                        study_key=study_key,
                        judge_model=judge_model,
                        judge_prompt_version=judge_prompt_version,
                        provider_metadata=aggregate,
                    )
    raise ValueError("atomic disclosure audit invalid after five attempts") from last_error
