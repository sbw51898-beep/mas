from __future__ import annotations

import json
from pathlib import Path

import mas_experiment.cli as cli

from typer.testing import CliRunner

from mas_experiment.domain import AgentResponse, AgentRole, Message, Question
from mas_experiment.cli import app
from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_prompts import build_vote_user_prompt
from mas_experiment.hiddenbench_protocol import parse_hiddenbench_vote
from mas_experiment.providers import (
    DeterministicProvider,
    StabilityOfflineProvider,
)
from mas_experiment.traces import read_results


runner = CliRunner()
ROOT = Path(__file__).parents[1]
HIDDENBENCH_SCRIPT = (
    ROOT / "tests" / "fixtures" / "hiddenbench_script.json"
)
STABILITY_CONFIG = (
    ROOT / "configs/hiddenbench-ai-disclosure-stability.json"
)


class FailingInitialProvider(DeterministicProvider):
    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        if role.agent_id == "agent-b":
            raise RuntimeError("initial failure")
        return await super().generate(
            question=question,
            role=role,
            round_index=round_index,
            visible_messages=visible_messages,
            seed=seed,
        )


async def test_stability_offline_provider_returns_valid_outputs() -> None:
    task = load_hiddenbench_task(
        ROOT / "data/hiddenbench/benchmark.json",
        task_id=1,
        expected_sha256=(
            "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
        ),
    )
    provider = StabilityOfflineProvider()
    vote = await provider.complete(
        agent_id="agent-a",
        system_prompt=task.description,
        user_prompt=build_vote_user_prompt(
            task,
            (),
            phase="hidden_pre",
        ),
        seed=1,
        json_response=True,
    )
    message = await provider.complete(
        agent_id="agent-a",
        system_prompt=task.description,
        user_prompt="You are the first to speak.",
        seed=1,
        json_response=False,
    )
    audit = await provider.complete(
        agent_id="disclosure-auditor",
        system_prompt="Return JSON only.",
        user_prompt=(
            "PRIVATE FACTS:\n"
            '- private-fact:agent-a | owner=agent-a | private_fact="Fact A"\n'
            '- private-fact:agent-b | owner=agent-b | private_fact="Fact B"\n'
            "\nPUBLIC MESSAGES:\n"
            "m-1 | agent-a | I recommend A.\n"
        ),
        seed=1,
        json_response=True,
    )

    assert parse_hiddenbench_vote(task, vote.text)
    assert message.text
    assert json.loads(audit.text)["facts"]


def test_cli_offline_run_creates_forty_records(tmp_path) -> None:
    output = tmp_path / "results.jsonl"

    result = runner.invoke(
        app,
        [
            "run",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--seed",
            "20260727",
        ],
    )

    assert result.exit_code == 0, result.output
    records = read_results(output)
    assert len(records) == 40
    assert {record["mode"] for record in records} == {
        "independent",
        "round_robin",
        "random_order",
        "dynamic",
    }


def test_cli_summary_reports_each_mode(tmp_path) -> None:
    output = tmp_path / "results.jsonl"
    run_result = runner.invoke(
        app,
        ["run", "--provider", "offline", "--output", str(output)],
    )
    assert run_result.exit_code == 0, run_result.output

    result = runner.invoke(app, ["summarize", str(output)])

    assert result.exit_code == 0, result.output
    assert "independent" in result.output
    assert "round_robin" in result.output
    assert "dynamic" in result.output
    assert "40 records" in result.output


def test_formal_pilot_writes_three_complete_mode_records(tmp_path) -> None:
    output = tmp_path / "pilot.jsonl"

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = read_results(output)
    assert {record["mode"] for record in records} == {
        "independent",
        "round_robin",
        "dynamic",
    }
    assert all(len(record["responses"]) == 9 for record in records)
    assert output.with_suffix(".md").exists()


def test_formal_pilot_reuses_one_initial_snapshot(tmp_path) -> None:
    output = tmp_path / "pilot.jsonl"

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = read_results(output)
    initial_ids = {
        record["metadata"]["initial_state_id"]
        for record in records
    }
    assert len(initial_ids) == 1
    assert all(
        record["metadata"]["shared_initial_state"] is True
        for record in records
    )
    assert records[0]["responses"][:3] == records[1]["responses"][:3]
    assert records[1]["responses"][:3] == records[2]["responses"][:3]
    assert "shared initialization API requests=3" in result.output
    assert "follow-up API requests=18" in result.output
    assert "discussion API requests=21" in result.output
    assert "logical response slots=27" in result.output


def test_formal_pilot_initial_failure_creates_no_output(
    monkeypatch,
    tmp_path,
) -> None:
    output = tmp_path / "pilot.jsonl"
    monkeypatch.setattr(
        cli,
        "create_formal_provider",
        lambda provider_name: FailingInitialProvider(),
    )

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "initialization errors" in str(result.exception)
    assert not output.exists()
    assert not output.with_suffix(".md").exists()


def test_formal_pilot_refuses_to_overwrite_existing_output(tmp_path) -> None:
    output = tmp_path / "pilot.jsonl"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "formal-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert output.read_text(encoding="utf-8") == "existing"


def test_screening_pilot_writes_twenty_four_matched_records_and_audit(
    tmp_path,
) -> None:
    output = tmp_path / "screening.jsonl"

    result = runner.invoke(
        app,
        [
            "screening-pilot",
            "--provider",
            "offline",
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = read_results(output)
    assert len(records) == 24
    assert {record["mode"] for record in records} == {
        "independent",
        "round_robin",
        "random_order",
        "dynamic",
    }
    assert len(
        {
            record["metadata"]["initial_state_id"]
            for record in records
        }
    ) == 6
    assert all(len(record["responses"]) == 9 for record in records)
    assert all(not record["errors"] for record in records)
    assert {
        record["metadata"]["difficulty"] for record in records
    } == {"easy", "medium", "hard"}
    assert all(
        len(record["metadata"]["configuration_fingerprint"]) == 64
        for record in records
    )
    assert all(record["metadata"]["code_commit"] for record in records)
    assert output.with_suffix(".md").exists()
    assert output.with_suffix(".manifest.json").exists()
    assert "records=24" in result.output
    assert "discussion API requests=162" in result.output


def test_hiddenbench_showcase_writes_complete_gated_bundle(
    tmp_path,
) -> None:
    output = tmp_path / "showcase.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-showcase",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["task"]["id"] == 25
    assert len(record["discussion_messages"]) == 60
    assert output.with_suffix(".md").exists()
    assert output.with_suffix(".manifest.json").exists()
    assert output.with_suffix(".gate.json").exists()
    assert "logical response slots=72" in result.output


def test_hiddenbench_showcase_refuses_existing_artifact(tmp_path) -> None:
    output = tmp_path / "showcase.jsonl"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "hiddenbench-showcase",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert output.read_text(encoding="utf-8") == "existing"


def test_hiddenbench_screening_requires_approved_showcase_manifest(
    tmp_path,
) -> None:
    output = tmp_path / "screening.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-screening",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "approved-showcase-manifest" in result.output
    assert not output.exists()


def test_hiddenbench_screening_runs_only_locked_ids_after_gate(
    tmp_path,
) -> None:
    showcase = tmp_path / "showcase.jsonl"
    showcase_result = runner.invoke(
        app,
        [
            "hiddenbench-showcase",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(showcase),
            "--skip-connectivity",
        ],
    )
    assert showcase_result.exit_code == 0, showcase_result.output
    output = tmp_path / "screening.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-screening",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--approved-showcase-manifest",
            str(showcase.with_suffix(".manifest.json")),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(records) == 10
    assert {record["task"]["id"] for record in records} == {
        1,
        5,
        7,
        9,
        13,
        14,
        16,
        25,
        47,
        62,
    }
    assert all(len(record["discussion_messages"]) == 60 for record in records)
    assert "logical response slots=720" in result.output


def test_hiddenbench_screening_rejects_tampered_manifest(tmp_path) -> None:
    showcase = tmp_path / "showcase.jsonl"
    showcase_result = runner.invoke(
        app,
        [
            "hiddenbench-showcase",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(showcase),
            "--skip-connectivity",
        ],
    )
    assert showcase_result.exit_code == 0, showcase_result.output
    manifest = showcase.with_suffix(".manifest.json")
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "screening.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-screening",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--approved-showcase-manifest",
            str(manifest),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code != 0
    assert "manifest hash mismatch" in result.output
    assert not output.exists()


def test_hiddenbench_dynamic_pilot_help_lists_control_inputs() -> None:
    result = runner.invoke(app, ["hiddenbench-dynamic-pilot", "--help"])

    assert result.exit_code == 0
    assert "--frozen-baseline" in result.output
    assert "--config" in result.output
    assert "--output" in result.output


def test_hiddenbench_dynamic_pilot_writes_budget_matched_bundle(
    tmp_path,
) -> None:
    output = tmp_path / "dynamic.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-dynamic-pilot",
            "--provider",
            "scripted",
            "--script",
            str(HIDDENBENCH_SCRIPT),
            "--output",
            str(output),
            "--skip-connectivity",
        ],
    )

    assert result.exit_code == 0, result.output
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(records) == 3
    assert all(
        len(record["run"]["discussion_messages"]) == 60
        for record in records
    )
    assert output.with_suffix(".trace.jsonl").exists()
    assert output.with_suffix(".md").exists()
    assert output.with_suffix(".gate.json").exists()
    assert output.with_suffix(".manifest.json").exists()
    assert "logical response slots=216" in result.output
    assert "selector LLM calls=0" in result.output


def test_hiddenbench_stability_help_lists_resume_workers_and_judge() -> None:
    result = runner.invoke(app, ["hiddenbench-stability", "--help"])

    assert result.exit_code == 0
    assert "--resume" in result.output
    assert "--experiment-workers" in result.output
    assert "--judge-workers" in result.output
    assert "--skip-ai-judge" in result.output


def test_hiddenbench_stability_offline_writes_gated_bundle(
    tmp_path: Path,
) -> None:
    output = tmp_path / "stability.jsonl"

    result = runner.invoke(
        app,
        [
            "hiddenbench-stability",
            "--offline",
            "--smoke",
            "--config",
            str(STABILITY_CONFIG),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "gate passed" in result.output
    assert output.with_suffix(".ai-disclosure.jsonl").exists()
    assert output.with_suffix(".summary.csv").exists()
