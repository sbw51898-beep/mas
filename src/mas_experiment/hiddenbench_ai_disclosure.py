from __future__ import annotations

import json
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
        payload = json.loads(text)
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
        "usage": usage,
        "calls": items,
    }


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
    completion = await provider.complete(
        agent_id="disclosure-auditor",
        system_prompt=(
            "You are a strict evidence auditor. Return JSON only and never "
            "invent evidence."
        ),
        user_prompt=user_prompt,
        seed=seed,
        json_response=True,
    )
    metadata.append(completion.provider_metadata)
    try:
        return parse_disclosure_audit(
            run,
            completion.text,
            study_key=study_key,
            judge_model=judge_model,
            judge_prompt_version=judge_prompt_version,
            provider_metadata=_aggregate_metadata(metadata),
        )
    except (ValueError, TypeError) as first_error:
        repair = await provider.complete(
            agent_id="disclosure-auditor",
            system_prompt=(
                "Repair the prior audit. Return strict JSON only and cite "
                "only owner-authored evidence from the supplied transcript."
            ),
            user_prompt=(
                f"{user_prompt}\n\n"
                "The previous response was invalid for this reason:\n"
                f"{first_error}\n\n"
                "Return a corrected complete JSON object."
            ),
            seed=seed + 1,
            json_response=True,
        )
        metadata.append(repair.provider_metadata)
        return parse_disclosure_audit(
            run,
            repair.text,
            study_key=study_key,
            judge_model=judge_model,
            judge_prompt_version=judge_prompt_version,
            provider_metadata=_aggregate_metadata(metadata),
        )
