from __future__ import annotations

import json
from pathlib import Path

from mas_experiment.hiddenbench_closure import build_closure_evidence


ROOT = Path(__file__).resolve().parents[1]


def test_closure_evidence_derives_the_three_formal_single_agent_baselines() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["single_agent_comparison"]["scope"] == {
        "task_ids": [1, 2, 3],
        "repetitions": 10,
        "model": "deepseek-v4-flash",
    }
    assert evidence["single_agent_comparison"]["overall"] == {
        "single_local": "4/30",
        "single_full_profile": "20/30",
        "fixed_60_multi_agent": "17/30",
    }
    assert evidence["single_agent_comparison"]["by_task"] == [
        {"task_id": 1, "single_local": "2/10", "single_full_profile": "10/10", "fixed_60_multi_agent": "10/10"},
        {"task_id": 2, "single_local": "2/10", "single_full_profile": "10/10", "fixed_60_multi_agent": "0/10"},
        {"task_id": 3, "single_local": "0/10", "single_full_profile": "0/10", "fixed_60_multi_agent": "7/10"},
    ]


def test_closure_evidence_has_traceable_representative_causal_cards() -> None:
    evidence = build_closure_evidence(ROOT)
    cards = evidence["causal_cards"]

    assert [card["mechanism"] for card in cards] == [
        "information_not_disclosed",
        "evidence_misinterpreted",
        "evidence_not_used_after_disclosure",
    ]
    assert cards[0]["run_id"] == "0d078a3c85f64262"
    assert cards[0]["study_key"] == {
        "task_id": 2,
        "condition": "fixed-60",
        "repetition": 0,
    }
    assert cards[0]["undisclosed_fact_count"] == 2
    assert "supply truck" in cards[0]["facts"][0]["fact"].casefold()
    assert cards[1]["run_id"] == "e46521e6691a10ca"
    assert cards[1]["study_key"] == {
        "task_id": 2,
        "condition": "fixed-reveal-all",
        "repetition": 1,
    }
    assert "tunnel is clear" in cards[1]["contradictory_final_rationale"].casefold()
    assert cards[2]["run_id"] == "bfba1db7a056ebea"
    assert cards[2]["study_key"] == {
        "task_id": 3,
        "condition": "fixed-60",
        "repetition": 0,
    }
    assert cards[2]["all_atomic_facts_disclosed"] is True
    assert "walking trails are closed" in cards[2]["late_evidence_quote"].casefold()


def test_closure_evidence_is_json_serializable_and_has_explicit_boundaries(tmp_path: Path) -> None:
    evidence = build_closure_evidence(ROOT)
    output = tmp_path / "closure.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["boundaries"]["human_review"] == "pending_real_human_double_blind_review"
    assert loaded["boundaries"]["model_framework_decoupling"] == "pending_gpt41_or_equivalent_api_access"
