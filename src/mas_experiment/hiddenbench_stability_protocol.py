from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_dynamic_protocol import (
    run_hiddenbench_dynamic_task,
)
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_protocol import (
    PromptProvider,
    run_hiddenbench_task,
)
from mas_experiment.hiddenbench_stability_domain import (
    StabilityStudyConfig,
    StudyKey,
    StudyRunRecord,
    assignment_fingerprint,
    derive_pair_seed,
)


ProviderFactory = Callable[[], PromptProvider]
PairKey = tuple[int, int]


class StabilityStudyExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed_pairs: tuple[str, ...]
    skipped_pairs: tuple[str, ...]
    output: Path


def expected_study_keys(
    config: StabilityStudyConfig,
) -> tuple[StudyKey, ...]:
    return tuple(
        StudyKey(
            task_id=task_id,
            condition=condition,
            repetition=repetition,
        )
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
        for condition in config.conditions
    )


def _pair_value(pair: PairKey) -> str:
    return f"task-{pair[0]}:rep-{pair[1]}"


async def run_study_pair(
    *,
    task: HiddenBenchTask,
    repetition: int,
    config: StabilityStudyConfig,
    fixed_provider: PromptProvider,
    dynamic_provider: PromptProvider,
) -> tuple[StudyRunRecord, StudyRunRecord]:
    pair_seed = derive_pair_seed(
        config.base_seed,
        task_id=task.id,
        repetition=repetition,
    )
    fixed_raw = await run_hiddenbench_task(
        task,
        fixed_provider,
        seed=pair_seed,
        discussion_rounds=15,
    )
    fixed_run = score_hiddenbench_run(fixed_raw)
    fingerprint = assignment_fingerprint(fixed_run)
    fixed = StudyRunRecord(
        key=StudyKey(
            task_id=task.id,
            condition="fixed",
            repetition=repetition,
        ),
        pair_seed=pair_seed,
        assignment_fingerprint=fingerprint,
        run=fixed_run,
    )

    dynamic_result = await run_hiddenbench_dynamic_task(
        task,
        dynamic_provider,
        seed=pair_seed,
        assignment=fixed_run.assignment,
        baseline_run_id=fixed_run.run_id,
        config=config,  # type: ignore[arg-type]
    )
    dynamic_fingerprint = assignment_fingerprint(dynamic_result.run)
    if dynamic_fingerprint != fingerprint:
        raise RuntimeError(
            "fixed and dynamic assignment fingerprints differ"
        )
    dynamic = StudyRunRecord(
        key=StudyKey(
            task_id=task.id,
            condition="dynamic",
            repetition=repetition,
        ),
        pair_seed=pair_seed,
        assignment_fingerprint=dynamic_fingerprint,
        run=dynamic_result.run,
        baseline_run_id=dynamic_result.baseline_run_id,
        selection_events=dynamic_result.selection_events,
    )

    for record in (fixed, dynamic):
        if len(record.run.discussion_messages) != config.total_speeches:
            raise RuntimeError("study run violated the speech budget")
    return fixed, dynamic


def _validate_complete_pairs(
    records: tuple[StudyRunRecord, ...],
) -> None:
    conditions_by_pair: dict[PairKey, set[str]] = {}
    seen: set[str] = set()
    by_pair: dict[PairKey, list[StudyRunRecord]] = {}
    for record in records:
        if record.key.value in seen:
            raise ValueError(
                f"duplicate study record: {record.key.value}"
            )
        seen.add(record.key.value)
        pair = (record.key.task_id, record.key.repetition)
        conditions_by_pair.setdefault(pair, set()).add(
            record.key.condition
        )
        by_pair.setdefault(pair, []).append(record)
    for pair, conditions in conditions_by_pair.items():
        if conditions != {"fixed", "dynamic"}:
            raise ValueError(
                f"partial pair {_pair_value(pair)} in study output"
            )
        pair_records = by_pair[pair]
        if (
            len({item.pair_seed for item in pair_records}) != 1
            or len(
                {
                    item.assignment_fingerprint
                    for item in pair_records
                }
            )
            != 1
        ):
            raise ValueError(
                f"paired conditions differ for {_pair_value(pair)}"
            )


def read_completed_study_records(
    output: Path,
) -> tuple[StudyRunRecord, ...]:
    if not output.exists():
        return ()
    records: list[StudyRunRecord] = []
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            records.append(StudyRunRecord.model_validate_json(line))
        except (ValidationError, ValueError) as exc:
            raise ValueError(
                f"invalid study record at line {line_number}: {exc}"
            ) from exc
    result = tuple(records)
    _validate_complete_pairs(result)
    return result


def _sort_records(
    records: tuple[StudyRunRecord, ...],
    config: StabilityStudyConfig,
) -> tuple[StudyRunRecord, ...]:
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
    records: tuple[StudyRunRecord, ...],
    config: StabilityStudyConfig,
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


async def run_stability_study(
    *,
    tasks: tuple[HiddenBenchTask, ...],
    config: StabilityStudyConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
    requested_pairs: tuple[PairKey, ...] | None = None,
) -> StabilityStudyExecution:
    if output.exists() and not resume:
        raise FileExistsError(
            f"study output already exists: {output}"
        )
    existing = (
        read_completed_study_records(output)
        if resume
        else ()
    )
    task_by_id = {task.id: task for task in tasks}
    pairs = requested_pairs or tuple(
        (task_id, repetition)
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
    )
    for task_id, repetition in pairs:
        if task_id not in task_by_id:
            raise ValueError(f"task {task_id} was not loaded")
        if task_id not in config.task_ids:
            raise ValueError(f"task {task_id} is outside the study matrix")
        if not 0 <= repetition < config.repetitions:
            raise ValueError(
                f"repetition {repetition} is outside the study matrix"
            )

    records_by_key = {
        record.key.value: record for record in existing
    }
    complete_pairs = {
        (record.key.task_id, record.key.repetition)
        for record in existing
    }
    skipped = tuple(
        _pair_value(pair)
        for pair in pairs
        if pair in complete_pairs
    )
    pending = tuple(
        pair for pair in pairs if pair not in complete_pairs
    )
    semaphore = asyncio.Semaphore(config.experiment_workers)
    write_lock = asyncio.Lock()
    executed: list[str] = []

    async def execute_pair(pair: PairKey) -> None:
        task_id, repetition = pair
        async with semaphore:
            fixed, dynamic = await run_study_pair(
                task=task_by_id[task_id],
                repetition=repetition,
                config=config,
                fixed_provider=provider_factory(),
                dynamic_provider=provider_factory(),
            )
        async with write_lock:
            records_by_key[fixed.key.value] = fixed
            records_by_key[dynamic.key.value] = dynamic
            _atomic_write_records(
                output,
                tuple(records_by_key.values()),
                config,
            )
            executed.append(_pair_value(pair))

    await asyncio.gather(
        *(execute_pair(pair) for pair in pending)
    )
    return StabilityStudyExecution(
        executed_pairs=tuple(executed),
        skipped_pairs=skipped,
        output=output,
    )
