from __future__ import annotations

import json

import pytest

from mas_experiment.hiddenbench_ai_disclosure import (
    audit_run_disclosure,
    parse_disclosure_audit,
)
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
    HiddenBenchRun,
)
from mas_experiment.hiddenbench_stability_domain import StudyKey
from mas_experiment.providers import ScriptedPromptProvider


FACTS = {
    "agent-a": "The bridge is closed.",
    "agent-b": "The train leaves at noon.",
    "agent-c": "The key is under the mat.",
    "agent-d": "The witness wore a red coat.",
}


def make_run() -> HiddenBenchRun:
    task = HiddenBenchTask(
        id=1,
        name="audit-fixture",
        description="Choose an answer.",
        shared_information=("Shared premise.",),
        hidden_information=tuple(FACTS.values()),
        possible_answers=("A", "B"),
        correct_answer="A",
    )
    assignment = HiddenBenchAssignment(
        task_id=task.id,
        seed=11,
        shared_information=task.shared_information,
        private_information=FACTS,
    )
    messages = tuple(
        HiddenBenchMessage(
            message_id=f"message-{index}",
            round_index=1,
            turn_index=index,
            agent_id=agent_id,
            content=f"My evidence says: {FACTS[agent_id]}",
            visible_message_ids=(),
            system_prompt="system",
            user_prompt="user",
        )
        for index, agent_id in enumerate(AGENT_IDS)
    )
    return HiddenBenchRun.model_construct(
        run_id="audit-run",
        task=task,
        assignment=assignment,
        discussion_messages=messages,
    )


RUN = make_run()


def valid_audit_payload(*, disclosed: int = 4) -> dict[str, object]:
    facts = []
    for index, agent_id in enumerate(AGENT_IDS):
        is_disclosed = index < disclosed
        facts.append(
            {
                "fact_id": f"private-fact:{agent_id}",
                "owner_agent_id": agent_id,
                "disclosed": is_disclosed,
                "evidence_message_ids": (
                    [f"message-{index}"] if is_disclosed else []
                ),
                "evidence_quote": (
                    FACTS[agent_id] if is_disclosed else ""
                ),
                "reason": (
                    "The owner stated the decision-relevant fact."
                    if is_disclosed
                    else "The owner did not state the fact."
                ),
                "confidence": 0.95,
            }
        )
    return {"facts": facts}


def test_audit_requires_one_judgment_per_owner_fact() -> None:
    payload = valid_audit_payload()
    payload["facts"].pop()  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="exactly one judgment"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_disclosed_evidence_must_exist_and_belong_to_owner() -> None:
    payload = valid_audit_payload()
    payload["facts"][0]["evidence_message_ids"] = [  # type: ignore[index]
        "message-1"
    ]

    with pytest.raises(ValueError, match="owner-authored"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_evidence_quote_must_be_exact_substring() -> None:
    payload = valid_audit_payload()
    payload["facts"][0]["evidence_quote"] = (  # type: ignore[index]
        "invented quotation"
    )

    with pytest.raises(ValueError, match="exact substring"):
        parse_disclosure_audit(RUN, json.dumps(payload))


def test_ai_disclosure_rate_is_disclosed_fact_fraction() -> None:
    audit = parse_disclosure_audit(
        RUN,
        json.dumps(valid_audit_payload(disclosed=3)),
    )

    assert audit.disclosure_rate == pytest.approx(0.75)
    assert audit.disclosure_percentage == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_invalid_first_response_gets_one_repair_call() -> None:
    provider = ScriptedPromptProvider(
        (
            "not-json",
            json.dumps(valid_audit_payload(disclosed=2)),
        )
    )

    audit = await audit_run_disclosure(
        RUN,
        provider=provider,
        study_key=StudyKey(
            task_id=1,
            condition="fixed",
            repetition=0,
        ),
        judge_model="scripted-offline",
        judge_prompt_version="hiddenbench-disclosure-audit-v1",
        seed=23,
    )

    assert len(provider.calls) == 2
    assert audit.disclosure_percentage == pytest.approx(50.0)
    assert audit.provider_metadata["attempts"] == 2


@pytest.mark.asyncio
async def test_second_response_quote_is_reanchored_to_exact_text() -> None:
    payload = valid_audit_payload(disclosed=1)
    payload["facts"][0]["evidence_quote"] = (  # type: ignore[index]
        "evidence says bridge is closed"
    )
    provider = ScriptedPromptProvider(
        ("not-json", json.dumps(payload))
    )

    audit = await audit_run_disclosure(
        RUN,
        provider=provider,
        study_key=StudyKey(
            task_id=1,
            condition="fixed",
            repetition=0,
        ),
        judge_model="scripted-offline",
        judge_prompt_version="hiddenbench-disclosure-audit-v1",
        seed=23,
    )

    judgment = audit.judgments[0]
    assert judgment.evidence_quote in RUN.discussion_messages[0].content
    assert audit.provider_metadata["local_evidence_reanchors"] == 1
    assert len(provider.calls) == 2
