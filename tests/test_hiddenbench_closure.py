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


def test_closure_evidence_derives_ordinary_60_disclosure_rates() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["ordinary_60_disclosure"] == {
        "scope": {
            "conditions": ["fixed-60", "dynamic-60"],
            "task_ids": [1, 2, 3],
            "repetitions": 10,
            "atomic_facts_per_run": 4,
            "audit_type": "model-assisted atomic disclosure audit",
        },
        "by_condition": [
            {
                "condition": "fixed-60",
                "by_task": [
                    {"task_id": 1, "disclosed": 30, "total": 40, "rate": 0.75},
                    {"task_id": 2, "disclosed": 28, "total": 40, "rate": 0.70},
                    {"task_id": 3, "disclosed": 32, "total": 40, "rate": 0.80},
                ],
                "overall": {"disclosed": 90, "total": 120, "rate": 0.75},
            },
            {
                "condition": "dynamic-60",
                "by_task": [
                    {"task_id": 1, "disclosed": 27, "total": 40, "rate": 0.675},
                    {"task_id": 2, "disclosed": 24, "total": 40, "rate": 0.60},
                    {"task_id": 3, "disclosed": 36, "total": 40, "rate": 0.90},
                ],
                "overall": {"disclosed": 87, "total": 120, "rate": 0.725},
            },
        ],
    }


def test_closure_evidence_records_ai_rate_crosscheck_and_selector_formula() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["ai_disclosure_crosscheck"]["by_condition"] == [
        {
            "condition": "fixed-60",
            "by_task": [
                {"task_id": 1, "ai_reported_rate": 0.75, "program_recomputed_rate": 0.75, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
                {"task_id": 2, "ai_reported_rate": 0.7, "program_recomputed_rate": 0.7, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
                {"task_id": 3, "ai_reported_rate": 0.8, "program_recomputed_rate": 0.8, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
            ],
            "overall": {"ai_reported_rate": 0.75, "program_recomputed_rate": 0.75, "rate_difference": 0.0, "audit_runs": 30, "mismatched_runs": 0},
        },
        {
            "condition": "dynamic-60",
            "by_task": [
                {"task_id": 1, "ai_reported_rate": 0.675, "program_recomputed_rate": 0.675, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
                {"task_id": 2, "ai_reported_rate": 0.6, "program_recomputed_rate": 0.6, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
                {"task_id": 3, "ai_reported_rate": 0.9, "program_recomputed_rate": 0.9, "rate_difference": 0.0, "audit_runs": 10, "mismatched_runs": 0},
            ],
            "overall": {"ai_reported_rate": 0.725, "program_recomputed_rate": 0.725, "rate_difference": 0.0, "audit_runs": 30, "mismatched_runs": 0},
        },
    ]
    assert evidence["correctness_stratified_disclosure"]["by_condition"] == [
        {
            "condition": "fixed-60",
            "correct_runs": 17,
            "correct_mean_disclosure_rate": 0.7647058823529411,
            "incorrect_runs": 13,
            "incorrect_mean_disclosure_rate": 0.7307692307692307,
        },
        {
            "condition": "dynamic-60",
            "correct_runs": 21,
            "correct_mean_disclosure_rate": 0.7619047619047619,
            "incorrect_runs": 9,
            "incorrect_mean_disclosure_rate": 0.6388888888888888,
        },
    ]
    assert evidence["selector_formula"]["score_formula"] == (
        "S_i = 0.30 d_i + 0.30 u_i + 0.15 r_i + 0.15 q_i + 0.10 w_i"
    )


def test_closure_evidence_derives_task_level_repeat_stability() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["repeat_stability"]["scope"] == {
        "conditions": ["fixed-60", "dynamic-60"],
        "task_ids": [1, 2, 3],
        "repetitions_per_task": 10,
        "vote_field": "hidden_post_votes",
        "outcome_encoding": "C=majority correct, I=majority incorrect",
    }
    assert [
        {
            "task_id": item["task_id"],
            "correct_runs": item["correct_runs"],
            "incorrect_runs": item["incorrect_runs"],
            "total_runs": item["total_runs"],
        }
        for item in evidence["repeat_stability"]["by_condition"][0]["by_task"]
    ] == [
        {"task_id": 1, "correct_runs": 10, "incorrect_runs": 0, "total_runs": 10},
        {"task_id": 2, "correct_runs": 0, "incorrect_runs": 10, "total_runs": 10},
        {"task_id": 3, "correct_runs": 7, "incorrect_runs": 3, "total_runs": 10},
    ]
    assert [
        {
            "task_id": item["task_id"],
            "correct_runs": item["correct_runs"],
            "incorrect_runs": item["incorrect_runs"],
            "total_runs": item["total_runs"],
        }
        for item in evidence["repeat_stability"]["by_condition"][1]["by_task"]
    ] == [
        {"task_id": 1, "correct_runs": 10, "incorrect_runs": 0, "total_runs": 10},
        {"task_id": 2, "correct_runs": 2, "incorrect_runs": 8, "total_runs": 10},
        {"task_id": 3, "correct_runs": 9, "incorrect_runs": 1, "total_runs": 10},
    ]


def test_closure_evidence_exposes_disclosure_timing_and_pairing() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["disclosure_timing"]["by_condition"] == [
        {
            "condition": "fixed-60",
            "disclosed_facts": 90,
            "first_round_count": 85,
            "later_round_count": 5,
            "mean_first_disclosure_round": 1.2,
            "median_first_disclosure_round": 1.0,
            "first_round_counts": [
                {"round": 1, "count": 85},
                {"round": 2, "count": 3},
                {"round": 3, "count": 1},
                {"round": 14, "count": 1},
            ],
        },
        {
            "condition": "dynamic-60",
            "disclosed_facts": 87,
            "first_round_count": 72,
            "later_round_count": 15,
            "mean_first_disclosure_round": 1.7701149425287357,
            "median_first_disclosure_round": 1,
            "first_round_counts": [
                {"round": 1, "count": 72},
                {"round": 2, "count": 3},
                {"round": 3, "count": 2},
                {"round": 4, "count": 1},
                {"round": 5, "count": 3},
                {"round": 6, "count": 1},
                {"round": 7, "count": 2},
                {"round": 9, "count": 2},
                {"round": 13, "count": 1},
            ],
        },
    ]
    pair = evidence["paired_comparisons"]["result"][0]
    assert pair == {
        "condition_a": "fixed-60",
        "condition_b": "dynamic-60",
        "pairs": 30,
        "same_pair_seed": 30,
        "same_assignment_fingerprint": 30,
        "a_only": 0,
        "b_only": 4,
        "discordant": 4,
        "a_correct": 17,
        "b_correct": 21,
        "test": "two-sided exact McNemar (binomial test on discordant pairs)",
    }


def test_closure_evidence_separates_public_speech_budget_from_total_requests() -> None:
    evidence = build_closure_evidence(ROOT)

    assert evidence["public_speech_budget"] == {
        "scope": {
            "task_ids": [1, 2, 3],
            "repetitions": 10,
            "agents": 4,
            "public_messages_per_run": 60,
            "public_messages_per_agent": 15,
        },
        "by_condition": [
            {
                "condition": "fixed-60",
                "runs": 30,
                "logical_response_slots_per_run": 132,
                "shadow_vote_calls_per_run": 60,
                "selector_llm_calls_per_run": 0,
                "api_request_distribution": {132: 29, 133: 1},
            },
            {
                "condition": "dynamic-60",
                "runs": 30,
                "logical_response_slots_per_run": 72,
                "shadow_vote_calls_per_run": 0,
                "selector_llm_calls_per_run": 0,
                "api_request_distribution": {72: 30},
            },
        ],
    }


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
    assert "固定检索规则" in cards[0]["selection_rule"]
    assert "固定检索规则" in cards[1]["selection_rule"]
    assert "固定检索规则" in cards[2]["selection_rule"]


def test_closure_evidence_has_filled_prompt_example() -> None:
    evidence = build_closure_evidence(ROOT)
    example = evidence["prompt_example"]

    assert example["study_key"] == {
        "task_id": 2,
        "condition": "fixed-60",
        "repetition": 0,
    }
    assert example["public_message_count"] == 60
    assert len(example["private_facts"]) == 4
    assert len(example["public_messages_excerpt"]) == 4
    assert len(example["judgments"]) == 4
    assert example["judgments"][0]["disclosed"] is True
    assert example["judgments"][1]["disclosed"] is False
    assert example["judgments"][1]["evidence_message_ids"] == []
    assert "supply truck" in example["private_facts"][1]["claim"].casefold()
    assert example["discussion_turn"]["agent_id"] == "agent-b"
    assert example["discussion_turn"]["round_index"] == 1
    assert "You are the first to speak." not in example["discussion_turn"]["user_prompt"]
    assert "It’s your turn to speak." in example["discussion_turn"]["user_prompt"]
    assert "bridge over the river may be risky" in example["discussion_turn"]["actual_output"]


def test_closure_evidence_is_json_serializable_and_has_explicit_boundaries(tmp_path: Path) -> None:
    evidence = build_closure_evidence(ROOT)
    output = tmp_path / "closure.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["boundaries"]["human_review"] == "pending_real_human_double_blind_review"
    assert loaded["boundaries"]["model_framework_decoupling"] == "pending_gpt41_or_equivalent_api_access"
