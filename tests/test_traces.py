from __future__ import annotations

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS
from mas_experiment.domain import AgentResponse, ExperimentResult
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


def test_trace_redacts_secrets_inside_provider_metadata(tmp_path) -> None:
    response = AgentResponse(
        response_id="r1",
        agent_id="agent-a",
        round_index=0,
        answer="A",
        probabilities={"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1},
        reasoning="A reason.",
        raw_text="{}",
        changed_from_previous=False,
        provider_metadata={
            "usage": {"input_token_count": 10},
            "transport": {
                "api_key": "provider-key",
                "authorization": "Bearer provider-key",
                "refresh_token": "provider-token",
                "client_secret": "provider-secret",
            },
        },
    )
    result = result_with_secret().model_copy(
        update={"responses": (response,)}
    )
    path = tmp_path / "provider-trace.jsonl"

    append_result(path, result)
    content = path.read_text(encoding="utf-8")

    assert "provider-key" not in content
    assert "provider-token" not in content
    assert "provider-secret" not in content
    assert '"input_token_count": 10' in content
