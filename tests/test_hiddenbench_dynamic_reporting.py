from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mas_experiment.hiddenbench_dynamic_domain import load_dynamic_pilot_config
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
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).parents[1]
CONFIG = load_dynamic_pilot_config(
    ROOT / "configs" / "hiddenbench-dynamic-pilot.json"
)


def scripted_outputs(task) -> tuple[str, ...]:
    answer = task.possible_answers[0]
    vote = json.dumps(
        {"vote": answer, "rationale": f"Evidence favors {answer}."}
    )
    return (
        *(vote for _ in range(4)),
        *(
            f"Discussion statement {index:02d} supports {answer}."
            for index in range(60)
        ),
        *(vote for _ in range(4)),
        *(vote for _ in range(4)),
    )


def build_dynamic_runs():
    baseline = load_and_validate_frozen_baseline(ROOT, CONFIG)
    dynamic = []
    for task_id in CONFIG.pilot_task_ids:
        frozen = baseline[task_id]
        dynamic.append(
            asyncio.run(
                run_hiddenbench_dynamic_task(
                    frozen.task,
                    ScriptedPromptProvider(scripted_outputs(frozen.task)),
                    seed=frozen.assignment.seed,
                    assignment=frozen.assignment,
                    baseline_run_id=frozen.run_id,
                    config=CONFIG,
                )
            )
        )
    return baseline, tuple(dynamic)


def test_bundle_writes_runs_trace_report_gate_and_manifest(
    tmp_path: Path,
) -> None:
    baseline, dynamic = build_dynamic_runs()
    gate = validate_dynamic_protocol(
        baseline,
        dynamic,
        CONFIG,
        provider_name="scripted",
    )

    paths = write_dynamic_pilot_bundle(
        baseline_runs=baseline,
        dynamic_runs=dynamic,
        gate=gate,
        output=tmp_path / "hiddenbench-dynamic-pilot.jsonl",
    )

    assert gate.passed is True
    assert paths.runs.exists()
    assert paths.trace.exists()
    assert paths.report.exists()
    assert paths.gate.exists()
    assert paths.manifest.exists()
    assert len(paths.trace.read_text(encoding="utf-8").splitlines()) == 180
    report = paths.report.read_text(encoding="utf-8")
    assert "每个 Agent 15 次" in report
    assert "选择器 LLM 调用：0" in report
    assert "Token 预算并未被强制设为相等" in report
    assert "人工复核状态：pending" in report
