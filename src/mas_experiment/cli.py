from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Annotated

import typer

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS
from mas_experiment.maf_adapter import (
    MAFModelProvider,
    build_maf_concurrent,
    build_maf_group_chat,
    create_maf_agents,
    maf_runtime_info,
)
from mas_experiment.orchestrations import (
    run_dynamic,
    run_independent,
    run_round_robin,
)
from mas_experiment.providers import (
    DeterministicProvider,
    OpenAICompatibleSettings,
)
from mas_experiment.traces import append_result, read_results


app = typer.Typer(no_args_is_help=True)


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
