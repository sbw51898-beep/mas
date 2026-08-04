from __future__ import annotations

from pathlib import Path

import pytest

from mas_experiment.hiddenbench_atomic_disclosure import (
    AtomicDisclosureAudit,
    AtomicDisclosureJudgment,
    decompose_private_facts,
    mechanical_reveal_all_audit,
)
from mas_experiment.hiddenbench_confirmatory_domain import (
    load_confirmatory_config,
)
from mas_experiment.hiddenbench_confirmatory_gate import (
    build_confirmatory_gate,
)
from mas_experiment.hiddenbench_confirmatory_study import (
    read_confirmatory_records,
    run_confirmatory_study,
)
from mas_experiment.hiddenbench_data import load_hiddenbench_tasks
from mas_experiment.providers import StabilityOfflineProvider


ROOT = Path(__file__).parents[1]
CONFIG = load_confirmatory_config(
    ROOT / "configs" / "hiddenbench-confirmatory-20260804.json"
).model_copy(update={"repetitions": 1})
TASKS = load_hiddenbench_tasks(
    ROOT / "data" / "hiddenbench" / "benchmark.json",
    expected_sha256=CONFIG.dataset_sha256,
)


def _audit(record) -> AtomicDisclosureAudit:
    if record.key.condition.endswith("reveal-all"):
        return mechanical_reveal_all_audit(
            record.run,
            study_key=record.key,
        )
    facts = decompose_private_facts(record.run.assignment)
    judgments = tuple(
        AtomicDisclosureJudgment(
            fact_id=fact.fact_id,
            owner_agent_id=fact.owner_agent_id,
            disclosed=False,
            evidence_message_ids=(),
            evidence_quote="",
            reason="Offline test: not disclosed.",
            confidence=1.0,
        )
        for fact in facts
    )
    return AtomicDisclosureAudit(
        study_key=record.key,
        judge_model="stability-offline-v1",
        judge_prompt_version="hiddenbench-atomic-disclosure-v1",
        facts=facts,
        judgments=judgments,
        disclosure_rate=0.0,
        provider_metadata={"api_requests": 0, "repair_requests": 0},
    )


@pytest.mark.asyncio
async def test_gate_passes_complete_fixture_and_names_each_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs.jsonl"
    await run_confirmatory_study(
        tasks=TASKS,
        config=CONFIG,
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=False,
    )
    records = read_confirmatory_records(output, config=CONFIG)
    audits = tuple(_audit(record) for record in records)

    complete = build_confirmatory_gate(
        CONFIG,
        records,
        audits,
        dataset_path=ROOT / "data" / "hiddenbench" / "benchmark.json",
    )
    assert complete.passed is True
    assert all(complete.checks.values())

    duplicate = build_confirmatory_gate(
        CONFIG,
        (*records, records[0]),
        audits,
    )
    assert duplicate.checks["unique_run_keys"] is False

    reordered = build_confirmatory_gate(
        CONFIG,
        tuple(reversed(records)),
        audits,
    )
    assert reordered.checks["deterministic_row_order"] is False

    wrong_pair = records[1].model_copy(
        update={"assignment_fingerprint": "f" * 64}
    )
    pair_records = (records[0], wrong_pair, *records[2:])
    pair_gate = build_confirmatory_gate(CONFIG, pair_records, audits)
    assert pair_gate.checks["paired_seeds_and_assignments"] is False

    fixed_index = next(
        index
        for index, record in enumerate(records)
        if record.key.condition == "fixed-60"
    )
    no_shadow = records[fixed_index].model_copy(
        update={"shadow_checkpoints": ()}
    )
    shadow_records = tuple(
        no_shadow if index == fixed_index else record
        for index, record in enumerate(records)
    )
    shadow_gate = build_confirmatory_gate(CONFIG, shadow_records, audits)
    assert shadow_gate.checks["complete_shadow_checkpoints"] is False

    reveal_index = next(
        index
        for index, audit in enumerate(audits)
        if audit.study_key.condition.endswith("reveal-all")
    )
    low_reveal = audits[reveal_index].model_copy(
        update={"disclosure_rate": 0.5}
    )
    reveal_audits = tuple(
        low_reveal if index == reveal_index else audit
        for index, audit in enumerate(audits)
    )
    reveal_gate = build_confirmatory_gate(CONFIG, records, reveal_audits)
    assert reveal_gate.checks["reveal_all_is_complete"] is False

    first_audit = audits[0]
    invalid_judgment = first_audit.judgments[0].model_copy(
        update={
            "disclosed": True,
            "evidence_message_ids": ("missing",),
            "evidence_quote": "invented",
        }
    )
    invalid_audit = first_audit.model_copy(
        update={
            "judgments": (invalid_judgment, *first_audit.judgments[1:]),
            "disclosure_rate": 1 / len(first_audit.judgments),
        }
    )
    evidence_audits = (invalid_audit, *audits[1:])
    evidence_gate = build_confirmatory_gate(CONFIG, records, evidence_audits)
    assert evidence_gate.checks["valid_atomic_evidence"] is False

    bad_vote = records[0].run.hidden_pre_votes[0].model_copy(
        update={"provider_metadata": {"model": "wrong-model"}}
    )
    bad_run = records[0].run.model_copy(
        update={
            "hidden_pre_votes": (
                bad_vote,
                *records[0].run.hidden_pre_votes[1:],
            )
        }
    )
    bad_provider_record = records[0].model_copy(update={"run": bad_run})
    provider_records = (bad_provider_record, *records[1:])
    provider_gate = build_confirmatory_gate(CONFIG, provider_records, audits)
    assert provider_gate.checks["provider_settings"] is False

    bad_commit = records[0].model_copy(
        update={"frozen_code_commit": "e" * 40}
    )
    commit_gate = build_confirmatory_gate(
        CONFIG,
        (bad_commit, *records[1:]),
        audits,
    )
    assert commit_gate.checks["code_commit_provenance"] is False
