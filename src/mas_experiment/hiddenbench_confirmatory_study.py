from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_atomic_disclosure import (
    AtomicDisclosureAudit,
    audit_atomic_disclosure,
)
from mas_experiment.hiddenbench_confirmatory_domain import (
    ConfirmatoryStudyConfig,
    ConfirmatoryStudyKey,
)
from mas_experiment.hiddenbench_contrast_protocol import _run_single_agent
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    HiddenBenchAssignment,
    HiddenBenchRun,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicPilotConfig,
    DynamicSelectorConfig,
    FrozenBaselineConfig,
    SelectorEvent,
)
from mas_experiment.hiddenbench_dynamic_protocol import (
    run_hiddenbench_dynamic_task,
)
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_protocol import PromptProvider, run_hiddenbench_task
from mas_experiment.hiddenbench_shadow_voting import (
    EarlyStopEvaluation,
    ShadowVoteCheckpoint,
    ShadowVotingRun,
)
from mas_experiment.hiddenbench_stability_domain import derive_pair_seed
from mas_experiment.hiddenbench_structured_protocol import (
    run_hiddenbench_structured_task,
)


ProviderFactory = Callable[[], PromptProvider]


class ConfirmatoryRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ConfirmatoryStudyKey
    pair_seed: int
    assignment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    frozen_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    run: HiddenBenchRun
    baseline_run_id: str | None = None
    selection_events: tuple[SelectorEvent, ...] = ()
    shadow_checkpoints: tuple[ShadowVoteCheckpoint, ...] = ()
    early_stop: EarlyStopEvaluation | None = None

    @model_validator(mode="after")
    def validate_condition_shape(self) -> ConfirmatoryRunRecord:
        if self.run.task.id != self.key.task_id:
            raise ValueError("record key task does not match run task")
        if self.run.assignment.seed != self.pair_seed:
            raise ValueError("pair seed does not match assignment seed")
        if self.key.condition.startswith("dynamic"):
            if len(self.selection_events) != 60 or not self.baseline_run_id:
                raise ValueError("dynamic condition requires 60 selector events")
        elif self.selection_events or self.baseline_run_id:
            raise ValueError("non-dynamic condition has dynamic metadata")
        if self.key.condition == "fixed-60":
            if len(self.shadow_checkpoints) != 15 or self.early_stop is None:
                raise ValueError("fixed-60 requires 15 shadow checkpoints")
        elif self.shadow_checkpoints or self.early_stop is not None:
            raise ValueError("only fixed-60 may store shadow checkpoints")
        return self


class ConfirmatoryStudyExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed_runs: int = Field(ge=0)
    skipped_runs: int = Field(ge=0)
    output: Path


class ConfirmatoryAuditExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executed_audits: int = Field(ge=0)
    skipped_audits: int = Field(ge=0)
    output: Path


def expected_confirmatory_keys(
    config: ConfirmatoryStudyConfig,
) -> tuple[ConfirmatoryStudyKey, ...]:
    return tuple(
        ConfirmatoryStudyKey(
            task_id=task_id,
            condition=condition,
            repetition=repetition,
        )
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
        for condition in config.conditions
    )


def _assignment_fingerprint(assignment: HiddenBenchAssignment) -> str:
    payload = json.dumps(
        assignment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dynamic_config(config: ConfirmatoryStudyConfig) -> DynamicPilotConfig:
    zeros = "0" * 64
    return DynamicPilotConfig(
        configuration_version="hiddenbench-dynamic-pilot-v1",
        pilot_task_ids=(1, 5, 7),
        base_seed=config.base_seed,
        dataset_sha256=config.dataset_sha256,
        prompt_version="hiddenbench-appendix-a4-v1",
        total_speeches=60,
        speeches_per_agent=15,
        selector_llm_calls=0,
        selector=DynamicSelectorConfig(
            disagreement=0.30,
            undisclosed=0.30,
            related_discussion=0.15,
            response_due=0.15,
            waiting=0.10,
        ),
        evidence_rule_version="lexical-semantic-v2",
        provider=config.provider,
        frozen_baseline=FrozenBaselineConfig(
            git_commit=config.frozen_code_commit,
            jsonl="confirmatory-runtime",
            jsonl_sha256=zeros,
            report="confirmatory-runtime",
            report_sha256=zeros,
            config="configs/hiddenbench-confirmatory-20260804.json",
            config_sha256=zeros,
        ),
    )


def _record(
    *,
    key: ConfirmatoryStudyKey,
    pair_seed: int,
    assignment: HiddenBenchAssignment,
    run: HiddenBenchRun,
    config: ConfirmatoryStudyConfig,
    baseline_run_id: str | None = None,
    selection_events: tuple[SelectorEvent, ...] = (),
    shadow_checkpoints: tuple[ShadowVoteCheckpoint, ...] = (),
    early_stop: EarlyStopEvaluation | None = None,
) -> ConfirmatoryRunRecord:
    return ConfirmatoryRunRecord(
        key=key,
        pair_seed=pair_seed,
        assignment_fingerprint=_assignment_fingerprint(assignment),
        run_commit=current_git_commit(),
        frozen_code_commit=config.frozen_code_commit,
        run=run,
        baseline_run_id=baseline_run_id,
        selection_events=selection_events,
        shadow_checkpoints=shadow_checkpoints,
        early_stop=early_stop,
    )


async def run_confirmatory_pair(
    *,
    task: HiddenBenchTask,
    repetition: int,
    config: ConfirmatoryStudyConfig,
    provider_factory: ProviderFactory,
) -> tuple[ConfirmatoryRunRecord, ...]:
    pair_seed = derive_pair_seed(
        config.base_seed,
        task_id=task.id,
        repetition=repetition,
    )
    assignment = assign_hidden_information(task, seed=pair_seed)
    dynamic_config = _dynamic_config(config)
    records: list[ConfirmatoryRunRecord] = []
    baselines: dict[str, str] = {}

    for condition in config.conditions:
        key = ConfirmatoryStudyKey(
            task_id=task.id,
            condition=condition,
            repetition=repetition,
        )
        provider = provider_factory()
        if condition == "fixed-60":
            result = await run_hiddenbench_task(
                task,
                provider,
                seed=pair_seed,
                discussion_rounds=15,
                collect_round_shadow_votes=True,
                assignment=assignment,
            )
            if not isinstance(result, ShadowVotingRun):
                raise RuntimeError("fixed-60 did not return shadow trace")
            scored = score_hiddenbench_run(result.run)
            baselines[condition] = scored.run_id
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=scored,
                config=config,
                shadow_checkpoints=result.shadow_checkpoints,
                early_stop=result.early_stop,
            )
        elif condition in {"dynamic-60", "dynamic-reveal-all"}:
            baseline_condition = (
                "fixed-60"
                if condition == "dynamic-60"
                else "fixed-reveal-all"
            )
            baseline_run_id = baselines.get(baseline_condition)
            if baseline_run_id is None:
                raise RuntimeError("dynamic condition requires its fixed baseline")
            result = await run_hiddenbench_dynamic_task(
                task,
                provider,
                seed=pair_seed,
                assignment=assignment,
                baseline_run_id=baseline_run_id,
                config=dynamic_config,
                mechanical_reveal_all=condition == "dynamic-reveal-all",
            )
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=result.run,
                config=config,
                baseline_run_id=result.baseline_run_id,
                selection_events=result.selection_events,
            )
        elif condition == "fixed-reveal-all":
            raw = await run_hiddenbench_task(
                task,
                provider,
                seed=pair_seed,
                discussion_rounds=15,
                mechanical_reveal_all=True,
                assignment=assignment,
            )
            if isinstance(raw, ShadowVotingRun):
                raise RuntimeError("Reveal-All unexpectedly returned shadow trace")
            scored = score_hiddenbench_run(raw)
            baselines[condition] = scored.run_id
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=scored,
                config=config,
            )
        elif condition == "structured-12":
            raw = await run_hiddenbench_structured_task(
                task,
                provider,
                seed=pair_seed,
                assignment=assignment,
            )
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=score_hiddenbench_run(raw),
                config=config,
            )
        elif condition == "fixed-12":
            raw = await run_hiddenbench_task(
                task,
                provider,
                seed=pair_seed,
                discussion_rounds=3,
                assignment=assignment,
            )
            if isinstance(raw, ShadowVotingRun):
                raise RuntimeError("fixed-12 unexpectedly returned shadow trace")
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=score_hiddenbench_run(raw),
                config=config,
            )
        elif condition == "single-local":
            scored = await _run_single_agent(
                task,
                provider,
                seed=pair_seed,
                assignment=assignment,
                reflect_rounds=0,
            )
            record = _record(
                key=key,
                pair_seed=pair_seed,
                assignment=assignment,
                run=scored,
                config=config,
            )
        else:  # pragma: no cover - Literal/config validation guards this.
            raise ValueError(f"unknown confirmatory condition: {condition}")
        records.append(record)

    if len({item.assignment_fingerprint for item in records}) != 1:
        raise RuntimeError("paired conditions differ in assignment")
    return tuple(records)


def read_confirmatory_records(
    output: Path,
    *,
    config: ConfirmatoryStudyConfig,
) -> tuple[ConfirmatoryRunRecord, ...]:
    if not output.exists():
        return ()
    records: list[ConfirmatoryRunRecord] = []
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            records.append(ConfirmatoryRunRecord.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise ValueError(
                f"invalid confirmatory record at line {line_number}: {error}"
            ) from error
    keys = tuple(record.key for record in records)
    expected = expected_confirmatory_keys(config)
    if keys != expected[: len(keys)]:
        raise ValueError("confirmatory rows are not a deterministic prefix")
    if len(keys) % len(config.conditions):
        raise ValueError("confirmatory output contains a partial pair")
    return tuple(records)


def _append_records(output: Path, records: tuple[ConfirmatoryRunRecord, ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(record.model_dump_json())
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_confirmatory_audits(
    output: Path,
    *,
    config: ConfirmatoryStudyConfig,
) -> tuple[AtomicDisclosureAudit, ...]:
    if not output.exists():
        return ()
    audits: list[AtomicDisclosureAudit] = []
    for line_number, line in enumerate(
        output.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            audits.append(AtomicDisclosureAudit.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise ValueError(
                f"invalid confirmatory audit at line {line_number}: {error}"
            ) from error
    keys = tuple(audit.study_key for audit in audits)
    expected = expected_confirmatory_keys(config)
    if keys != expected[: len(keys)]:
        raise ValueError("confirmatory audits are not a deterministic prefix")
    return tuple(audits)


def _append_audit(output: Path, audit: AtomicDisclosureAudit) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(audit.model_dump_json())
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


async def audit_confirmatory_records(
    *,
    records: tuple[ConfirmatoryRunRecord, ...],
    config: ConfirmatoryStudyConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
) -> ConfirmatoryAuditExecution:
    if output.exists() and not resume:
        raise FileExistsError(f"confirmatory audit output exists: {output}")
    existing = read_confirmatory_audits(output, config=config) if resume else ()
    expected_records = tuple(
        record.key for record in records
    )
    if expected_records != expected_confirmatory_keys(config):
        raise ValueError("cannot audit an incomplete or reordered run matrix")
    pending = records[len(existing) :]
    semaphore = asyncio.Semaphore(config.judge_workers)

    async def execute(record: ConfirmatoryRunRecord) -> AtomicDisclosureAudit:
        async with semaphore:
            return await audit_atomic_disclosure(
                record.run,
                provider=provider_factory(),
                study_key=record.key,
                judge_model=config.provider.model,
                seed=record.pair_seed + 700_000,
            )

    running = [asyncio.create_task(execute(record)) for record in pending]
    executed = 0
    for task in running:
        audit = await task
        _append_audit(output, audit)
        executed += 1
    return ConfirmatoryAuditExecution(
        executed_audits=executed,
        skipped_audits=len(existing),
        output=output,
    )


async def run_confirmatory_study(
    *,
    tasks: tuple[HiddenBenchTask, ...],
    config: ConfirmatoryStudyConfig,
    provider_factory: ProviderFactory,
    output: Path,
    resume: bool,
) -> ConfirmatoryStudyExecution:
    if output.exists() and not resume:
        raise FileExistsError(f"confirmatory output already exists: {output}")
    existing = read_confirmatory_records(output, config=config) if resume else ()
    task_by_id = {task.id: task for task in tasks}
    pairs = tuple(
        (task_id, repetition)
        for task_id in config.task_ids
        for repetition in range(config.repetitions)
    )
    completed_pairs = len(existing) // len(config.conditions)
    pending_pairs = pairs[completed_pairs:]
    semaphore = asyncio.Semaphore(config.experiment_workers)

    async def execute(pair: tuple[int, int]) -> tuple[ConfirmatoryRunRecord, ...]:
        task_id, repetition = pair
        task = task_by_id.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id} was not loaded")
        async with semaphore:
            return await run_confirmatory_pair(
                task=task,
                repetition=repetition,
                config=config,
                provider_factory=provider_factory,
            )

    running = [asyncio.create_task(execute(pair)) for pair in pending_pairs]
    executed = 0
    for task in running:
        records = await task
        _append_records(output, records)
        executed += len(records)
    return ConfirmatoryStudyExecution(
        executed_runs=executed,
        skipped_runs=len(existing),
        output=output,
    )
