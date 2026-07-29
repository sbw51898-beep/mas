from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchRun,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import DynamicPilotConfig


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    if _sha256(path) != expected.casefold():
        raise ValueError(f"{label} SHA-256 mismatch")


def _validate_provider_metadata(
    run: HiddenBenchRun,
    config: DynamicPilotConfig,
) -> None:
    items = (
        *run.hidden_pre_votes,
        *run.discussion_messages,
        *run.hidden_post_votes,
        *run.full_profile_votes,
    )
    for item in items:
        metadata = item.provider_metadata
        if metadata.get("model") != config.provider.model:
            raise ValueError(
                f"baseline task {run.task.id} provider model mismatch"
            )
        if float(metadata.get("temperature", -1)) != config.provider.temperature:
            raise ValueError(
                f"baseline task {run.task.id} provider temperature mismatch"
            )
        if metadata.get("thinking") != config.provider.thinking:
            raise ValueError(
                f"baseline task {run.task.id} provider thinking mismatch"
            )


def load_and_validate_frozen_baseline(
    root: Path,
    config: DynamicPilotConfig,
) -> dict[int, HiddenBenchRun]:
    frozen = config.frozen_baseline
    jsonl_path = root / frozen.jsonl
    report_path = root / frozen.report
    baseline_config_path = root / frozen.config
    _require_hash(
        jsonl_path,
        frozen.jsonl_sha256,
        "baseline JSONL",
    )
    _require_hash(
        report_path,
        frozen.report_sha256,
        "baseline report",
    )
    _require_hash(
        baseline_config_path,
        frozen.config_sha256,
        "baseline config",
    )
    dataset_path = root / "data" / "hiddenbench" / "benchmark.json"
    if dataset_path.is_file() and _sha256(dataset_path).upper() != (
        config.dataset_sha256.upper()
    ):
        raise ValueError("HiddenBench dataset SHA-256 mismatch")

    baseline_config = json.loads(
        baseline_config_path.read_text(encoding="utf-8")
    )
    task_ids = tuple(int(value) for value in baseline_config["screening_task_ids"])
    if tuple(baseline_config["agent_ids"]) != AGENT_IDS:
        raise ValueError("baseline agent IDs mismatch")
    if int(baseline_config["discussion_rounds"]) != 15:
        raise ValueError("baseline must contain 15 discussion rounds")
    if int(baseline_config["base_seed"]) != config.base_seed:
        raise ValueError("baseline seed mismatch")

    all_runs = tuple(
        HiddenBenchRun.model_validate_json(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    by_id = {run.task.id: run for run in all_runs}
    missing = set(config.pilot_task_ids) - set(by_id)
    if missing:
        raise ValueError(f"baseline missing pilot tasks: {sorted(missing)}")

    expected_order = tuple(AGENT_IDS[index % len(AGENT_IDS)] for index in range(60))
    pilot: dict[int, HiddenBenchRun] = {}
    for task_id in config.pilot_task_ids:
        run = by_id[task_id]
        if len(run.discussion_messages) != 60:
            raise ValueError(f"baseline task {task_id} must have 60 messages")
        actual_order = tuple(
            message.agent_id for message in run.discussion_messages
        )
        if actual_order != expected_order:
            raise ValueError(
                f"baseline task {task_id} is not fixed round-robin"
            )
        if any(
            message.turn_index != index
            or message.round_index != index // 4 + 1
            or len(message.visible_message_ids) != index
            for index, message in enumerate(run.discussion_messages)
        ):
            raise ValueError(f"baseline task {task_id} visibility mismatch")
        task_index = task_ids.index(task_id)
        expected_assignment = assign_hidden_information(
            run.task,
            seed=config.base_seed + task_index * 100,
        )
        if run.assignment != expected_assignment:
            raise ValueError(f"baseline task {task_id} assignment mismatch")
        post_answers = {vote.vote for vote in run.hidden_post_votes}
        if (
            len(post_answers) != 1
            or next(iter(post_answers)) == run.task.correct_answer
        ):
            raise ValueError(
                f"baseline task {task_id} is not an erroneous consensus case"
            )
        if run.provider_metadata.get("prompt_version") != config.prompt_version:
            raise ValueError(f"baseline task {task_id} prompt version mismatch")
        _validate_provider_metadata(run, config)
        pilot[task_id] = run
    return pilot
