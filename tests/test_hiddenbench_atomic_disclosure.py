from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_atomic_disclosure import (
    AtomicDisclosureJudgment,
    append_reveal_all_block,
    audit_atomic_disclosure,
    build_atomic_disclosure_prompt,
    decompose_private_facts,
    mechanical_reveal_all_audit,
    parse_atomic_disclosure_audit,
    validate_atomic_evidence,
)
from mas_experiment.hiddenbench_confirmatory_domain import ConfirmatoryStudyKey
from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_protocol import run_hiddenbench_task
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
EXPECTED_SHA = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)
TASK = load_hiddenbench_task(
    DATASET,
    task_id=1,
    expected_sha256=EXPECTED_SHA,
)


def _vote_text() -> str:
    return json.dumps(
        {"vote": TASK.correct_answer, "rationale": "Evidence."}
    )


def _three_round_script() -> tuple[str, ...]:
    outputs: list[str] = []
    outputs.extend(_vote_text() for _ in range(4))
    outputs.extend("No private detail in this model output." for _ in range(12))
    outputs.extend(_vote_text() for _ in range(4))
    outputs.extend(_vote_text() for _ in range(4))
    return tuple(outputs)


def test_short_assignment_decomposes_to_four_atomic_facts() -> None:
    assignment = assign_hidden_information(TASK, seed=20260804)

    facts = decompose_private_facts(assignment)

    assert len(facts) == 4
    assert {fact.owner_agent_id for fact in facts} == set(AGENT_IDS)
    assert len({fact.fact_id for fact in facts}) == 4


def test_structured_packet_splits_bullets_with_heading_context() -> None:
    assignment = HiddenBenchAssignment(
        task_id=7,
        seed=1,
        shared_information=(),
        private_information={
            "agent-a": "Cape Industries:\n- (a) Y\n- (b) N",
            "agent-b": "Simple B.",
            "agent-c": "Simple C.",
            "agent-d": "Simple D.",
        },
    )

    facts = [
        fact
        for fact in decompose_private_facts(assignment)
        if fact.owner_agent_id == "agent-a"
    ]

    assert [fact.text for fact in facts] == [
        "Cape Industries: (a) Y",
        "Cape Industries: (b) N",
    ]
    assert [fact.atomic_index for fact in facts] == [0, 1]
    assert facts == [
        fact
        for fact in decompose_private_facts(assignment)
        if fact.owner_agent_id == "agent-a"
    ]


def test_reveal_all_block_contains_exact_atomic_facts_and_ids() -> None:
    assignment = assign_hidden_information(TASK, seed=20260804)
    facts = decompose_private_facts(assignment)
    owner_facts = tuple(
        fact for fact in facts if fact.owner_agent_id == "agent-a"
    )

    content, appended_ids = append_reveal_all_block(
        "Model-authored discussion.",
        owner_facts,
    )

    assert "SYSTEM MECHANICAL REVEAL-ALL" in content
    assert owner_facts[0].text in content
    assert appended_ids == (owner_facts[0].fact_id,)


@pytest.mark.asyncio
async def test_fixed_protocol_stores_mechanically_revealed_facts() -> None:
    provider = ScriptedPromptProvider(_three_round_script())

    run = await run_hiddenbench_task(
        TASK,
        provider,
        seed=20260804,
        discussion_rounds=3,
        mechanical_reveal_all=True,
    )

    facts = decompose_private_facts(run.assignment)
    first_round = run.discussion_messages[:4]
    for message in first_round:
        owner_facts = [
            fact for fact in facts if fact.owner_agent_id == message.agent_id
        ]
        assert owner_facts
        assert all(fact.text in message.content for fact in owner_facts)
        assert message.provider_metadata["mechanical_reveal_all"] is True
        assert tuple(message.provider_metadata["appended_fact_ids"]) == tuple(
            fact.fact_id for fact in owner_facts
        )

    for message in run.discussion_messages[4:]:
        assert "SYSTEM MECHANICAL REVEAL-ALL" not in message.content


@pytest.mark.asyncio
async def test_mechanical_reveal_audit_is_100_percent_without_judge_call() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
        mechanical_reveal_all=True,
    )

    audit = mechanical_reveal_all_audit(
        run,
        study_key=ConfirmatoryStudyKey(
            task_id=1,
            condition="fixed-reveal-all",
            repetition=0,
        ),
    )

    assert audit.disclosure_rate == 1.0
    assert audit.disclosure_percentage == 100.0
    assert audit.provider_metadata["api_requests"] == 0
    assert all(judgment.disclosed for judgment in audit.judgments)


def _judgments_with_one_positive(
    facts: tuple,
    *,
    fact_id: str,
    message_id: str,
    quote: str,
) -> tuple[AtomicDisclosureJudgment, ...]:
    return tuple(
        AtomicDisclosureJudgment(
            fact_id=fact.fact_id,
            owner_agent_id=fact.owner_agent_id,
            disclosed=fact.fact_id == fact_id,
            evidence_message_ids=(message_id,)
            if fact.fact_id == fact_id
            else (),
            evidence_quote=quote if fact.fact_id == fact_id else "",
            reason="Evidence checked.",
            confidence=1.0,
        )
        for fact in facts
    )


@pytest.mark.asyncio
async def test_atomic_evidence_rejects_non_owner_and_missing_message() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
        mechanical_reveal_all=True,
    )
    facts = decompose_private_facts(run.assignment)
    target = facts[0]
    owner_message = next(
        message
        for message in run.discussion_messages
        if message.agent_id == target.owner_agent_id
    )
    other_message = next(
        message
        for message in run.discussion_messages
        if message.agent_id != target.owner_agent_id
    )

    validate_atomic_evidence(
        run,
        facts,
        _judgments_with_one_positive(
            facts,
            fact_id=target.fact_id,
            message_id=owner_message.message_id,
            quote=target.text,
        ),
    )
    with pytest.raises(ValueError, match="owner-authored"):
        validate_atomic_evidence(
            run,
            facts,
            _judgments_with_one_positive(
                facts,
                fact_id=target.fact_id,
                message_id=other_message.message_id,
                quote=target.text,
            ),
        )
    with pytest.raises(ValueError, match="owner-authored"):
        validate_atomic_evidence(
            run,
            facts,
            _judgments_with_one_positive(
                facts,
                fact_id=target.fact_id,
                message_id="missing-message",
                quote=target.text,
            ),
        )


@pytest.mark.asyncio
async def test_atomic_evidence_rejects_missing_quote_and_polarity_reversal() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
        mechanical_reveal_all=True,
    )
    facts = decompose_private_facts(run.assignment)
    target = facts[0]
    owner_message = next(
        message
        for message in run.discussion_messages
        if message.agent_id == target.owner_agent_id
    )

    with pytest.raises(ValueError, match="exact substring"):
        validate_atomic_evidence(
            run,
            facts,
            _judgments_with_one_positive(
                facts,
                fact_id=target.fact_id,
                message_id=owner_message.message_id,
                quote="This quote is absent.",
            ),
        )

    reversed_quote = "The supply truck was not stuck in the tunnel."
    reversed_message = owner_message.model_copy(
        update={"content": reversed_quote}
    )
    reversed_run = run.model_copy(
        update={
            "discussion_messages": tuple(
                reversed_message if message == owner_message else message
                for message in run.discussion_messages
            )
        }
    )
    reversed_fact = target.model_copy(
        update={"text": "The supply truck was stuck in the tunnel."}
    )
    reversed_facts = (reversed_fact, *facts[1:])
    with pytest.raises(ValueError, match="polarity"):
        validate_atomic_evidence(
            reversed_run,
            reversed_facts,
            _judgments_with_one_positive(
                reversed_facts,
                fact_id=reversed_fact.fact_id,
                message_id=reversed_message.message_id,
                quote=reversed_quote,
            ),
        )


@pytest.mark.asyncio
async def test_atomic_prompt_and_parser_cover_every_fact_once() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
    )
    facts = decompose_private_facts(run.assignment)
    prompt = build_atomic_disclosure_prompt(run, facts)
    for fact in facts:
        assert fact.fact_id in prompt
        assert fact.text in prompt
    for message in run.discussion_messages:
        assert message.message_id in prompt

    payload = {
        "facts": [
            {
                "fact_id": fact.fact_id,
                "owner_agent_id": fact.owner_agent_id,
                "disclosed": False,
                "evidence_message_ids": [],
                "evidence_quote": "",
                "reason": "Not stated.",
                "confidence": 0.95,
            }
            for fact in facts
        ]
    }
    audit = parse_atomic_disclosure_audit(
        run,
        json.dumps(payload),
        study_key=ConfirmatoryStudyKey(
            task_id=1,
            condition="fixed-12",
            repetition=0,
        ),
        judge_model="test-judge",
    )

    assert audit.disclosure_rate == 0.0
    assert audit.facts == facts


@pytest.mark.asyncio
async def test_atomic_auditor_calls_judge_for_non_mechanical_run() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
    )
    facts = decompose_private_facts(run.assignment)
    response = json.dumps(
        {
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "owner_agent_id": fact.owner_agent_id,
                    "disclosed": False,
                    "evidence_message_ids": [],
                    "evidence_quote": "",
                    "reason": "Not stated.",
                    "confidence": 0.9,
                }
                for fact in facts
            ]
        }
    )
    judge = ScriptedPromptProvider((response,))

    audit = await audit_atomic_disclosure(
        run,
        provider=judge,
        study_key=ConfirmatoryStudyKey(
            task_id=1,
            condition="fixed-12",
            repetition=0,
        ),
        judge_model="test-judge",
        seed=20260804,
    )

    assert audit.disclosure_rate == 0.0
    assert len(judge.calls) == 1
    assert judge.calls[0]["json_response"] is True


@pytest.mark.asyncio
async def test_atomic_auditor_bypasses_judge_for_mechanical_run() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
        mechanical_reveal_all=True,
    )
    judge = ScriptedPromptProvider(())

    audit = await audit_atomic_disclosure(
        run,
        provider=judge,
        study_key=ConfirmatoryStudyKey(
            task_id=1,
            condition="fixed-reveal-all",
            repetition=0,
        ),
        judge_model="unused",
        seed=20260804,
    )

    assert audit.disclosure_rate == 1.0
    assert len(judge.calls) == 0


@pytest.mark.asyncio
async def test_atomic_auditor_locally_reanchors_near_match_quote() -> None:
    run = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(_three_round_script()),
        seed=20260804,
        discussion_rounds=3,
    )
    facts = decompose_private_facts(run.assignment)
    target = next(fact for fact in facts if fact.owner_agent_id == "agent-a")
    original = run.discussion_messages[0]
    exact_message = original.model_copy(
        update={
            "content": (
                "The supply truck headed to village was stuck in the tunnel."
            )
        }
    )
    run = run.model_copy(
        update={
            "discussion_messages": (
                exact_message,
                *run.discussion_messages[1:],
            )
        }
    )
    response = json.dumps(
        {
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "owner_agent_id": fact.owner_agent_id,
                    "disclosed": fact.fact_id == target.fact_id,
                    "evidence_message_ids": [exact_message.message_id]
                    if fact.fact_id == target.fact_id
                    else [],
                    "evidence_quote": (
                        "The supply truck headed to the village was stuck "
                        "in the tunnel."
                    )
                    if fact.fact_id == target.fact_id
                    else "",
                    "reason": "Evidence checked.",
                    "confidence": 0.9,
                }
                for fact in facts
            ]
        }
    )
    judge = ScriptedPromptProvider((response,))

    audit = await audit_atomic_disclosure(
        run,
        provider=judge,
        study_key=ConfirmatoryStudyKey(
            task_id=1,
            condition="fixed-12",
            repetition=0,
        ),
        judge_model="test-judge",
        seed=20260804,
    )

    positive = next(item for item in audit.judgments if item.disclosed)
    assert positive.evidence_quote in exact_message.content
    assert audit.provider_metadata["local_evidence_reanchors"] == 1
    assert len(judge.calls) == 1
