from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Annotated, Any, NamedTuple

import typer

from mas_experiment.audit import (
    configuration_fingerprint,
    current_git_commit,
    write_sha256_manifest,
)
from mas_experiment.datasets import (
    AGENT_ROLES,
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    QUESTIONS,
    SCREENING_DIFFICULTIES,
    SCREENING_QUESTIONS,
    SCREENING_ROLES,
)
from mas_experiment.maf_adapter import (
    MAFModelProvider,
    MAFPromptProvider,
    build_maf_concurrent,
    build_maf_group_chat,
    create_maf_agents,
    maf_runtime_info,
)
from mas_experiment.hiddenbench_data import (
    HiddenBenchTask,
    load_hiddenbench_task,
    load_hiddenbench_tasks,
)
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS as HIDDENBENCH_AGENT_IDS,
    HiddenBenchRun,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicBundlePaths,
    load_dynamic_pilot_config,
)
from mas_experiment.hiddenbench_dynamic_gate import (
    load_and_validate_frozen_baseline,
    validate_dynamic_protocol,
)
from mas_experiment.hiddenbench_dynamic_protocol import (
    run_hiddenbench_dynamic_task,
)
from mas_experiment.hiddenbench_dynamic_reporting import (
    write_dynamic_pilot_bundle,
)
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_prompts import (
    build_hidden_system_prompt,
    build_vote_user_prompt,
)
from mas_experiment.hiddenbench_protocol import run_hiddenbench_task
from mas_experiment.hiddenbench_reporting import write_hiddenbench_bundle
from mas_experiment.orchestrations import (
    prepare_initial_state,
    run_dynamic,
    run_independent,
    run_random_order,
    run_round_robin,
    validate_initial_state,
)
from mas_experiment.providers import (
    DeepSeekSettings,
    DeterministicProvider,
    OpenAICompatibleSettings,
    ScriptedPromptProvider,
)
from mas_experiment.reporting import (
    build_pilot_report,
    build_screening_report,
    provider_request_totals,
)
from mas_experiment.traces import append_result, read_results


app = typer.Typer(no_args_is_help=True)


class FormalPilotCounts(NamedTuple):
    connectivity: int
    shared_initialization: int
    follow_up: int
    discussion: int
    logical_slots: int


class ScreeningCounts(NamedTuple):
    records: int
    connectivity: int
    discussion: int
    logical_slots: int


class HiddenBenchCounts(NamedTuple):
    records: int
    connectivity: int
    api_requests: int
    repair_requests: int
    logical_slots: int


HIDDENBENCH_DATASET = Path("data/hiddenbench/benchmark.json")
HIDDENBENCH_CONFIG = Path("configs/hiddenbench-screening.json")
HIDDENBENCH_DYNAMIC_CONFIG = Path(
    "configs/hiddenbench-dynamic-pilot.json"
)


def _load_hiddenbench_config() -> dict[str, Any]:
    payload = json.loads(
        HIDDENBENCH_CONFIG.read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise RuntimeError("HiddenBench configuration must be an object")
    return payload


def _scripted_outputs(
    script: Path,
    task: HiddenBenchTask,
) -> tuple[str, ...]:
    payload = json.loads(script.read_text(encoding="utf-8"))
    required = {
        "pre_vote",
        "discussion_template",
        "post_vote",
        "full_vote",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise typer.BadParameter(
            "script must contain pre_vote, discussion_template, "
            "post_vote, and full_vote"
        )
    if not all(isinstance(payload[key], str) for key in required):
        raise typer.BadParameter("all script values must be strings")

    def fill_vote(key: str) -> str:
        return payload[key].replace("{answer}", task.correct_answer)

    return (
        *(fill_vote("pre_vote") for _ in HIDDENBENCH_AGENT_IDS),
        *(
            payload["discussion_template"].format(
                index=index,
                answer=task.correct_answer,
            )
            for index in range(60)
        ),
        *(fill_vote("post_vote") for _ in HIDDENBENCH_AGENT_IDS),
        *(fill_vote("full_vote") for _ in HIDDENBENCH_AGENT_IDS),
    )


def create_hiddenbench_provider(
    provider_name: str,
    *,
    task: HiddenBenchTask,
    script: Path | None,
) -> Any:
    if provider_name == "scripted":
        if script is None:
            raise typer.BadParameter(
                "--script is required for scripted provider"
            )
        return ScriptedPromptProvider(_scripted_outputs(script, task))
    if provider_name == "deepseek":
        return MAFPromptProvider(DeepSeekSettings.from_env())
    raise typer.BadParameter("provider must be deepseek or scripted")


def _artifact_paths(
    output: Path,
    *,
    include_gate: bool,
) -> tuple[Path, ...]:
    paths = (
        output,
        output.with_suffix(".md"),
        output.with_suffix(".manifest.json"),
    )
    if include_gate:
        return (*paths, output.with_suffix(".gate.json"))
    return paths


def _refuse_existing_artifacts(
    output: Path,
    *,
    include_gate: bool,
    overwrite: bool,
) -> None:
    existing = [
        path
        for path in _artifact_paths(output, include_gate=include_gate)
        if path.exists()
    ]
    if existing and not overwrite:
        raise typer.BadParameter(
            "HiddenBench artifact already exists: "
            + ", ".join(str(path) for path in existing)
        )


def _validate_showcase_run(run: HiddenBenchRun) -> dict[str, bool]:
    if run.task.id != 25:
        raise RuntimeError("showcase gate requires HiddenBench task ID 25")
    if len(run.assignment.private_information) != 4:
        raise RuntimeError("showcase gate requires four private facts")
    if len(set(run.assignment.private_information.values())) != 4:
        raise RuntimeError("showcase private facts are not one-to-one")
    if len(run.discussion_messages) != 60:
        raise RuntimeError("showcase gate requires exactly 60 messages")
    expected_speakers = tuple(
        agent_id
        for _ in range(15)
        for agent_id in HIDDENBENCH_AGENT_IDS
    )
    if tuple(
        message.agent_id for message in run.discussion_messages
    ) != expected_speakers:
        raise RuntimeError("showcase discussion order is not fixed round-robin")

    hidden_items = (
        *run.hidden_pre_votes,
        *run.hidden_post_votes,
        *run.discussion_messages,
    )
    for item in hidden_items:
        own_fact = run.assignment.private_information[item.agent_id]
        if own_fact not in item.system_prompt:
            raise RuntimeError(
                f"showcase prompt omits own fact for {item.agent_id}"
            )
        peer_facts = {
            fact
            for agent_id, fact
            in run.assignment.private_information.items()
            if agent_id != item.agent_id
        }
        if any(fact in item.system_prompt for fact in peer_facts):
            raise RuntimeError(
                f"showcase prompt leaks peer fact to {item.agent_id}"
            )
    public_contents = tuple(
        message.content for message in run.discussion_messages
    )
    if any(
        not all(content in vote.user_prompt for content in public_contents)
        for vote in run.hidden_post_votes
    ):
        raise RuntimeError("showcase post vote does not contain full history")
    if any(
        not all(
            fact in vote.system_prompt
            for fact in run.task.hidden_information
        )
        for vote in run.full_profile_votes
    ):
        raise RuntimeError("showcase full profile omits private facts")
    if any(
        vote.vote not in run.task.possible_answers
        for vote in (
            *run.hidden_pre_votes,
            *run.hidden_post_votes,
            *run.full_profile_votes,
        )
    ):
        raise RuntimeError("showcase contains an invalid vote")
    return {
        "task_id_25": True,
        "one_to_one_private_information": True,
        "hidden_prompt_isolation": True,
        "fifteen_rounds_sixty_messages": True,
        "post_vote_full_history": True,
        "full_profile_complete": True,
        "all_votes_parseable": True,
    }


async def _hiddenbench_connectivity_probe(
    task: HiddenBenchTask,
    provider: Any,
    *,
    seed: int,
) -> int:
    assignment = assign_hidden_information(task, seed=seed)
    completion = await provider.complete(
        agent_id=HIDDENBENCH_AGENT_IDS[0],
        system_prompt=build_hidden_system_prompt(
            task,
            assignment,
            HIDDENBENCH_AGENT_IDS[0],
        ),
        user_prompt=build_vote_user_prompt(
            task,
            (),
            phase="hidden_pre",
        ),
        seed=seed,
        json_response=True,
    )
    return int(
        completion.provider_metadata.get("api_requests", 1) or 0
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_showcase_gate(
    run: HiddenBenchRun,
    manifest_path: Path,
    gate_path: Path,
) -> Path:
    checks = _validate_showcase_run(run)
    payload = {
        "gate_version": "hiddenbench-showcase-v1",
        "structural_validation_passed": True,
        "showcase_task_id": run.task.id,
        "run_id": run.run_id,
        "configuration_fingerprint": run.configuration_fingerprint,
        "dataset_sha256": _load_hiddenbench_config()["dataset_sha256"],
        "manifest_sha256": _sha256(manifest_path),
        "checks": checks,
    }
    gate_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return gate_path


def _gate_path_for_manifest(manifest_path: Path) -> Path:
    suffix = ".manifest.json"
    if not manifest_path.name.endswith(suffix):
        raise typer.BadParameter(
            "approved showcase manifest must end with .manifest.json"
        )
    return manifest_path.with_name(
        manifest_path.name[: -len(suffix)] + ".gate.json"
    )


def _verify_showcase_gate(manifest_path: Path) -> HiddenBenchRun:
    if not manifest_path.exists():
        raise typer.BadParameter(
            f"approved showcase manifest not found: {manifest_path}"
        )
    gate_path = _gate_path_for_manifest(manifest_path)
    if not gate_path.exists():
        raise typer.BadParameter(f"showcase gate not found: {gate_path}")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("manifest_sha256") != _sha256(manifest_path):
        raise typer.BadParameter("showcase manifest hash mismatch")
    if gate.get("structural_validation_passed") is not True:
        raise typer.BadParameter("showcase structural gate did not pass")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jsonl_entries = [
        item for item in manifest.get("files", [])
        if str(item.get("path", "")).endswith(".jsonl")
    ]
    if len(jsonl_entries) != 1:
        raise typer.BadParameter(
            "showcase manifest must contain one JSONL file"
        )
    entry = jsonl_entries[0]
    jsonl_path = manifest_path.parent / entry["path"]
    if not jsonl_path.exists() or _sha256(jsonl_path) != entry["sha256"]:
        raise typer.BadParameter("showcase JSONL hash mismatch")
    records = [
        line
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(records) != 1:
        raise typer.BadParameter("showcase JSONL must contain one run")
    run = HiddenBenchRun.model_validate_json(records[0])
    _validate_showcase_run(run)
    return run


def create_formal_provider(provider_name: str) -> Any:
    if provider_name == "offline":
        return DeterministicProvider()
    if provider_name == "deepseek":
        settings = DeepSeekSettings.from_env()
        agents = create_maf_agents(settings, FORMAL_PILOT_ROLES)
        return MAFModelProvider(
            {
                role.agent_id: agent
                for role, agent in zip(
                    FORMAL_PILOT_ROLES,
                    agents,
                    strict=True,
                )
            }
        )
    raise typer.BadParameter("provider must be deepseek or offline")


def create_screening_provider(provider_name: str) -> Any:
    if provider_name == "offline":
        return DeterministicProvider()
    if provider_name == "deepseek":
        settings = DeepSeekSettings.from_env()
        agents = create_maf_agents(settings, SCREENING_ROLES)
        return MAFModelProvider(
            {
                role.agent_id: agent
                for role, agent in zip(
                    SCREENING_ROLES,
                    agents,
                    strict=True,
                )
            }
        )
    raise typer.BadParameter("provider must be deepseek or offline")


async def _run_formal_pilot(
    *,
    provider_name: str,
    output: Path,
    seed: int,
    skip_connectivity: bool,
) -> FormalPilotCounts:
    provider = create_formal_provider(provider_name)
    connectivity_requests = 0
    if provider_name == "deepseek" and not skip_connectivity:
        probe = await provider.generate(
            question=FORMAL_PILOT_QUESTION,
            role=FORMAL_PILOT_ROLES[0],
            round_index=0,
            visible_messages=(),
            seed=seed,
        )
        connectivity_requests = int(
            probe.provider_metadata.get("api_requests", 1)
        )

    initial_state = await prepare_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        provider,
        seed=seed,
    )
    validate_initial_state(
        FORMAL_PILOT_QUESTION,
        FORMAL_PILOT_ROLES,
        initial_state,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")
    runners = (
        run_independent,
        run_round_robin,
        run_dynamic,
    )
    for runner in runners:
        result = await runner(
            FORMAL_PILOT_QUESTION,
            FORMAL_PILOT_ROLES,
            provider,
            seed=seed,
            initial_state=initial_state,
        )
        append_result(output, result)
        if len(result.responses) != 9 or result.errors:
            raise RuntimeError(
                f"{result.mode} incomplete: "
                f"{len(result.responses)} responses, "
                f"errors={list(result.errors)}"
            )

    records = read_results(output)
    report_path = output.with_suffix(".md")
    report_path.write_text(
        build_pilot_report(records),
        encoding="utf-8",
        newline="\n",
    )
    shared_initialization_requests = max(
        int(
            record.get("metadata", {}).get(
                "shared_initialization_api_requests",
                0,
            )
            or 0
        )
        for record in records
    )
    follow_up_requests = sum(
        int(
            record.get("metadata", {}).get(
                "mode_follow_up_api_requests",
                0,
            )
            or 0
        )
        for record in records
    )
    discussion_requests = (
        shared_initialization_requests + follow_up_requests
    )
    logical_response_slots = sum(
        len(record["responses"]) for record in records
    )
    return FormalPilotCounts(
        connectivity=connectivity_requests,
        shared_initialization=shared_initialization_requests,
        follow_up=follow_up_requests,
        discussion=discussion_requests,
        logical_slots=logical_response_slots,
    )


async def _run_screening_pilot(
    *,
    provider_name: str,
    output: Path,
    base_seed: int,
    repeats: int,
    skip_connectivity: bool,
) -> ScreeningCounts:
    provider = create_screening_provider(provider_name)
    connectivity_requests = 0
    if provider_name == "deepseek" and not skip_connectivity:
        probe = await provider.generate(
            question=SCREENING_QUESTIONS[0],
            role=SCREENING_ROLES[0],
            round_index=0,
            visible_messages=(),
            seed=base_seed,
        )
        connectivity_requests = int(
            probe.provider_metadata.get("api_requests", 1)
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")
    runners = (
        run_independent,
        run_round_robin,
        run_random_order,
        run_dynamic,
    )
    code_commit = current_git_commit()
    for task_index, question in enumerate(SCREENING_QUESTIONS):
        for repeat_index in range(repeats):
            seed = base_seed + task_index * 100 + repeat_index
            initial_state = await prepare_initial_state(
                question,
                SCREENING_ROLES,
                provider,
                seed=seed,
            )
            validate_initial_state(
                question,
                SCREENING_ROLES,
                initial_state,
            )
            fingerprint = configuration_fingerprint(
                question,
                SCREENING_ROLES,
                seed=seed,
            )
            for run_mode in runners:
                result = await run_mode(
                    question,
                    SCREENING_ROLES,
                    provider,
                    seed=seed,
                    initial_state=initial_state,
                )
                if len(result.responses) != 9 or result.errors:
                    raise RuntimeError(
                        f"{question.question_id}/{result.mode} incomplete: "
                        f"{len(result.responses)} responses, "
                        f"errors={list(result.errors)}"
                    )
                metadata = {
                    **dict(result.metadata),
                    "difficulty": SCREENING_DIFFICULTIES[
                        question.question_id
                    ],
                    "task_index": task_index,
                    "repeat_index": repeat_index,
                    "base_seed": base_seed,
                    "configuration_fingerprint": fingerprint,
                    "code_commit": code_commit,
                }
                append_result(
                    output,
                    result.model_copy(update={"metadata": metadata}),
                )

    records = read_results(output)
    report_path = output.with_suffix(".md")
    report_path.write_text(
        build_screening_report(records),
        encoding="utf-8",
        newline="\n",
    )
    write_sha256_manifest(
        (output, report_path),
        output.with_suffix(".manifest.json"),
    )
    discussion_requests, _ = provider_request_totals(records)
    return ScreeningCounts(
        records=len(records),
        connectivity=connectivity_requests,
        discussion=discussion_requests,
        logical_slots=sum(len(record["responses"]) for record in records),
    )


async def _run_hiddenbench_showcase(
    *,
    provider_name: str,
    script: Path | None,
    output: Path,
    seed: int,
    skip_connectivity: bool,
) -> HiddenBenchCounts:
    config = _load_hiddenbench_config()
    task = load_hiddenbench_task(
        HIDDENBENCH_DATASET,
        task_id=int(config["showcase_task_id"]),
        expected_sha256=str(config["dataset_sha256"]),
    )
    provider = create_hiddenbench_provider(
        provider_name,
        task=task,
        script=script,
    )
    connectivity_requests = 0
    if provider_name == "deepseek" and not skip_connectivity:
        connectivity_requests = await _hiddenbench_connectivity_probe(
            task,
            provider,
            seed=seed,
        )
    raw_run = await run_hiddenbench_task(
        task,
        provider,
        seed=seed,
        discussion_rounds=int(config["discussion_rounds"]),
    )
    run = score_hiddenbench_run(raw_run)
    _validate_showcase_run(run)
    _, _, manifest_path = write_hiddenbench_bundle(
        (run,),
        output,
        report_kind="showcase",
    )
    _write_showcase_gate(
        run,
        manifest_path,
        output.with_suffix(".gate.json"),
    )
    return HiddenBenchCounts(
        records=1,
        connectivity=connectivity_requests,
        api_requests=run.metrics.api_requests,
        repair_requests=run.metrics.repair_requests,
        logical_slots=int(
            run.provider_metadata.get("logical_response_slots", 0)
        ),
    )


async def _run_hiddenbench_screening(
    *,
    provider_name: str,
    script: Path | None,
    approved_showcase_manifest: Path,
    output: Path,
    base_seed: int,
    skip_connectivity: bool,
) -> HiddenBenchCounts:
    _verify_showcase_gate(approved_showcase_manifest)
    config = _load_hiddenbench_config()
    all_tasks = load_hiddenbench_tasks(
        HIDDENBENCH_DATASET,
        expected_sha256=str(config["dataset_sha256"]),
    )
    by_id = {task.id: task for task in all_tasks}
    task_ids = tuple(int(value) for value in config["screening_task_ids"])
    tasks = tuple(by_id[task_id] for task_id in task_ids)

    shared_provider = (
        create_hiddenbench_provider(
            provider_name,
            task=tasks[0],
            script=script,
        )
        if provider_name == "deepseek"
        else None
    )
    connectivity_requests = 0
    if (
        provider_name == "deepseek"
        and not skip_connectivity
        and shared_provider is not None
    ):
        connectivity_requests = await _hiddenbench_connectivity_probe(
            tasks[0],
            shared_provider,
            seed=base_seed,
        )

    runs: list[HiddenBenchRun] = []
    for task_index, task in enumerate(tasks):
        seed = base_seed + task_index * 100
        provider = shared_provider or create_hiddenbench_provider(
            provider_name,
            task=task,
            script=script,
        )
        raw_run = await run_hiddenbench_task(
            task,
            provider,
            seed=seed,
            discussion_rounds=int(config["discussion_rounds"]),
        )
        runs.append(score_hiddenbench_run(raw_run))

    write_hiddenbench_bundle(
        tuple(runs),
        output,
        report_kind="screening",
    )
    return HiddenBenchCounts(
        records=len(runs),
        connectivity=connectivity_requests,
        api_requests=sum(run.metrics.api_requests for run in runs),
        repair_requests=sum(
            run.metrics.repair_requests for run in runs
        ),
        logical_slots=sum(
            int(
                run.provider_metadata.get(
                    "logical_response_slots",
                    0,
                )
            )
            for run in runs
        ),
    )


async def _run_hiddenbench_dynamic_pilot(
    *,
    provider_name: str,
    script: Path | None,
    config_path: Path,
    frozen_baseline: Path,
    output: Path,
    skip_connectivity: bool,
) -> tuple[HiddenBenchCounts, DynamicBundlePaths]:
    config = load_dynamic_pilot_config(config_path)
    if frozen_baseline != Path(config.frozen_baseline.jsonl):
        frozen = config.frozen_baseline.model_copy(
            update={"jsonl": str(frozen_baseline)}
        )
        config = config.model_copy(update={"frozen_baseline": frozen})

    baseline_runs = load_and_validate_frozen_baseline(Path.cwd(), config)
    shared_provider = (
        create_hiddenbench_provider(
            provider_name,
            task=baseline_runs[config.pilot_task_ids[0]].task,
            script=script,
        )
        if provider_name == "deepseek"
        else None
    )
    connectivity_requests = 0
    if (
        provider_name == "deepseek"
        and not skip_connectivity
        and shared_provider is not None
    ):
        connectivity_requests = await _hiddenbench_connectivity_probe(
            baseline_runs[config.pilot_task_ids[0]].task,
            shared_provider,
            seed=config.base_seed,
        )

    dynamic_runs = []
    for task_id in config.pilot_task_ids:
        baseline = baseline_runs[task_id]
        provider = shared_provider or create_hiddenbench_provider(
            provider_name,
            task=baseline.task,
            script=script,
        )
        dynamic_runs.append(
            await run_hiddenbench_dynamic_task(
                baseline.task,
                provider,
                seed=baseline.assignment.seed,
                assignment=baseline.assignment,
                baseline_run_id=baseline.run_id,
                config=config,
            )
        )
    dynamic_tuple = tuple(dynamic_runs)
    gate = validate_dynamic_protocol(
        baseline_runs,
        dynamic_tuple,
        config,
        provider_name=provider_name,
    )
    paths = write_dynamic_pilot_bundle(
        baseline_runs=baseline_runs,
        dynamic_runs=dynamic_tuple,
        gate=gate,
        output=output,
    )
    return (
        HiddenBenchCounts(
            records=len(dynamic_runs),
            connectivity=connectivity_requests,
            api_requests=sum(
                item.run.metrics.api_requests for item in dynamic_runs
            ),
            repair_requests=sum(
                item.run.metrics.repair_requests for item in dynamic_runs
            ),
            logical_slots=sum(
                int(
                    item.run.provider_metadata.get(
                        "logical_response_slots",
                        0,
                    )
                )
                for item in dynamic_runs
            ),
        ),
        paths,
    )


async def _run_experiments(
    *,
    provider_name: str,
    output: Path,
    seed: int,
    mode: str,
    limit: int,
) -> int:
    if provider_name == "offline":
        provider = DeterministicProvider()
    elif provider_name == "openai-compatible":
        settings = OpenAICompatibleSettings.from_env()
        agents = create_maf_agents(settings, AGENT_ROLES)
        provider = MAFModelProvider(
            {role.agent_id: agent for role, agent in zip(AGENT_ROLES, agents)}
        )
    else:
        raise typer.BadParameter(
            "provider must be offline or openai-compatible"
        )

    selected_modes = (
        ("independent", "round_robin", "random_order", "dynamic")
        if mode == "all"
        else (mode,)
    )
    if any(
        selected
        not in {
            "concurrent",
            "independent",
            "round_robin",
            "random_order",
            "dynamic",
        }
        for selected in selected_modes
    ):
        raise typer.BadParameter(
            "mode must be all, independent, round_robin, "
            "random_order, or dynamic"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")
    completed = 0
    for question in QUESTIONS[:limit]:
        for selected_mode in selected_modes:
            if selected_mode in {"concurrent", "independent"}:
                result = await run_independent(
                    question, AGENT_ROLES, provider, seed=seed
                )
            elif selected_mode == "round_robin":
                result = await run_round_robin(
                    question,
                    AGENT_ROLES,
                    provider,
                    seed=seed,
                )
            elif selected_mode == "random_order":
                result = await run_random_order(
                    question,
                    AGENT_ROLES,
                    provider,
                    seed=seed,
                )
            else:
                result = await run_dynamic(
                    question,
                    AGENT_ROLES,
                    provider,
                    seed=seed,
                )
            append_result(output, result)
            completed += 1
    return completed


@app.command("run")
def run_command(
    output: Annotated[
        Path,
        typer.Option(help="Destination JSONL file."),
    ] = Path("artifacts/results.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="offline or openai-compatible"),
    ] = "offline",
    mode: Annotated[
        str,
        typer.Option(
            help="all, independent, round_robin, random_order, or dynamic"
        ),
    ] = "all",
    seed: Annotated[int, typer.Option()] = 20260727,
    limit: Annotated[int, typer.Option(min=1, max=10)] = 10,
) -> None:
    completed = asyncio.run(
        _run_experiments(
            provider_name=provider,
            output=output,
            seed=seed,
            mode=mode,
            limit=limit,
        )
    )
    typer.echo(f"Completed {completed} records -> {output}")


@app.command("formal-pilot")
def formal_pilot_command(
    output: Annotated[
        Path,
        typer.Option(help="Destination JSONL file."),
    ] = Path("artifacts/deepseek-formal-pilot.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="deepseek or offline"),
    ] = "deepseek",
    seed: Annotated[int, typer.Option()] = 20260727,
    skip_connectivity: Annotated[
        bool,
        typer.Option(help="Skip the uncounted connectivity probe."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(help="Replace an existing output file."),
    ] = False,
) -> None:
    if output.exists() and not overwrite:
        raise typer.BadParameter(
            f"output already exists: {output}"
        )
    counts = asyncio.run(
        _run_formal_pilot(
            provider_name=provider,
            output=output,
            seed=seed,
            skip_connectivity=skip_connectivity,
        )
    )
    typer.echo(
        f"Completed formal pilot -> {output}; "
        f"report -> {output.with_suffix('.md')}; "
        f"connectivity API requests={counts.connectivity}; "
        "shared initialization API requests="
        f"{counts.shared_initialization}; "
        f"follow-up API requests={counts.follow_up}; "
        f"discussion API requests={counts.discussion}; "
        f"logical response slots={counts.logical_slots}"
    )


@app.command("screening-pilot")
def screening_pilot_command(
    output: Annotated[
        Path,
        typer.Option(help="Destination JSONL file."),
    ] = Path("artifacts/deepseek-screening-20260727.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="deepseek or offline"),
    ] = "deepseek",
    base_seed: Annotated[int, typer.Option()] = 20260727,
    repeats: Annotated[int, typer.Option(min=1, max=10)] = 2,
    skip_connectivity: Annotated[
        bool,
        typer.Option(help="Skip the uncounted connectivity probe."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(help="Replace existing screening artifacts."),
    ] = False,
) -> None:
    artifacts = (
        output,
        output.with_suffix(".md"),
        output.with_suffix(".manifest.json"),
    )
    existing = [path for path in artifacts if path.exists()]
    if existing and not overwrite:
        raise typer.BadParameter(
            "screening artifact already exists: "
            + ", ".join(str(path) for path in existing)
        )
    counts = asyncio.run(
        _run_screening_pilot(
            provider_name=provider,
            output=output,
            base_seed=base_seed,
            repeats=repeats,
            skip_connectivity=skip_connectivity,
        )
    )
    typer.echo(
        f"Completed screening -> {output}; "
        f"records={counts.records}; "
        f"connectivity API requests={counts.connectivity}; "
        f"discussion API requests={counts.discussion}; "
        f"logical response slots={counts.logical_slots}; "
        f"report={output.with_suffix('.md')}; "
        f"manifest={output.with_suffix('.manifest.json')}"
    )


@app.command("hiddenbench-showcase")
def hiddenbench_showcase_command(
    output: Annotated[
        Path,
        typer.Option(help="Destination JSONL file."),
    ] = Path("artifacts/hiddenbench-showcase-20260728.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="deepseek or scripted"),
    ] = "deepseek",
    script: Annotated[
        Path | None,
        typer.Option(help="Strict offline script for scripted provider."),
    ] = None,
    seed: Annotated[int, typer.Option()] = 20260728,
    skip_connectivity: Annotated[
        bool,
        typer.Option(help="Skip the uncounted connectivity probe."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(help="Replace existing showcase artifacts."),
    ] = False,
) -> None:
    _refuse_existing_artifacts(
        output,
        include_gate=True,
        overwrite=overwrite,
    )
    counts = asyncio.run(
        _run_hiddenbench_showcase(
            provider_name=provider,
            script=script,
            output=output,
            seed=seed,
            skip_connectivity=skip_connectivity,
        )
    )
    typer.echo(
        f"Completed HiddenBench showcase -> {output}; "
        f"records={counts.records}; "
        f"connectivity API requests={counts.connectivity}; "
        f"formal API requests={counts.api_requests}; "
        f"repair requests={counts.repair_requests}; "
        f"logical response slots={counts.logical_slots}; "
        f"report={output.with_suffix('.md')}; "
        f"manifest={output.with_suffix('.manifest.json')}; "
        f"gate={output.with_suffix('.gate.json')}"
    )


@app.command("hiddenbench-screening")
def hiddenbench_screening_command(
    approved_showcase_manifest: Annotated[
        Path,
        typer.Option(
            help="Validated ID 25 showcase manifest approved by the user."
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(help="Destination JSONL file."),
    ] = Path("artifacts/hiddenbench-screening-20260728.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="deepseek or scripted"),
    ] = "deepseek",
    script: Annotated[
        Path | None,
        typer.Option(help="Strict offline script for scripted provider."),
    ] = None,
    base_seed: Annotated[int, typer.Option()] = 20260728,
    skip_connectivity: Annotated[
        bool,
        typer.Option(help="Skip the uncounted connectivity probe."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(help="Replace existing screening artifacts."),
    ] = False,
) -> None:
    _refuse_existing_artifacts(
        output,
        include_gate=False,
        overwrite=overwrite,
    )
    counts = asyncio.run(
        _run_hiddenbench_screening(
            provider_name=provider,
            script=script,
            approved_showcase_manifest=approved_showcase_manifest,
            output=output,
            base_seed=base_seed,
            skip_connectivity=skip_connectivity,
        )
    )
    typer.echo(
        f"Completed HiddenBench screening -> {output}; "
        f"records={counts.records}; "
        f"connectivity API requests={counts.connectivity}; "
        f"formal API requests={counts.api_requests}; "
        f"repair requests={counts.repair_requests}; "
        f"logical response slots={counts.logical_slots}; "
        f"report={output.with_suffix('.md')}; "
        f"manifest={output.with_suffix('.manifest.json')}"
    )


@app.command("hiddenbench-dynamic-pilot")
def hiddenbench_dynamic_pilot_command(
    output: Annotated[
        Path,
        typer.Option(help="Destination dynamic JSONL file."),
    ] = Path("artifacts/hiddenbench-dynamic-pilot-20260729.jsonl"),
    provider: Annotated[
        str,
        typer.Option(help="deepseek or scripted"),
    ] = "deepseek",
    script: Annotated[
        Path | None,
        typer.Option(help="Strict offline script for scripted provider."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(help="Locked dynamic pilot configuration."),
    ] = HIDDENBENCH_DYNAMIC_CONFIG,
    frozen_baseline: Annotated[
        Path,
        typer.Option(help="Frozen fixed round-robin baseline JSONL."),
    ] = Path("artifacts/hiddenbench-screening-20260728-v2.jsonl"),
    skip_connectivity: Annotated[
        bool,
        typer.Option(help="Skip the uncounted connectivity probe."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(help="Replace existing dynamic pilot artifacts."),
    ] = False,
) -> None:
    dynamic_paths = (
        output,
        output.with_suffix(".trace.jsonl"),
        output.with_suffix(".md"),
        output.with_suffix(".gate.json"),
        output.with_suffix(".manifest.json"),
    )
    existing = [path for path in dynamic_paths if path.exists()]
    if existing and not overwrite:
        raise typer.BadParameter(
            "HiddenBench dynamic artifact already exists: "
            + ", ".join(str(path) for path in existing)
        )
    counts, paths = asyncio.run(
        _run_hiddenbench_dynamic_pilot(
            provider_name=provider,
            script=script,
            config_path=config,
            frozen_baseline=frozen_baseline,
            output=output,
            skip_connectivity=skip_connectivity,
        )
    )
    typer.echo(
        f"Completed HiddenBench dynamic pilot -> {paths.runs}; "
        f"records={counts.records}; "
        f"connectivity API requests={counts.connectivity}; "
        f"formal API requests={counts.api_requests}; "
        f"repair requests={counts.repair_requests}; "
        f"logical response slots={counts.logical_slots}; "
        "selector LLM calls=0; "
        f"trace={paths.trace}; report={paths.report}; "
        f"gate={paths.gate}; manifest={paths.manifest}"
    )


@app.command("summarize")
def summarize_command(path: Path) -> None:
    records = read_results(path)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["mode"]].append(record)
    typer.echo(f"{len(records)} records")
    typer.echo(
        "mode\taccuracy\tmajority_share\tdisagreement\tentropy"
    )
    for mode in sorted(grouped):
        metrics = [
            record["metrics"]
            for record in grouped[mode]
            if record.get("metrics")
        ]
        typer.echo(
            f"{mode}\t"
            f"{mean(item['accuracy'] for item in metrics):.3f}\t"
            f"{mean(item['majority_share'] for item in metrics):.3f}\t"
            f"{mean(item['pairwise_disagreement'] for item in metrics):.3f}\t"
            f"{mean(item['answer_entropy'] for item in metrics):.3f}"
        )


@app.command("maf-smoke")
def maf_smoke_command(
    mode: Annotated[
        str,
        typer.Option(help="concurrent or group-chat"),
    ] = "concurrent",
) -> None:
    settings = OpenAICompatibleSettings.from_env()
    agents = create_maf_agents(settings, AGENT_ROLES)
    if mode == "concurrent":
        build_maf_concurrent(agents)
    elif mode == "group-chat":
        build_maf_group_chat(agents, mode="round_robin", max_turns=9)
    else:
        raise typer.BadParameter("mode must be concurrent or group-chat")
    info = maf_runtime_info()
    typer.echo(
        "Built MAF workflow with "
        f"core={info['agent_framework']} "
        f"orchestrations={info['orchestrations']}"
    )
