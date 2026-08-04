from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal


EarlyStopClass = Literal[
    "same-majority",
    "final-tie",
    "different-majority",
    "no-candidate",
]


def wilson_interval(
    successes: int,
    trials: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    proportion = successes / trials
    z_squared = z * z
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / trials
            + z_squared / (4 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def exact_paired_mcnemar(
    a: Sequence[bool],
    b: Sequence[bool],
) -> dict[str, int | float]:
    if len(a) != len(b):
        raise ValueError("paired vectors must have equal lengths")
    a_only = sum(bool(left) and not bool(right) for left, right in zip(a, b))
    b_only = sum(bool(right) and not bool(left) for left, right in zip(a, b))
    discordant = a_only + b_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = min(a_only, b_only)
        probability = sum(
            math.comb(discordant, index)
            for index in range(tail + 1)
        ) / (2**discordant)
        p_value = min(1.0, 2 * probability)
    return {
        "a_only": a_only,
        "b_only": b_only,
        "discordant": discordant,
        "p_value": p_value,
    }


def _strict_majority(votes: Sequence[str]) -> str | None:
    counts = Counter(votes)
    if not counts:
        return None
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def classify_early_stop(row: Mapping[str, Any]) -> EarlyStopClass:
    if row.get("candidate_round") is None or row.get("candidate_answer") is None:
        return "no-candidate"
    raw_votes = row.get("final_votes", ())
    if isinstance(raw_votes, str):
        votes = tuple(item for item in raw_votes.split("|") if item)
    else:
        votes = tuple(str(item) for item in raw_votes)
    final_majority = _strict_majority(votes)
    if final_majority is None:
        return "final-tie"
    if final_majority == row.get("candidate_answer"):
        return "same-majority"
    return "different-majority"


def summarize_binary_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int | float]:
    runs = len(rows)
    if not runs:
        raise ValueError("binary summary requires at least one row")
    successes = sum(
        bool(row["run"]["metrics"]["post_majority_correct"])
        for row in rows
    )
    low, high = wilson_interval(successes, runs)
    return {
        "successes": successes,
        "runs": runs,
        "rate": successes / runs,
        "wilson_95_low": low,
        "wilson_95_high": high,
    }


def _key_tuple(value: Mapping[str, Any]) -> tuple[int, str, int]:
    return (
        int(value["task_id"]),
        str(value["condition"]),
        int(value["repetition"]),
    )


def select_disclosure_example(
    runs: Sequence[Mapping[str, Any]],
    audits: Sequence[Mapping[str, Any]],
    *,
    target_rate: float,
) -> dict[str, Any]:
    runs_by_key = {_key_tuple(row["key"]): row for row in runs}
    for audit in audits:
        if abs(float(audit["disclosure_rate"]) - target_rate) > 1e-12:
            continue
        key = _key_tuple(audit["study_key"])
        run = runs_by_key.get(key)
        if run is None:
            continue
        judgments = list(audit["judgments"])
        disclosed = sum(bool(item["disclosed"]) for item in judgments)
        facts = list(audit["facts"])
        percentage = disclosed / len(facts) * 100
        return {
            "study_key": dict(audit["study_key"]),
            "run_id": run["run"]["run_id"],
            "facts": facts,
            "judgments": judgments,
            "disclosed_count": disclosed,
            "fact_count": len(facts),
            "disclosure_rate": float(audit["disclosure_rate"]),
            "arithmetic": (
                f"{disclosed} disclosed / {len(facts)} total = "
                f"{percentage:.1f}%"
            ),
        }
    raise ValueError(f"no disclosure example found at rate {target_rate}")


_EVIDENCE_CHAINS = {
    1: (
        "East Town's tunnel is blocked by the stuck supply truck and fire; "
        "North Hill's driveway and trails are both blocked; the West City "
        "bridge remains passable, leaving West City as the viable route."
    ),
    2: (
        "The imminent dam release makes the West City bridge unsafe; the "
        "East Town tunnel is blocked by the supply truck and fire; North "
        "Hill's driveway remains open, leaving North Hill as the viable route."
    ),
    3: (
        "The dam release makes the West City bridge unsafe and both North "
        "Hill access routes are blocked; no fact blocks the East Town tunnel, "
        "leaving East Town as the viable route."
    ),
}


def build_task_details(
    tasks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected = {int(task["id"]): task for task in tasks}
    details: list[dict[str, Any]] = []
    for task_id in (1, 2, 3):
        task = selected.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id} missing from benchmark")
        private_facts = list(task["hidden_information"])
        if len(private_facts) != 4:
            raise ValueError(f"task {task_id} must have four private facts")
        details.append(
            {
                "task_id": task_id,
                "name": task["name"],
                "description": task["description"],
                "shared_information": list(task["shared_information"]),
                "private_facts": private_facts,
                "correct_answer": task["correct_answer"],
                "evidence_chain": _EVIDENCE_CHAINS[task_id],
            }
        )
    return details


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _condition_statistics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int | float]]:
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = row["key"]
        grouped[(str(key["condition"]), int(key["task_id"]))].append(row)
    return {
        f"{condition}:ID{task_id}": summarize_binary_rows(group)
        for (condition, task_id), group in sorted(grouped.items())
    }


def _paired_tests(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int | float]]:
    by_key = {
        _key_tuple(row["key"]): bool(
            row["run"]["metrics"]["post_majority_correct"]
        )
        for row in rows
    }
    contrasts = (
        ("fixed-60", "dynamic-60"),
        ("fixed-reveal-all", "dynamic-reveal-all"),
        ("fixed-12", "structured-12"),
    )
    results: dict[str, dict[str, int | float]] = {}
    for left, right in contrasts:
        left_values: list[bool] = []
        right_values: list[bool] = []
        for task_id in (1, 2, 3):
            for repetition in range(10):
                left_values.append(by_key[(task_id, left, repetition)])
                right_values.append(by_key[(task_id, right, repetition)])
        test = exact_paired_mcnemar(left_values, right_values)
        test.update(
            {
                "left_successes": sum(left_values),
                "right_successes": sum(right_values),
                "pairs": len(left_values),
            }
        )
        results[f"{left}_vs_{right}"] = test
    return results


def _early_stop_analysis(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fixed = [row for row in rows if row["key"]["condition"] == "fixed-60"]
    classes = Counter(
        classify_early_stop(
            {
                "candidate_round": row["early_stop"]["candidate_round"],
                "candidate_answer": row["early_stop"]["candidate_answer"],
                "final_votes": row["early_stop"]["final_votes"],
            }
        )
        for row in fixed
    )
    candidate_correct = sum(
        bool(row["early_stop"]["candidate_correct"]) for row in fixed
    )
    final_correct = sum(
        bool(row["early_stop"]["final_correct"]) for row in fixed
    )
    exceptional = [
        {
            "study_key": row["key"],
            "run_id": row["run"]["run_id"],
            "candidate_round": row["early_stop"]["candidate_round"],
            "candidate_answer": row["early_stop"]["candidate_answer"],
            "final_votes": row["early_stop"]["final_votes"],
            "classification": classify_early_stop(
                {
                    "candidate_round": row["early_stop"]["candidate_round"],
                    "candidate_answer": row["early_stop"]["candidate_answer"],
                    "final_votes": row["early_stop"]["final_votes"],
                }
            ),
            "candidate_correct": row["early_stop"]["candidate_correct"],
            "final_correct": row["early_stop"]["final_correct"],
        }
        for row in fixed
        if classify_early_stop(
            {
                "candidate_round": row["early_stop"]["candidate_round"],
                "candidate_answer": row["early_stop"]["candidate_answer"],
                "final_votes": row["early_stop"]["final_votes"],
            }
        )
        != "same-majority"
    ]
    return {
        "runs": len(fixed),
        "classifications": dict(sorted(classes.items())),
        "candidate_correct": candidate_correct,
        "final_correct": final_correct,
        "exceptional_cases": exceptional,
    }


def _mast_cases(
    runs: Sequence[Mapping[str, Any]],
    audits: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    runs_by_key = {_key_tuple(row["key"]): row for row in runs}
    fm24_audit = next(
        audit
        for audit in audits
        if audit["study_key"]["condition"] == "fixed-60"
        and float(audit["disclosure_rate"]) < 1.0
    )
    fm24_run = runs_by_key[_key_tuple(fm24_audit["study_key"])]
    fm24_undisclosed = [
        fact["text"]
        for fact, judgment in zip(
            fm24_audit["facts"], fm24_audit["judgments"], strict=True
        )
        if not judgment["disclosed"]
    ]
    fm25_run = next(
        row
        for row in runs
        if row["key"] == {
            "task_id": 2,
            "condition": "fixed-reveal-all",
            "repetition": 1,
        }
    )
    fm25_audit = next(
        audit
        for audit in audits
        if _key_tuple(audit["study_key"]) == _key_tuple(fm25_run["key"])
    )
    return [
        {
            "mast_mode": "FM-2.4",
            "boundary": "confirmed",
            "study_key": fm24_audit["study_key"],
            "run_id": fm24_run["run"]["run_id"],
            "disclosure_rate": fm24_audit["disclosure_rate"],
            "evidence": fm24_undisclosed,
            "final_votes": [
                vote["vote"] for vote in fm24_run["run"]["hidden_post_votes"]
            ],
            "interpretation": "At least one owner fact never appeared in an owner-authored public message.",
        },
        {
            "mast_mode": "FM-2.5",
            "boundary": "candidate-needs-human-causal-coding",
            "study_key": fm25_run["key"],
            "run_id": fm25_run["run"]["run_id"],
            "disclosure_rate": fm25_audit["disclosure_rate"],
            "evidence": [
                message["message_id"]
                for message in fm25_run["run"]["discussion_messages"][-4:]
            ],
            "final_votes": [
                vote["vote"] for vote in fm25_run["run"]["hidden_post_votes"]
            ],
            "interpretation": "All facts were public, yet every final rationale treated the East Town tunnel as clear and the group unanimously chose the wrong answer.",
        },
        {
            "mast_mode": "FM-2.6",
            "boundary": "not-confirmed",
            "study_key": None,
            "run_id": None,
            "disclosure_rate": None,
            "evidence": [],
            "final_votes": [],
            "interpretation": "No rationale-vote inconsistency was directly verified; lexical alternative mentions were negated comparisons, not conflicting actions.",
        },
    ]


def write_hardened_summaries(root: Path) -> dict[str, Path]:
    artifacts = root / "artifacts"
    data_dir = root / "reports" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    confirmatory_path = artifacts / "hiddenbench-confirmatory-20260804.jsonl"
    audits_path = artifacts / "hiddenbench-confirmatory-20260804.audits.jsonl"
    supplement_path = (
        artifacts / "hiddenbench-official-reveal-supplement-20260804.jsonl"
    )
    official_path = data_dir / "hiddenbench-official-gpt41-short-summary.json"
    benchmark_path = root / "data" / "hiddenbench" / "benchmark.json"
    confirmatory = _jsonl(confirmatory_path)
    audits = _jsonl(audits_path)
    supplement = _jsonl(supplement_path)
    official = json.loads(official_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    mast = _mast_cases(confirmatory, audits)
    analysis = {
        "schema_version": "hiddenbench-hardened-analysis-v1",
        "scope": {
            "confirmatory_runs": len(confirmatory),
            "atomic_audits": len(audits),
            "official_reveal_supplement_runs": len(supplement),
            "task_ids": [1, 2, 3],
        },
        "generation_seed_boundary": (
            "Pair seeds control private-fact assignment only; "
            "MAFPromptProvider does not transmit a generation seed."
        ),
        "condition_statistics": _condition_statistics(
            [*confirmatory, *supplement]
        ),
        "paired_exact_tests": _paired_tests(confirmatory),
        "early_stop": _early_stop_analysis(confirmatory),
        "disclosure_example": select_disclosure_example(
            confirmatory,
            audits,
            target_rate=0.75,
        ),
        "task_details": build_task_details(benchmark),
        "mast_cases": mast,
        "official_gpt41": official,
        "source_sha256": {
            confirmatory_path.name: _sha256(confirmatory_path),
            audits_path.name: _sha256(audits_path),
            supplement_path.name: _sha256(supplement_path),
            official_path.name: _sha256(official_path),
            benchmark_path.name: _sha256(benchmark_path),
        },
    }
    analysis_path = data_dir / "hiddenbench-hardened-analysis-20260804.json"
    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    statistics_path = (
        data_dir / "hiddenbench-hardened-statistics-20260804.csv"
    )
    with statistics_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "condition_task",
                "successes",
                "runs",
                "rate",
                "wilson_95_low",
                "wilson_95_high",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for condition_task, values in analysis["condition_statistics"].items():
            writer.writerow({"condition_task": condition_task, **values})
    mast_path = data_dir / "hiddenbench-mast-cases-20260804.csv"
    with mast_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "mast_mode",
                "boundary",
                "study_key",
                "run_id",
                "disclosure_rate",
                "evidence",
                "final_votes",
                "interpretation",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in mast:
            writer.writerow(
                {
                    **row,
                    "study_key": json.dumps(
                        row["study_key"], ensure_ascii=False
                    ),
                    "evidence": json.dumps(row["evidence"], ensure_ascii=False),
                    "final_votes": json.dumps(
                        row["final_votes"], ensure_ascii=False
                    ),
                }
            )
    supplement_summary = {
        "schema_version": "hiddenbench-official-reveal-supplement-summary-v1",
        "runs": len(supplement),
        "model": "deepseek-v4-flash",
        "protocol": "official-compatible global Reveal-All in round one",
        "generation_seed_controlled": False,
        "by_task": {
            str(task_id): summarize_binary_rows(
                [row for row in supplement if row["key"]["task_id"] == task_id]
            )
            for task_id in (1, 2, 3)
        },
        "api_requests": sum(
            int(row["run"]["provider_metadata"].get("api_requests", 0) or 0)
            for row in supplement
        ),
        "source_sha256": _sha256(supplement_path),
    }
    supplement_summary_path = (
        data_dir / "hiddenbench-official-reveal-supplement-summary.json"
    )
    supplement_summary_path.write_text(
        json.dumps(supplement_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "analysis": analysis_path,
        "statistics": statistics_path,
        "mast": mast_path,
        "supplement": supplement_summary_path,
    }


def main() -> None:
    root = Path(__file__).parents[1]
    paths = write_hardened_summaries(root)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
