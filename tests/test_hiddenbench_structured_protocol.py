from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from mas_experiment.cli import app
from mas_experiment.hiddenbench_data import load_hiddenbench_tasks
from mas_experiment.hiddenbench_structured_protocol import (
    TOTAL_MESSAGES,
    StructuredStudyConfig,
    load_structured_config,
    run_hiddenbench_structured_task,
)
from mas_experiment.hiddenbench_structured_study import (
    build_structured_gate,
    read_completed_study_records,
    run_structured_study,
)
from mas_experiment.hiddenbench_structured_study import derive_pair_seed
from mas_experiment.providers import StabilityOfflineProvider


ROOT = Path(__file__).resolve().parents[1]
STRUCTURED_CONFIG = ROOT / "configs" / "hiddenbench-structured-20260802.json"
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
runner = CliRunner()


def test_structured_config_validates_task_matrix() -> None:
    config = load_structured_config(STRUCTURED_CONFIG)
    assert config.task_ids == (1, 5, 7, 25)
    assert config.exchange_rounds == 2
    assert config.decide_passes == 1
    assert config.repetitions == 10


def test_structured_config_rejects_wrong_tasks(tmp_path: Path) -> None:
    payload = json.loads(STRUCTURED_CONFIG.read_text(encoding="utf-8"))
    payload["task_ids"] = [1, 2]
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        load_structured_config(path)
    except ValueError:
        return
    raise AssertionError("expected task_ids validation error")


def test_structured_offline_run_has_exchange_then_decide_shape() -> None:
    config = load_structured_config(STRUCTURED_CONFIG)
    tasks = tuple(
        task
        for task in load_hiddenbench_tasks(
            DATASET,
            expected_sha256=config.dataset_sha256,
        )
        if task.id in config.task_ids
    )
    seed = derive_pair_seed(
        config.base_seed,
        task_id=1,
        repetition=0,
    )
    run = asyncio.run(
        run_hiddenbench_structured_task(
            tasks[0],
            StabilityOfflineProvider(),
            seed=seed,
        )
    )
    messages = run.discussion_messages
    assert len(messages) == TOTAL_MESSAGES == 12
    assert [message.round_index for message in messages] == [
        1,
        1,
        1,
        1,
        2,
        2,
        2,
        2,
        3,
        3,
        3,
        3,
    ]
    assert [message.agent_id for message in messages][:4] == [
        "agent-a",
        "agent-b",
        "agent-c",
        "agent-d",
    ]
    assert "Share 1-2 decision-relevant facts" in messages[0].user_prompt
    assert (
        "Summarize the strongest evidence"
        in messages[8].user_prompt
    )
    assert len(run.hidden_pre_votes) == 4
    assert len(run.hidden_post_votes) == 4
    assert len(run.full_profile_votes) == 4


def test_structured_offline_writes_gated_bundle(tmp_path: Path) -> None:
    output = tmp_path / "structured.jsonl"
    result = runner.invoke(
        app,
        [
            "hiddenbench-structured",
            "--offline",
            "--config",
            str(STRUCTURED_CONFIG),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "gate passed" in result.output
    assert output.exists()
    assert output.with_suffix(".ai-disclosure.jsonl").exists()
    assert output.with_suffix(".summary.csv").exists()
    assert output.with_suffix(".gate.json").exists()


def test_structured_gate_requires_complete_audits(tmp_path: Path) -> None:
    config = load_structured_config(STRUCTURED_CONFIG)
    tasks = tuple(
        task
        for task in load_hiddenbench_tasks(
            DATASET,
            expected_sha256=config.dataset_sha256,
        )
        if task.id in config.task_ids
    )
    output = tmp_path / "structured.jsonl"
    asyncio.run(
        run_structured_study(
            tasks=tasks,
            config=config,
            provider_factory=StabilityOfflineProvider,
            output=output,
            resume=False,
        )
    )
    records = read_completed_study_records(output)
    gate = build_structured_gate(
        config,
        records,
        (),
        dataset_path=DATASET,
    )
    assert not gate.passed
    assert not gate.checks["complete_ai_audits"]
