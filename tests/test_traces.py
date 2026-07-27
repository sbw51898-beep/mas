from __future__ import annotations

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS
from mas_experiment.domain import ExperimentResult
from mas_experiment.traces import append_result, read_results


def result_with_secret() -> ExperimentResult:
    return ExperimentResult(
        run_id="run-1",
        mode="concurrent",
        seed=20260727,
        question=QUESTIONS[0],
        roles=AGENT_ROLES,
        messages=(),
        responses=(),
        metadata={
            "api_key": "secret-value",
            "nested": {"Authorization": "Bearer secret-value"},
            "model": "offline",
        },
    )


def test_trace_redacts_secrets_recursively(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"

    append_result(path, result_with_secret())
    content = path.read_text(encoding="utf-8")

    assert "secret-value" not in content
    assert "Bearer" not in content
    assert content.count("[REDACTED]") == 2


def test_trace_round_trip_preserves_result_shape(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    append_result(path, result_with_secret())

    records = read_results(path)

    assert len(records) == 1
    assert records[0]["run_id"] == "run-1"
    assert records[0]["question"]["question_id"] == "q01"
    assert records[0]["metadata"]["model"] == "offline"
