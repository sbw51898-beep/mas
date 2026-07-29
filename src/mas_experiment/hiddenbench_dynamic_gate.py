from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchRun,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicHiddenBenchRun,
    DynamicPilotConfig,
    PilotGate,
)
from mas_experiment.hiddenbench_dynamic_selector import select_dynamic_speaker


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


def validate_dynamic_protocol(
    baseline_runs: dict[int, HiddenBenchRun],
    dynamic_runs: tuple[DynamicHiddenBenchRun, ...],
    config: DynamicPilotConfig,
    *,
    provider_name: str,
) -> PilotGate:
    by_id = {item.run.task.id: item for item in dynamic_runs}
    expected_ids = config.pilot_task_ids
    checks: dict[str, bool] = {
        "task_ids": tuple(sorted(by_id)) == tuple(sorted(expected_ids)),
        "selector_llm_calls": all(
            item.run.provider_metadata.get("selector_llm_calls") == 0
            for item in dynamic_runs
        ),
        "logical_slots": all(
            item.run.provider_metadata.get("logical_response_slots") == 72
            for item in dynamic_runs
        ),
    }
    budgets_ok = True
    assignments_ok = True
    visibility_ok = True
    trace_ok = True
    provider_ok = True
    for task_id in expected_ids:
        if task_id not in by_id or task_id not in baseline_runs:
            budgets_ok = assignments_ok = visibility_ok = trace_ok = False
            continue
        item = by_id[task_id]
        run = item.run
        assignments_ok &= run.assignment == baseline_runs[task_id].assignment
        budgets_ok &= len(run.discussion_messages) == 60
        budgets_ok &= Counter(
            message.agent_id for message in run.discussion_messages
        ) == {agent_id: 15 for agent_id in AGENT_IDS}
        budgets_ok &= len(item.selection_events) == 60
        visibility_ok &= all(
            message.turn_index == index
            and message.round_index == index // 4 + 1
            and message.visible_message_ids
            == tuple(
                earlier.message_id
                for earlier in run.discussion_messages[:index]
            )
            for index, message in enumerate(run.discussion_messages)
        )

        pre_stances = {
            vote.agent_id: vote.vote for vote in run.hidden_pre_votes
        }
        quotas = {agent_id: 15 for agent_id in AGENT_IDS}
        last_spoken = {agent_id: -1 for agent_id in AGENT_IDS}
        for turn_index, event in enumerate(item.selection_events):
            selected, candidates = select_dynamic_speaker(
                task=run.task,
                assignment=run.assignment,
                pre_stances=pre_stances,
                public_messages=run.discussion_messages[:turn_index],
                remaining_quotas=quotas,
                last_spoken_turns=last_spoken,
                config=config.selector,
                turn_index=turn_index,
            )
            actual = run.discussion_messages[turn_index].agent_id
            trace_ok &= event.selected_agent_id == selected == actual
            trace_ok &= event.candidates == candidates
            quotas[actual] -= 1
            last_spoken[actual] = turn_index
        trace_ok &= all(value == 0 for value in quotas.values())

        if provider_name == "deepseek":
            provider_items = (
                *run.hidden_pre_votes,
                *run.discussion_messages,
                *run.hidden_post_votes,
                *run.full_profile_votes,
            )
            provider_ok &= all(
                value.provider_metadata.get("model")
                == config.provider.model
                and float(
                    value.provider_metadata.get("temperature", -1)
                )
                == config.provider.temperature
                and value.provider_metadata.get("thinking")
                == config.provider.thinking
                for value in provider_items
            )
        else:
            provider_ok &= all(
                message.provider_metadata.get("provider")
                == "scripted-offline"
                for message in run.discussion_messages
            )
    checks.update(
        {
            "equal_speech_budgets": budgets_ok,
            "frozen_assignments": assignments_ok,
            "sequential_visibility": visibility_ok,
            "deterministic_trace": trace_ok,
            "provider_settings": provider_ok,
        }
    )
    return PilotGate(
        provider_name=provider_name,
        task_ids=expected_ids,
        checks=checks,
        passed=all(checks.values()),
    )
