from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_confirmatory_domain import (
    validate_confirmatory_tasks,
)
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import HiddenBenchRun, assign_hidden_information
from mas_experiment.hiddenbench_dynamic_domain import DynamicProviderConfig
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_protocol import PromptProvider, run_hiddenbench_task
from mas_experiment.hiddenbench_stability_domain import (
    assignment_fingerprint,
    derive_pair_seed,
)


ProviderFactory = Callable[[], PromptProvider]


class OfficialRevealSupplementConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: Literal[
        "hiddenbench-official-reveal-supplement-v1"
    ]
    task_ids: tuple[int, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    frozen_code_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    experiment_workers: int = Field(ge=1, le=16)
    provider: DynamicProviderConfig

    @model_validator(mode="after")
    def validate_lock(self) -> OfficialRevealSupplementConfig:
        if self.task_ids != (1, 2, 3):
            raise ValueError("task_ids must be exactly 1, 2, 3")
        if self.repetitions != 10:
            raise ValueError("repetitions must be exactly 10")
        if self.provider.model != "deepseek-v4-flash":
            raise ValueError("provider model must be deepseek-v4-flash")
        if self.provider.temperature != 0:
            raise ValueError("provider temperature must be 0")
        if self.provider.thinking != "disabled":
            raise ValueError("provider thinking must be disabled")
        return self

    @property
    def expected_run_count(self) -> int:
        return len(self.task_ids) * self.repetitions


class OfficialRevealSupplementKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: Literal["official-global-reveal"] = "official-global-reveal"
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return (
            f"task-{self.task_id}:{self.condition}:rep-{self.repetition}"
        )


class OfficialRevealSupplementRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: OfficialRevealSupplementKey
    pair_seed: int
    assignment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    frozen_code_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    run: HiddenBenchRun

    @model_validator(mode="after")
    def validate_shape(self) -> OfficialRevealSupplementRecord:
        if self.run.task.id != self.key.task_id:
            raise ValueError("record key task does not match run task")
        if self.run.assignment.seed != self.pair_seed:
            raise ValueError("pair seed does not match assignment seed")
        if len(self.run.discussion_messages) != 60:
            raise ValueError("supplement run requires exactly 60 messages")
        return self


class OfficialRevealSupplementExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed_runs: int = Field(ge=0)
    skipped_runs: int = Field(ge=0)
    output: Path


def load_official_reveal_config(
    path: Path,
) -> OfficialRevealSupplementConfig:
    return OfficialRevealSupplementConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def expected_official_reveal_keys(
    config: OfficialRevealSupplementConfig,
) -> tuple[OfficialRevealSupplementKey, ...]:
    return tuple(
        OfficialRevealSupplementKey(
            task_id=task_id,
            repetition=repetition,
        )
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
    )


def read_official_reveal_records(
    output: Path,
    *,
    config: OfficialRevealSupplementConfig,
) -> tuple[OfficialRevealSupplementRecord, ...]:
    if not output.exists():
        return ()
    records: list[OfficialRevealSupplementRecord] = []
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            records.append(
                OfficialRevealSupplementRecord.model_validate_json(line)
            )
        except (ValidationError, ValueError) as error:
            raise ValueError(
                f"invalid supplement record at line {line_number}: {error}"
            ) from error
    keys = tuple(record.key for record in records)
    expected = expected_official_reveal_keys(config)
    if keys != expected[: len(keys)]:
        raise ValueError("supplement rows are not a deterministic prefix")
    return tuple(records)


def _append_record(
    output: Path,
    record: OfficialRevealSupplementRecord,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(record.model_dump_json())
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


async def _run_one(
    *,
    task: HiddenBenchTask,
    repetition: int,
    config: OfficialRevealSupplementConfig,
    provider_factory: ProviderFactory,
) -> OfficialRevealSupplementRecord:
    pair_seed = derive_pair_seed(
        config.base_seed,
        task_id=task.id,
        repetition=repetition,
    )
    assignment = assign_hidden_information(task, seed=pair_seed)
    raw = await run_hiddenbench_task(
        task,
        provider_factory(),
        seed=pair_seed,
        discussion_rounds=15,
        assignment=assignment,
        mechanical_global_reveal_round_one=True,
    )
    scored = score_hiddenbench_run(raw)
    return OfficialRevealSupplementRecord(
        key=OfficialRevealSupplementKey(
            task_id=task.id,
            repetition=repetition,
        ),
        pair_seed=pair_seed,
        assignment_fingerprint=assignment_fingerprint(scored),
        run_commit=current_git_commit(),
        frozen_code_commit=config.frozen_code_commit,
        run=scored,
    )


async def run_official_reveal_supplement(
    *,
    tasks: tuple[HiddenBenchTask, ...],
    config: OfficialRevealSupplementConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
) -> OfficialRevealSupplementExecution:
    if output.exists() and not resume:
        raise FileExistsError(f"supplement output already exists: {output}")
    existing = (
        read_official_reveal_records(output, config=config) if resume else ()
    )
    task_by_id = {task.id: task for task in tasks}
    if config.task_ids == (1, 2, 3):
        validate_confirmatory_tasks(tasks)
    pairs = tuple(
        (task_id, repetition)
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
    )
    pending = pairs[len(existing) :]
    semaphore = asyncio.Semaphore(config.experiment_workers)

    async def execute(pair: tuple[int, int]) -> OfficialRevealSupplementRecord:
        task_id, repetition = pair
        task = task_by_id.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id} was not loaded")
        async with semaphore:
            return await _run_one(
                task=task,
                repetition=repetition,
                config=config,
                provider_factory=provider_factory,
            )

    running = [asyncio.create_task(execute(pair)) for pair in pending]
    executed = 0
    for task in running:
        record = await task
        _append_record(output, record)
        executed += 1
    return OfficialRevealSupplementExecution(
        executed_runs=executed,
        skipped_runs=len(existing),
        output=output,
    )

