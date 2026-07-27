from __future__ import annotations

import mas_experiment.cli as cli

from typer.testing import CliRunner

from mas_experiment.domain import AgentResponse, AgentRole, Message, Question
from mas_experiment.cli import app
from mas_experiment.providers import DeterministicProvider
from mas_experiment.traces import read_results


runner = CliRunner()


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
