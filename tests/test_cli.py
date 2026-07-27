from __future__ import annotations

from typer.testing import CliRunner

from mas_experiment.cli import app
from mas_experiment.traces import read_results


runner = CliRunner()


def test_cli_offline_run_creates_thirty_records(tmp_path) -> None:
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
    assert len(records) == 30
    assert {record["mode"] for record in records} == {
        "concurrent",
        "round_robin",
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
    assert "concurrent" in result.output
    assert "round_robin" in result.output
    assert "dynamic" in result.output
    assert "30 records" in result.output
