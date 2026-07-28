from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_protocol import run_hiddenbench_task
from mas_experiment.hiddenbench_reporting import (
    SecretLeakError,
    build_screening_report,
    build_showcase_report,
    write_hiddenbench_bundle,
)
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
EXPECTED_SHA = (
    "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
)
TASK = load_hiddenbench_task(
    DATASET,
    task_id=25,
    expected_sha256=EXPECTED_SHA,
)


def vote_text() -> str:
    return json.dumps(
        {
            "vote": "Station Delta",
            "rationale": "All constraints favor Station Delta.",
        }
    )


async def make_run():
    outputs = (
        *(vote_text() for _ in range(4)),
        *(
            f"Discussion statement {index:02d} about Station Delta."
            for index in range(60)
        ),
        *(vote_text() for _ in range(4)),
        *(vote_text() for _ in range(4)),
    )
    raw = await run_hiddenbench_task(
        TASK,
        ScriptedPromptProvider(outputs),
        seed=20260728,
    )
    return score_hiddenbench_run(raw)


@pytest.mark.asyncio
async def test_showcase_report_contains_complete_teacher_material() -> None:
    run = await make_run()

    report = build_showcase_report(run)

    assert "Systematic Failures in Collective Reasoning" in report
    assert "https://arxiv.org/abs/2505.11556" in report
    assert "https://github.com/multi-agent-systems-failure-taxonomy/MAST" in report
    assert TASK.description in report
    assert TASK.correct_answer in report
    assert all(item in report for item in TASK.shared_information)
    assert all(item in report for item in TASK.hidden_information)
    assert all(agent_id in report for agent_id in run.assignment.private_information)
    assert all(
        message.content in report for message in run.discussion_messages
    )
    assert "Round 01" in report
    assert "Round 15" in report
    assert "Y_pre_average" in report
    assert "FM-2.4" in report
    assert "单题、单种子" in report
    assert run.configuration_fingerprint in report
    assert run.code_commit in report


@pytest.mark.asyncio
async def test_bundle_writes_jsonl_markdown_and_valid_manifest(
    tmp_path: Path,
) -> None:
    run = await make_run()
    output = tmp_path / "showcase.jsonl"

    jsonl_path, report_path, manifest_path = write_hiddenbench_bundle(
        (run,),
        output,
        report_kind="showcase",
    )

    assert jsonl_path == output
    assert report_path == output.with_suffix(".md")
    assert manifest_path == output.with_suffix(".manifest.json")
    record = json.loads(jsonl_path.read_text(encoding="utf-8"))
    assert record["task"]["id"] == 25
    assert len(record["discussion_messages"]) == 60
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_by_name = {
        item["path"]: item for item in manifest["files"]
    }
    for path in (jsonl_path, report_path):
        assert manifest_by_name[path.name]["sha256"] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest()


@pytest.mark.asyncio
async def test_secret_like_metadata_is_rejected_before_writing(
    tmp_path: Path,
) -> None:
    run = await make_run()
    unsafe = run.model_copy(
        update={
            "provider_metadata": {
                **run.provider_metadata,
                "api_key": "sk-1234567890abcdefghijklmnop",
            }
        }
    )
    output = tmp_path / "unsafe.jsonl"

    with pytest.raises(SecretLeakError, match="sensitive field"):
        write_hiddenbench_bundle(
            (unsafe,),
            output,
            report_kind="showcase",
        )

    assert not output.exists()
    assert not output.with_suffix(".md").exists()
    assert not output.with_suffix(".manifest.json").exists()


@pytest.mark.asyncio
async def test_screening_report_labels_scope_as_non_equivalent() -> None:
    run = await make_run()

    report = build_screening_report((run,))

    assert "筛选实验" in report
    assert "65 题" in report
    assert "不能" in report
    assert "30.1%" in report
    assert "80.7%" in report
