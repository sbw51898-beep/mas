from __future__ import annotations

import pytest

from reports.build_hardened_confirmatory_summaries import (
    build_task_details,
    classify_early_stop,
    exact_paired_mcnemar,
    select_disclosure_example,
    summarize_binary_rows,
    wilson_interval,
)


def test_wilson_interval_for_ten_out_of_ten_is_not_zero_width() -> None:
    low, high = wilson_interval(10, 10)

    assert low == pytest.approx(0.7224672, abs=1e-6)
    assert high == pytest.approx(1.0, abs=1e-12)


def test_wilson_interval_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(11, 10)
    with pytest.raises(ValueError, match="trials"):
        wilson_interval(0, 0)


def test_exact_paired_mcnemar_uses_two_sided_binomial_probability() -> None:
    result = exact_paired_mcnemar(
        [False, False, False, False],
        [True, True, True, True],
    )

    assert result == {
        "a_only": 0,
        "b_only": 4,
        "discordant": 4,
        "p_value": 0.125,
    }


def test_exact_paired_mcnemar_rejects_unequal_lengths() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        exact_paired_mcnemar([True], [True, False])


def test_early_unanimity_followed_by_two_two_votes_is_final_tie() -> None:
    classification = classify_early_stop(
        {
            "candidate_round": 2,
            "candidate_answer": "North Hill",
            "final_votes": (
                "North Hill",
                "West City",
                "North Hill",
                "West City",
            ),
        }
    )

    assert classification == "final-tie"


def test_early_stop_distinguishes_same_and_different_majorities() -> None:
    assert classify_early_stop(
        {
            "candidate_round": 2,
            "candidate_answer": "West City",
            "final_votes": ("West City",) * 4,
        }
    ) == "same-majority"
    assert classify_early_stop(
        {
            "candidate_round": 2,
            "candidate_answer": "West City",
            "final_votes": ("East Town",) * 3 + ("West City",),
        }
    ) == "different-majority"
    assert classify_early_stop(
        {
            "candidate_round": None,
            "candidate_answer": None,
            "final_votes": ("West City",) * 4,
        }
    ) == "no-candidate"


def test_binary_summary_includes_numerator_denominator_and_interval() -> None:
    rows = [
        {"run": {"metrics": {"post_majority_correct": value}}}
        for value in (True, True, False, True)
    ]

    result = summarize_binary_rows(rows)

    assert result["successes"] == 3
    assert result["runs"] == 4
    assert result["rate"] == 0.75
    assert result["wilson_95_low"] < 0.75 < result["wilson_95_high"]


def test_disclosure_example_preserves_ai_judgments_and_arithmetic() -> None:
    runs = [
        {
            "key": {"task_id": 1, "condition": "fixed-60", "repetition": 3},
            "run": {"run_id": "run-3"},
        }
    ]
    audits = [
        {
            "study_key": {
                "task_id": 1,
                "condition": "fixed-60",
                "repetition": 3,
            },
            "facts": [{"fact_id": f"f{i}"} for i in range(4)],
            "judgments": [
                {"fact_id": f"f{i}", "disclosed": i < 3}
                for i in range(4)
            ],
            "disclosure_rate": 0.75,
        }
    ]

    result = select_disclosure_example(runs, audits, target_rate=0.75)

    assert result["study_key"] == audits[0]["study_key"]
    assert result["run_id"] == "run-3"
    assert result["disclosed_count"] == 3
    assert result["fact_count"] == 4
    assert result["arithmetic"] == "3 disclosed / 4 total = 75.0%"
    assert result["judgments"] == audits[0]["judgments"]


def test_task_details_explain_why_each_official_short_answer_is_correct() -> None:
    tasks = [
        {
            "id": task_id,
            "name": f"task-{task_id}",
            "description": "Shared decision description.",
            "shared_information": ["Shared fact."],
            "hidden_information": [f"Private {i}." for i in range(4)],
            "correct_answer": answer,
        }
        for task_id, answer in (
            (1, "West City"),
            (2, "North Hill"),
            (3, "East Town"),
        )
    ]

    details = build_task_details(tasks)

    assert [item["task_id"] for item in details] == [1, 2, 3]
    assert all(len(item["private_facts"]) == 4 for item in details)
    assert all(item["evidence_chain"] for item in details)
