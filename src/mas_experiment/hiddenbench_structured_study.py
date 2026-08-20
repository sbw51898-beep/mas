from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from mas_experiment.hiddenbench_ai_disclosure import (
    DisclosureAudit,
    validate_disclosure_evidence,
)
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_reporting import _assert_no_secrets
from mas_experiment.hiddenbench_structured_protocol import (
    EXCHANGE_ROUNDS,
    StructuredRunRecord,
    StructuredStudyConfig,
    StructuredStudyKey,
    TOTAL_MESSAGES,
    assignment_fingerprint,
    run_hiddenbench_structured_task,
)


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
    config: StructuredStudyConfig,
) -> tuple[StructuredStudyKey, ...]:
    return tuple(
        StructuredStudyKey(
            task_id=task_id,
            repetition=repetition,
        )
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
    )


def _sort_records(
    records: tuple[StructuredRunRecord, ...],
    config: StructuredStudyConfig,
) -> tuple[StructuredRunRecord, ...]:
    task_order = {
        task_id: index
        for index, task_id in enumerate(config.task_ids)
    }
    return tuple(
        sorted(
            records,
            key=lambda item: (
                task_order[item.key.task_id],
                item.key.repetition,
            ),
        )
    )


def _atomic_write_records(
    output: Path,
    records: tuple[StructuredRunRecord, ...],
    config: StructuredStudyConfig,
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
) -> tuple[StructuredRunRecord, ...]:
    if not output.exists():
        return ()
    records: list[StructuredRunRecord] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = StructuredRunRecord.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise ValueError(
                f"invalid structured record at line {line_number}: {exc}"
            ) from exc
        if record.key.value in seen:
            raise ValueError(f"duplicate structured record: {record.key.value}")
        seen.add(record.key.value)
        records.append(record)
    return tuple(records)


class StructuredStudyExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed: tuple[str, ...]
    skipped: tuple[str, ...]
    output: Path


async def run_structured_study(
    *,
    tasks: tuple[HiddenBenchTask, ...],
    config: StructuredStudyConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
) -> StructuredStudyExecution:
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

    async def execute_one(key: StructuredStudyKey) -> None:
        task = task_by_id[key.task_id]
        pair_seed = derive_pair_seed(
            config.base_seed,
            task_id=key.task_id,
            repetition=key.repetition,
        )
        async with semaphore:
            run = await run_hiddenbench_structured_task(
                task,
                provider_factory(),
                seed=pair_seed,
            )
        record = StructuredRunRecord(
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
    return StructuredStudyExecution(
        executed=tuple(executed),
        skipped=tuple(
            key.value for key in expected if key.value in by_key
        ),
        output=output,
    )


class StructuredGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: dict[str, bool]
    passed: bool


def _provider_items(record: StructuredRunRecord) -> tuple[object, ...]:
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


def build_structured_gate(
    config: StructuredStudyConfig,
    records: tuple[StructuredRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    *,
    dataset_path: Path | None = None,
) -> StructuredGate:
    expected = tuple(key.value for key in expected_study_keys(config))
    run_keys = tuple(record.key.value for record in records)
    audit_keys = tuple(audit.study_key.value for audit in audits)

    dataset_ok = True
    if dataset_path is not None:
        dataset_ok = (
            dataset_path.is_file()
            and hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            == config.dataset_sha256
        )

    budget_ok = True
    visibility_ok = True
    provider_ok = True
    protocol_ok = True
    for record in records:
        messages = record.run.discussion_messages
        budget_ok &= len(messages) == TOTAL_MESSAGES
        budget_ok &= Counter(
            message.agent_id for message in messages
        ) == {agent_id: EXCHANGE_ROUNDS + 1 for agent_id in AGENT_IDS}
        expected_rounds = (
            [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3]
        )
        visibility_ok &= (
            [
                message.round_index
                for message in messages
            ]
            == expected_rounds
        )
        visibility_ok &= all(
            message.turn_index == index
            and message.visible_message_ids
            == tuple(
                previous.message_id
                for previous in messages[:index]
            )
            for index, message in enumerate(messages)
        )
        protocol_ok &= all(
            message.agent_id == AGENT_IDS[index % len(AGENT_IDS)]
            for index, message in enumerate(messages)
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
    evidence_ok = len(audits) == len(expected)
    for audit in audits:
        record = records_by_key.get(audit.study_key.value)
        if record is None:
            evidence_ok = False
            continue
        try:
            validate_disclosure_evidence(
                record.run,
                audit.judgments,
            )
        except (ValueError, TypeError):
            evidence_ok = False

    checks = {
        "complete_run_matrix": (
            len(run_keys) == len(expected)
            and set(run_keys) == set(expected)
        ),
        "unique_run_keys": len(set(run_keys)) == len(run_keys),
        "complete_ai_audits": (
            len(audit_keys) == len(expected)
            and set(audit_keys) == set(expected)
        ),
        "unique_audit_keys": len(set(audit_keys)) == len(audit_keys),
        "task_and_dataset_hashes": (
            dataset_ok
            and {record.key.task_id for record in records}.issubset(
                set(config.task_ids)
            )
        ),
        "seeds_match_config": seed_ok,
        "assignment_fingerprints": fingerprint_ok,
        "provider_settings": provider_ok,
        "twelve_message_protocol": budget_ok,
        "exchange_then_decide_rounds": visibility_ok,
        "fixed_agent_order": protocol_ok,
        "valid_ai_evidence": evidence_ok,
        "credential_leak_scan": (
            _contains_no_secrets(
                [record.model_dump(mode="json") for record in records]
            )
            and _contains_no_secrets(
                [audit.model_dump(mode="json") for audit in audits]
            )
        ),
        "deterministic_row_order": (
            run_keys == expected and audit_keys == expected
        ),
    }
    return StructuredGate(
        checks=checks,
        passed=all(checks.values()),
    )
