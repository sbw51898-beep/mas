from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Annotated, Any, NamedTuple

import typer

from mas_experiment.datasets import (
    AGENT_ROLES,
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    QUESTIONS,
)
from mas_experiment.maf_adapter import (
    MAFModelProvider,
    build_maf_concurrent,
    build_maf_group_chat,
    create_maf_agents,
    maf_runtime_info,
)
from mas_experiment.orchestrations import (
    prepare_initial_state,
    run_dynamic,
    run_independent,
    run_round_robin,
    validate_initial_state,
)
from mas_experiment.providers import (
    DeepSeekSettings,
    DeterministicProvider,
    OpenAICompatibleSettings,
)
from mas_experiment.reporting import build_pilot_report
from mas_experiment.traces import append_result, read_results


app = typer.Typer(no_args_is_help=True)


class FormalPilotCounts(NamedTuple):
    connectivity: int
    shared_initialization: int
    follow_up: int
    discussion: int
    logical_slots: int


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
        ("independent", "round_robin", "dynamic")
        if mode == "all"
        else (mode,)
    )
    if any(
        selected
        not in {"concurrent", "independent", "round_robin", "dynamic"}
        for selected in selected_modes
    ):
        raise typer.BadParameter(
            "mode must be all, independent, round_robin, or dynamic"
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
        typer.Option(help="all, independent, round_robin, or dynamic"),
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
