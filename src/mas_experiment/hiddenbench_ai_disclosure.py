from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
    HiddenBenchRun,
)
from mas_experiment.hiddenbench_protocol import PromptProvider
from mas_experiment.hiddenbench_stability_domain import StudyKey


class FactDisclosureJudgment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str
    owner_agent_id: str
    disclosed: bool
    evidence_message_ids: tuple[str, ...]
    evidence_quote: str
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DisclosureAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_key: StudyKey
    judge_model: str
    judge_prompt_version: str
    judgments: tuple[FactDisclosureJudgment, ...]
    disclosure_rate: float = Field(ge=0, le=1)
    provider_metadata: dict[str, Any]

    @property
    def disclosure_percentage(self) -> float:
        return self.disclosure_rate * 100.0


def _expected_facts(run: HiddenBenchRun) -> dict[str, tuple[str, str]]:
    return {
        f"private-fact:{owner_id}": (owner_id, fact)
        for owner_id, fact in run.assignment.private_information.items()
    }


def _tolerant_json_loads(text: str) -> dict[str, Any]:
    """Parse an LLM JSON object, tolerating fences and stray prose."""
    candidate = text
    if "```" in candidate:
        candidate = re.sub(r"```(?:json)?", "", candidate, flags=re.IGNORECASE)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain a JSON object")
    candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        escaped = _escape_raw_control_characters(candidate)
        payload = json.loads(escaped)
    if not isinstance(payload, dict):
        raise ValueError("model response JSON must be an object")
    return payload


def _escape_raw_control_characters(text: str) -> str:
    """Escape raw control characters that sit inside JSON string values."""
    out: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            out.append(char)
            continue
        if in_string and char in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
            continue
        out.append(char)
    return "".join(out)


def build_disclosure_audit_prompt(run: HiddenBenchRun) -> str:
    facts = "\n".join(
        (
            f"- private-fact:{owner_id} | owner={owner_id} | "
            f"private_fact={json.dumps(fact, ensure_ascii=False)}"
        )
        for owner_id, fact in run.assignment.private_information.items()
    )
    messages = "\n".join(
        (
            f"{message.message_id} | {message.agent_id} | "
            f"{message.content}"
        )
        for message in run.discussion_messages
    )
    schema_example = {
        "facts": [
            {
                "fact_id": "private-fact:agent-a",
                "owner_agent_id": "agent-a",
                "disclosed": True,
                "evidence_message_ids": ["message-id"],
                "evidence_quote": "exact substring from that message",
                "reason": "short explanation",
                "confidence": 0.95,
            }
        ]
    }
    return (
        "Judge whether each private fact was disclosed in the public "
        "discussion.\n\n"
        "Definition:\n"
        "1. Count a fact only when its owner states the fact or a faithful "
        "paraphrase containing the decision-relevant claim.\n"
        "2. A polarity reversal, contradiction, or materially weakened claim "
        "is not disclosure.\n"
        "3. A partial statement counts only if it preserves the part needed "
        "to decide the task.\n"
        "4. A guess or repetition by a non-owner does not disclose the "
        "owner's private information.\n"
        "5. For disclosed=true, cite owner-authored message IDs and copy one "
        "exact, non-empty substring from a cited message as evidence_quote.\n"
        "6. For disclosed=false, use an empty ID list and empty quote.\n\n"
        f"PRIVATE FACTS:\n{facts}\n\n"
        f"PUBLIC MESSAGES:\n{messages}\n\n"
        "Return strict JSON only, with exactly one item for every listed "
        "fact. Do not use Markdown and do not calculate a percentage. Shape:\n"
        f"{json.dumps(schema_example, ensure_ascii=False)}"
    )


def validate_disclosure_evidence(
    run: HiddenBenchRun,
    judgments: tuple[FactDisclosureJudgment, ...],
) -> None:
    expected = _expected_facts(run)
    if len(judgments) != len(expected):
        raise ValueError(
            "audit must contain exactly one judgment per owner fact"
        )
    by_fact = {judgment.fact_id: judgment for judgment in judgments}
    if len(by_fact) != len(judgments) or set(by_fact) != set(expected):
        raise ValueError(
            "audit must contain exactly one judgment per owner fact"
        )

    messages: dict[str, HiddenBenchMessage] = {
        message.message_id: message
        for message in run.discussion_messages
    }
    for fact_id, (owner_id, _) in expected.items():
        judgment = by_fact[fact_id]
        if judgment.owner_agent_id != owner_id:
            raise ValueError(
                f"{fact_id} owner_agent_id does not match assignment"
            )
        if not judgment.disclosed:
            if judgment.evidence_message_ids or judgment.evidence_quote:
                raise ValueError(
                    "undisclosed judgment must not contain evidence"
                )
            continue
        if (
            not judgment.evidence_message_ids
            or not judgment.evidence_quote
        ):
            raise ValueError(
                "disclosed judgment requires owner-authored evidence"
            )
        referenced: list[HiddenBenchMessage] = []
        for message_id in judgment.evidence_message_ids:
            message = messages.get(message_id)
            if message is None or message.agent_id != owner_id:
                raise ValueError(
                    "disclosed evidence must be owner-authored"
                )
            referenced.append(message)
        if not any(
            judgment.evidence_quote in message.content
            for message in referenced
        ):
            raise ValueError(
                "evidence_quote must be an exact substring of a "
                "referenced message"
            )


def parse_disclosure_audit(
    run: HiddenBenchRun,
    text: str,
    *,
    study_key: StudyKey | None = None,
    judge_model: str = "unspecified",
    judge_prompt_version: str = "hiddenbench-disclosure-audit-v1",
    provider_metadata: dict[str, Any] | None = None,
) -> DisclosureAudit:
    try:
        payload = _tolerant_json_loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid disclosure audit JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"facts"}:
        raise ValueError(
            "disclosure audit must be an object containing only facts"
        )
    if not isinstance(payload["facts"], list):
        raise ValueError("disclosure audit facts must be a list")
    judgments = tuple(
        FactDisclosureJudgment.model_validate(item)
        for item in payload["facts"]
    )
    validate_disclosure_evidence(run, judgments)
    rate = (
        sum(judgment.disclosed for judgment in judgments)
        / len(judgments)
    )
    resolved_key = study_key or StudyKey(
        task_id=run.task.id,
        condition="fixed",
        repetition=0,
    )
    return DisclosureAudit(
        study_key=resolved_key,
        judge_model=judge_model,
        judge_prompt_version=judge_prompt_version,
        judgments=judgments,
        disclosure_rate=rate,
        provider_metadata=provider_metadata or {},
    )


def _aggregate_metadata(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    usage: dict[str, float] = {}
    for item in items:
        raw_usage = item.get("usage", {})
        if isinstance(raw_usage, dict):
            for name, value in raw_usage.items():
                if isinstance(value, int | float):
                    usage[name] = usage.get(name, 0.0) + value
    return {
        "attempts": len(items),
        "api_requests": sum(
            int(item.get("api_requests", 0))
            for item in items
        ),
        "repair_requests": max(0, len(items) - 1),
        "local_evidence_reanchors": 0,
        "usage": usage,
        "calls": items,
    }


def _reanchor_evidence_quotes(
    run: HiddenBenchRun,
    text: str,
) -> tuple[str, int]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return text, 0
    facts = payload.get("facts")
    if not isinstance(facts, list):
        return text, 0
    messages = {
        message.message_id: message
        for message in run.discussion_messages
    }
    repaired = 0
    for item in facts:
        if (
            not isinstance(item, dict)
            or item.get("disclosed") is not True
            or not isinstance(item.get("evidence_quote"), str)
            or not isinstance(item.get("evidence_message_ids"), list)
            or not isinstance(item.get("owner_agent_id"), str)
        ):
            continue
        quote = item["evidence_quote"]
        referenced = [
            messages[message_id]
            for message_id in item["evidence_message_ids"]
            if isinstance(message_id, str)
            and message_id in messages
            and messages[message_id].agent_id
            == item["owner_agent_id"]
        ]
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
        if (
            len(best) < 12
            or len(best.split()) < 2
        ):
            best = referenced[0].content
        item["evidence_quote"] = best
        repaired += 1
    return (
        json.dumps(payload, ensure_ascii=False),
        repaired,
    )


async def audit_run_disclosure(
    run: HiddenBenchRun,
    *,
    provider: PromptProvider,
    study_key: StudyKey,
    judge_model: str,
    judge_prompt_version: str,
    seed: int,
) -> DisclosureAudit:
    user_prompt = build_disclosure_audit_prompt(run)
    metadata: list[dict[str, Any]] = []
    last_error: ValueError | None = None
    for attempt in range(5):
        if attempt == 0:
            attempt_prompt = user_prompt
            system_prompt = (
                "You are a strict evidence auditor. Return JSON only and "
                "never invent evidence."
            )
            attempt_seed = seed
        else:
            attempt_prompt = (
                f"{user_prompt}\n\n"
                "The previous response was not valid JSON and was rejected. "
                "Keep every reason under 80 characters, escape all quotes and "
                "newlines inside strings, and return only the complete JSON "
                "object with one item per fact."
            )
            system_prompt = (
                "You are a strict evidence auditor. Return JSON only and "
                "never invent evidence."
            )
            attempt_seed = seed + attempt
        completion = await provider.complete(
            agent_id="disclosure-auditor",
            system_prompt=system_prompt,
            user_prompt=attempt_prompt,
            seed=attempt_seed,
            json_response=True,
        )
        metadata.append(completion.provider_metadata)
        aggregate = _aggregate_metadata(metadata)
        try:
            return parse_disclosure_audit(
                run,
                completion.text,
                study_key=study_key,
                judge_model=judge_model,
                judge_prompt_version=judge_prompt_version,
                provider_metadata=aggregate,
            )
        except ValueError as error:
            last_error = error
            if "exact substring" in str(error):
                reanchored, count = _reanchor_evidence_quotes(
                    run,
                    completion.text,
                )
                if count == 0:
                    raise
                aggregate["local_evidence_reanchors"] = count
                return parse_disclosure_audit(
                    run,
                    reanchored,
                    study_key=study_key,
                    judge_model=judge_model,
                    judge_prompt_version=judge_prompt_version,
                    provider_metadata=aggregate,
                )
    raise ValueError(
        "audit JSON invalid after five attempts"
    ) from last_error
