from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_confirmatory_domain import (
    load_confirmatory_config,
)
from mas_experiment.hiddenbench_confirmatory_study import (
    audit_confirmatory_records,
    expected_confirmatory_keys,
    read_confirmatory_audits,
    read_confirmatory_records,
    run_confirmatory_study,
)
from mas_experiment.hiddenbench_data import load_hiddenbench_tasks
from mas_experiment.providers import StabilityOfflineProvider


ROOT = Path(__file__).parents[1]
CONFIG = load_confirmatory_config(
    ROOT / "configs" / "hiddenbench-confirmatory-20260804.json"
)
TASKS = load_hiddenbench_tasks(
    ROOT / "data" / "hiddenbench" / "benchmark.json",
    expected_sha256=CONFIG.dataset_sha256,
)


@pytest.mark.asyncio
async def test_reduced_matrix_is_paired_and_condition_shapes_are_exact(
    tmp_path: Path,
) -> None:
    reduced = CONFIG.model_copy(
        update={"repetitions": 2, "experiment_workers": 6}
    )
    output = tmp_path / "confirmatory.jsonl"

    result = await run_confirmatory_study(
        tasks=TASKS,
        config=reduced,
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=False,
    )
    records = read_confirmatory_records(output, config=reduced)

    assert result.executed_runs == 42
    assert len(records) == 42
    assert len({record.key.value for record in records}) == 42
    assert tuple(record.key for record in records) == expected_confirmatory_keys(
        reduced
    )
    for task_id in (1, 2, 3):
        for repetition in (0, 1):
            group = [
                record
                for record in records
                if record.key.task_id == task_id
                and record.key.repetition == repetition
            ]
            assert len({record.pair_seed for record in group}) == 1
            assert len(
                {record.assignment_fingerprint for record in group}
            ) == 1

            by_condition = {record.key.condition: record for record in group}
            fixed = by_condition["fixed-60"]
            assert len(fixed.run.discussion_messages) == 60
            assert len(fixed.shadow_checkpoints) == 15
            assert all(
                len(checkpoint.votes) == 4
                for checkpoint in fixed.shadow_checkpoints
            )
            for condition in ("structured-12", "fixed-12"):
                assert len(
                    by_condition[condition].run.discussion_messages
                ) == 12
            assert len(by_condition["single-local"].run.hidden_post_votes) == 1
            for condition in ("dynamic-60", "dynamic-reveal-all"):
                dynamic = by_condition[condition]
                assert len(dynamic.run.discussion_messages) == 60
                assert Counter(
                    message.agent_id
                    for message in dynamic.run.discussion_messages
                ) == {
                    "agent-a": 15,
                    "agent-b": 15,
                    "agent-c": 15,
                    "agent-d": 15,
                }
                assert dynamic.run.provider_metadata[
                    "selector_llm_calls"
                ] == 0
                assert len(dynamic.selection_events) == 60


@pytest.mark.asyncio
async def test_resume_skips_a_complete_matrix_without_provider_calls(
    tmp_path: Path,
) -> None:
    reduced = CONFIG.model_copy(update={"repetitions": 1})
    output = tmp_path / "confirmatory.jsonl"
    await run_confirmatory_study(
        tasks=TASKS,
        config=reduced,
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=False,
    )

    def fail_factory() -> StabilityOfflineProvider:
        raise AssertionError("resume must not construct a provider")

    result = await run_confirmatory_study(
        tasks=TASKS,
        config=reduced,
        provider_factory=fail_factory,
        output=output,
        resume=True,
    )

    assert result.executed_runs == 0
    assert result.skipped_runs == 21


@pytest.mark.asyncio
async def test_atomic_audit_writer_is_complete_ordered_and_resumable(
    tmp_path: Path,
) -> None:
    reduced = CONFIG.model_copy(update={"repetitions": 1})
    run_output = tmp_path / "runs.jsonl"
    audit_output = tmp_path / "audits.jsonl"
    await run_confirmatory_study(
        tasks=TASKS,
        config=reduced,
        provider_factory=StabilityOfflineProvider,
        output=run_output,
        resume=False,
    )
    records = read_confirmatory_records(run_output, config=reduced)

    first = await audit_confirmatory_records(
        records=records,
        config=reduced,
        provider_factory=StabilityOfflineProvider,
        output=audit_output,
        resume=False,
    )
    audits = read_confirmatory_audits(audit_output, config=reduced)

    assert first.executed_audits == 21
    assert len(audits) == 21
    assert tuple(audit.study_key for audit in audits) == tuple(
        record.key for record in records
    )
    assert all(
        audit.disclosure_rate == 1.0
        for audit in audits
        if audit.study_key.condition.endswith("reveal-all")
    )

    def fail_factory() -> StabilityOfflineProvider:
        raise AssertionError("completed audit resume must not create provider")

    resumed = await audit_confirmatory_records(
        records=records,
        config=reduced,
        provider_factory=fail_factory,
        output=audit_output,
        resume=True,
    )
    assert resumed.executed_audits == 0
    assert resumed.skipped_audits == 21
