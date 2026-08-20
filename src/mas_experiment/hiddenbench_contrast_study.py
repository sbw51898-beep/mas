from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_ai_disclosure import (
    DisclosureAudit,
    validate_disclosure_evidence,
)
from mas_experiment.hiddenbench_contrast_protocol import (
    ContrastRunRecord,
    ContrastStudyConfig,
    ContrastStudyKey,
    SINGLE_AGENT_ID,
    assignment_fingerprint,
    run_contrast_condition,
)
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_reporting import _assert_no_secrets


ProviderFactory = Callable[[], Any]


def derive_pair_seed(
    base_seed: int,
    *,
    task_id: int,
    repetition: int,
) -> int:
    payload = f"{base_seed}|{task_id}|{repetition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def expected_study_keys(
    config: ContrastStudyConfig,
) -> tuple[ContrastStudyKey, ...]:
    return tuple(
        ContrastStudyKey(
            task_id=task_id,
            condition=condition,
            repetition=repetition,
        )
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
        for condition in config.conditions
    )


def _sort_records(
    records: tuple[ContrastRunRecord, ...],
    config: ContrastStudyConfig,
) -> tuple[ContrastRunRecord, ...]:
    task_order = {
        task_id: index
        for index, task_id in enumerate(config.task_ids)
    }
    condition_order = {
        condition: index
        for index, condition in enumerate(config.conditions)
    }
    return tuple(
        sorted(
            records,
            key=lambda item: (
                task_order[item.key.task_id],
                item.key.repetition,
                condition_order[item.key.condition],
            ),
        )
    )


def _atomic_write_records(
    output: Path,
    records: tuple[ContrastRunRecord, ...],
    config: ContrastStudyConfig,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    ordered = _sort_records(records, config)
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in ordered:
            stream.write(record.model_dump_json())
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)


def read_completed_study_records(
    output: Path,
) -> tuple[ContrastRunRecord, ...]:
    if not output.exists():
        return ()
    records: list[ContrastRunRecord] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = ContrastRunRecord.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise ValueError(
                f"invalid contrast record at line {line_number}: {exc}"
            ) from exc
        if record.key.value in seen:
            raise ValueError(
                f"duplicate contrast record: {record.key.value}"
            )
        seen.add(record.key.value)
        records.append(record)
    return tuple(records)


class ContrastStudyExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed: tuple[str, ...]
    skipped: tuple[str, ...]
    output: Path


async def run_contrast_study(
    *,
    tasks: tuple[HiddenBenchTask, ...],
    config: ContrastStudyConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
) -> ContrastStudyExecution:
    if output.exists() and not resume:
        raise FileExistsError(f"study output already exists: {output}")
    existing = read_completed_study_records(output) if resume else ()
    task_by_id = {task.id: task for task in tasks}
    expected = expected_study_keys(config)
    keys = {key.value for key in expected}
    by_key = {record.key.value: record for record in existing}
    unknown = set(by_key) - keys
    if unknown:
        raise ValueError(f"records contain unknown keys: {sorted(unknown)}")
    pending = [key for key in expected if key.value not in by_key]
    semaphore = asyncio.Semaphore(config.experiment_workers)
    write_lock = asyncio.Lock()
    executed: list[str] = []

    async def execute_one(key: ContrastStudyKey) -> None:
        task = task_by_id[key.task_id]
        pair_seed = derive_pair_seed(
            config.base_seed,
            task_id=key.task_id,
            repetition=key.repetition,
        )
        async with semaphore:
            run = await run_contrast_condition(
                task=task,
                condition=key.condition,
                provider=provider_factory(),
                seed=pair_seed,
                assignment=None,
                config=config,
            )
        record = ContrastRunRecord(
            key=key,
            pair_seed=pair_seed,
            assignment_fingerprint=assignment_fingerprint(run),
            run=run,
        )
        async with write_lock:
            by_key[key.value] = record
            _atomic_write_records(
                output,
                tuple(by_key.values()),
                config,
            )
            executed.append(key.value)

    await asyncio.gather(*(execute_one(key) for key in pending))
    return ContrastStudyExecution(
        executed=tuple(executed),
        skipped=tuple(
            key.value for key in expected if key.value in by_key
        ),
        output=output,
    )


class ContrastGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: dict[str, bool]
    passed: bool


def _provider_items(record: ContrastRunRecord) -> tuple[object, ...]:
    run = record.run
    return (
        *run.hidden_pre_votes,
        *run.discussion_messages,
        *run.hidden_post_votes,
        *run.full_profile_votes,
    )


def _contains_no_secrets(value: object) -> bool:
    try:
        _assert_no_secrets(value)
    except ValueError:
        return False
    return True


def build_contrast_gate(
    config: ContrastStudyConfig,
    records: tuple[ContrastRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    *,
    dataset_path: Path | None = None,
) -> ContrastGate:
    expected = tuple(key.value for key in expected_study_keys(config))
    run_keys = tuple(record.key.value for record in records)

    dataset_ok = True
    if dataset_path is not None:
        dataset_ok = (
            dataset_path.is_file()
            and hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            == config.dataset_sha256
        )

    structure_ok = True
    provider_ok = True
    for record in records:
        run = record.run
        messages = run.discussion_messages
        condition = record.key.condition
        if condition == "single-direct":
            structure_ok &= len(messages) == 0
        elif condition == "single-reflect":
            structure_ok &= len(messages) == config.reflect_rounds
            structure_ok &= all(
                message.agent_id == SINGLE_AGENT_ID
                for message in messages
            )
            structure_ok &= all(
                message.turn_index == index
                and message.round_index == index + 1
                for index, message in enumerate(messages)
            )
        elif condition in ("fixed-4", "fixed-8", "fixed-12"):
            fixed_message_counts = {
                "fixed-4": 16,
                "fixed-8": 32,
                "fixed-12": 12,
            }
            fixed_round_counts = {
                "fixed-4": 4,
                "fixed-8": 8,
                "fixed-12": 3,
            }
            structure_ok &= (
                len(messages) == fixed_message_counts[condition]
            )
            structure_ok &= Counter(
                message.agent_id for message in messages
            ) == {
                agent_id: fixed_round_counts[condition]
                for agent_id in AGENT_IDS
            }
            structure_ok &= [
                message.round_index for message in messages
            ] == [
                round_index
                for round_index in range(1, fixed_round_counts[condition] + 1)
                for _ in AGENT_IDS
            ]
        else:
            structure_ok &= False
        structure_ok &= all(
            message.visible_message_ids
            == tuple(
                previous.message_id
                for previous in messages[:index]
            )
            for index, message in enumerate(messages)
        )
        if condition in ("fixed-4", "fixed-8", "fixed-12"):
            structure_ok &= (
                len(run.hidden_pre_votes) == 4
                and len(run.hidden_post_votes) == 4
                and len(run.full_profile_votes) == 4
            )
        else:
            structure_ok &= (
                len(run.hidden_pre_votes) == 1
                and len(run.hidden_post_votes) == 1
                and len(run.full_profile_votes) == 1
            )
        for item in _provider_items(record):
            metadata = item.provider_metadata
            if metadata.get("provider") == "stability-offline":
                provider_ok &= (
                    metadata.get("model") == "stability-offline-v1"
                    and float(metadata.get("temperature", -1)) == 0
                    and metadata.get("thinking") == "disabled"
                )
            else:
                provider_ok &= (
                    metadata.get("model") == config.provider.model
                    and float(metadata.get("temperature", -1))
                    == config.provider.temperature
                    and metadata.get("thinking")
                    == config.provider.thinking
                )

    seed_ok = True
    fingerprint_ok = True
    for record in records:
        seed_ok &= record.pair_seed == derive_pair_seed(
            config.base_seed,
            task_id=record.key.task_id,
            repetition=record.key.repetition,
        )
        fingerprint_ok &= (
            record.assignment_fingerprint
            == assignment_fingerprint(record.run)
        )

    records_by_key = {
        record.key.value: record for record in records
    }
    audit_keys = tuple(audit.study_key.value for audit in audits)
    evidence_ok = True
    for audit in audits:
        if audit.study_key.condition not in (
            "fixed-4",
            "fixed-8",
            "fixed-12",
        ):
            evidence_ok = False
            continue
        record = records_by_key.get(audit.study_key.value)
        if record is None:
            evidence_ok = False
            continue
        try:
            validate_disclosure_evidence(record.run, audit.judgments)
        except (ValueError, TypeError):
            evidence_ok = False

    fixed_keys = {
        key.value
        for key in expected_study_keys(config)
        if key.condition in ("fixed-4", "fixed-8", "fixed-12")
    }
    audit_complete = (
        set(audit_keys) == fixed_keys
        and len(audit_keys) == len(fixed_keys)
    )
    checks = {
        "complete_run_matrix": (
            len(run_keys) == len(expected)
            and set(run_keys) == set(expected)
        ),
        "unique_run_keys": len(set(run_keys)) == len(run_keys),
        "audit_coverage_fixed_conditions": audit_complete,
        "valid_ai_evidence": evidence_ok,
        "task_and_dataset_hashes": (
            dataset_ok
            and {record.key.task_id for record in records}.issubset(
                set(config.task_ids)
            )
        ),
        "seeds_match_config": seed_ok,
        "assignment_fingerprints": fingerprint_ok,
        "provider_settings": provider_ok,
        "condition_structure": structure_ok,
        "credential_leak_scan": (
            _contains_no_secrets(
                [record.model_dump(mode="json") for record in records]
            )
            and _contains_no_secrets(
                [audit.model_dump(mode="json") for audit in audits]
            )
        ),
        "deterministic_row_order": run_keys == expected,
    }
    return ContrastGate(
        checks=checks,
        passed=all(checks.values()),
    )
