from __future__ import annotations

from mas_experiment.reporting import build_pilot_report


FIXTURE_RESULTS = [
    {
        "mode": "independent",
        "responses": [],
        "messages": [],
        "errors": [],
        "metrics": {
            "accuracy": 1.0,
            "pooled_answer": "C",
            "majority_answer": "C",
            "majority_share": 1.0,
            "unanimity": True,
            "wrong_consensus": False,
            "flip_rate": 0.0,
            "js_disagreement": 0.0,
            "group_brier": 0.1,
            "speaker_share": {
                "agent-a": 1 / 3,
                "agent-b": 1 / 3,
                "agent-c": 1 / 3,
            },
            "runtime_belief_state": {
                "mean_b": 0.4,
                "order_parameter_r": 0.9,
                "temperature_proxy": 0.1,
                "entropy_proxy": 0.2,
                "disorder_proxy": 0.12,
            },
            "evaluation_belief_state": {
                "mean_b": 0.4,
                "order_parameter_r": 0.9,
                "temperature_proxy": 0.1,
                "entropy_proxy": 0.2,
                "disorder_proxy": 0.12,
            },
        },
    }
]


def test_report_separates_observations_from_research_claims() -> None:
    report = build_pilot_report(FIXTURE_RESULTS)

    assert "## 工程观察" in report
    assert "## MAST候选信号审计" in report
    assert "FM-2.4" in report
    assert "FM-2.5" in report
    assert "FM-2.6" in report
    assert "## 研究结论限制" in report
    assert "不能据此认定" in report
