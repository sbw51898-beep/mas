from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from io import StringIO
from pathlib import Path
from typing import Any


HISTORICAL_FILES = (
    "hiddenbench-stability-20260729.jsonl",
    "hiddenbench-governance-20260802.jsonl",
    "hiddenbench-structured-20260802.jsonl",
    "hiddenbench-contrast-20260803.jsonl",
    "hiddenbench-earlystop-20260803.jsonl",
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _majority(votes: list[str]) -> str | None:
    ranked = Counter(votes).most_common()
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def _run_api_requests(row: dict[str, Any]) -> int:
    run = row["run"]
    items = [
        *run["hidden_pre_votes"],
        *run["discussion_messages"],
        *run["hidden_post_votes"],
        *run["full_profile_votes"],
    ]
    items.extend(
        vote
        for checkpoint in row["shadow_checkpoints"]
        for vote in checkpoint["votes"]
    )
    return sum(
        int(item.get("provider_metadata", {}).get("api_requests", 0) or 0)
        for item in items
    )


def build_confirmatory_summary(
    *,
    runs_path: Path,
    audits_path: Path,
    gate_path: Path,
) -> dict[str, Any]:
    rows = _jsonl(runs_path)
    audits = _jsonl(audits_path)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_by_key = {
        (
            audit["study_key"]["condition"],
            audit["study_key"]["task_id"],
            audit["study_key"]["repetition"],
        ): audit
        for audit in audits
    }
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    early_cases: list[dict[str, Any]] = []
    for row in rows:
        key = row["key"]
        run = row["run"]
        votes = [item["vote"] for item in run["hidden_post_votes"]]
        correct = run["task"]["correct_answer"]
        audit = audit_by_key[
            (key["condition"], key["task_id"], key["repetition"])
        ]
        groups[(key["condition"], key["task_id"])].append(
            {
                "vote_accuracy": sum(vote == correct for vote in votes)
                / len(votes),
                "majority_correct": _majority(votes) == correct,
                "unanimous_correct": len(set(votes)) == 1
                and votes[0] == correct,
                "false_consensus": len(set(votes)) == 1
                and votes[0] != correct,
                "disclosure_rate": audit["disclosure_rate"],
            }
        )
        if key["condition"] == "fixed-60":
            early_cases.append(
                {
                    "task_id": key["task_id"],
                    "repetition": key["repetition"],
                    **row["early_stop"],
                }
            )

    by_condition_task: dict[str, Any] = {}
    for (condition, task_id), values in sorted(groups.items()):
        count = len(values)
        by_condition_task[f"{condition}:ID{task_id}"] = {
            "runs": count,
            "vote_accuracy": sum(v["vote_accuracy"] for v in values) / count,
            "majority_accuracy": sum(v["majority_correct"] for v in values)
            / count,
            "unanimous_correct_rate": sum(
                v["unanimous_correct"] for v in values
            )
            / count,
            "false_consensus_rate": sum(
                v["false_consensus"] for v in values
            )
            / count,
            "atomic_disclosure_rate": sum(
                v["disclosure_rate"] for v in values
            )
            / count,
        }
    candidates = [
        item for item in early_cases if item["candidate_round"] is not None
    ]
    return {
        "schema_version": "hiddenbench-confirmatory-summary-v1",
        "publication": {
            "repository": "https://github.com/sbw51898-beep/mas",
            "release_page": "https://github.com/sbw51898-beep/mas/releases/tag/hiddenbench-confirmatory-20260804",
            "raw_asset": "https://github.com/sbw51898-beep/mas/releases/download/hiddenbench-confirmatory-20260804/hiddenbench-confirmatory-20260804-raw.zip",
            "raw_asset_sha256": "release/hiddenbench-confirmatory-20260804-raw.sha256",
        },
        "run_count": len(rows),
        "audit_count": len(audits),
        "condition_count": len({row["key"]["condition"] for row in rows}),
        "task_ids": sorted({row["key"]["task_id"] for row in rows}),
        "run_api_requests": sum(_run_api_requests(row) for row in rows),
        "audit_api_requests": sum(
            int(audit["provider_metadata"].get("api_requests", 0) or 0)
            for audit in audits
        ),
        "run_commits": sorted({row["run_commit"] for row in rows}),
        "frozen_code_commits": sorted(
            {row["frozen_code_commit"] for row in rows}
        ),
        "audit_code_commits": sorted(
            {
                audit["provider_metadata"].get("audit_code_commit")
                for audit in audits
            }
        ),
        "gate_passed": gate["passed"],
        "gate_checks": gate["checks"],
        "early_stop": {
            "candidate_runs": len(candidates),
            "exact_match_true": sum(
                item["exact_match"] is True for item in candidates
            ),
            "exact_match_false": sum(
                item["exact_match"] is False for item in candidates
            ),
            "mean_saved_messages_candidates": sum(
                item["saved_public_messages"] for item in candidates
            )
            / len(candidates),
        },
        "by_condition_task": by_condition_task,
        "source_files": {
            runs_path.name: _sha256(runs_path),
            audits_path.name: _sha256(audits_path),
            gate_path.name: _sha256(gate_path),
        },
    }


def build_historical_summary(artifacts: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources = {}
    for name in HISTORICAL_FILES:
        path = artifacts / name
        rows.extend(_jsonl(path))
        sources[name] = _sha256(path)
    correct_by_condition: dict[str, int] = defaultdict(int)
    correct_by_task: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for row in rows:
        condition = row["key"]["condition"]
        task_id = str(row["key"]["task_id"])
        run = row["run"]
        votes = [vote["vote"] for vote in run["hidden_post_votes"]]
        correct = _majority(votes) == run["task"]["correct_answer"]
        correct_by_condition[condition] += int(correct)
        correct_by_task[condition][task_id] += int(correct)
    multi_agent = [
        value
        for condition, value in correct_by_condition.items()
        if not condition.startswith("single")
    ]
    return {
        "total_conditions": len(correct_by_condition),
        "total_runs": len(rows),
        "correct_runs_by_condition": dict(sorted(correct_by_condition.items())),
        "multi_agent_correct_range": [min(multi_agent), max(multi_agent)],
        "earlystop_by_task": {
            condition: dict(sorted(correct_by_task[condition].items()))
            for condition in ("fixed-4", "fixed-8", "fixed")
        },
        "source_files": sources,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-8", newline="\n")


def write_confirmatory_summaries(
    *,
    root: Path,
    output_dir: Path,
) -> dict[str, Path]:
    artifacts = root / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_path = artifacts / "hiddenbench-confirmatory-20260804.jsonl"
    audits_path = artifacts / "hiddenbench-confirmatory-20260804.audits.jsonl"
    gate_path = artifacts / "hiddenbench-confirmatory-20260804.gate.json"
    rows = _jsonl(runs_path)
    audits = _jsonl(audits_path)
    summary = build_confirmatory_summary(
        runs_path=runs_path,
        audits_path=audits_path,
        gate_path=gate_path,
    )
    summary["historical_appendix"] = build_historical_summary(artifacts)
    official = json.loads(
        (
            root
            / "data"
            / "hiddenbench"
            / "official_short_gpt41_summary_20260804.json"
        ).read_text(encoding="utf-8")
    )
    paths = {
        "confirmatory": output_dir / "hiddenbench-confirmatory-summary.json",
        "official": output_dir / "hiddenbench-official-gpt41-short-summary.json",
        "earlystop": output_dir
        / "hiddenbench-confirmatory-earlystop-cases.csv",
        "disclosure": output_dir
        / "hiddenbench-confirmatory-atomic-disclosure.csv",
    }
    _write_json(paths["confirmatory"], summary)
    _write_json(paths["official"], official)
    early_rows = []
    for row in rows:
        if row["key"]["condition"] != "fixed-60":
            continue
        item = row["early_stop"]
        early_rows.append(
            {
                "task_id": row["key"]["task_id"],
                "repetition": row["key"]["repetition"],
                "candidate_round": item["candidate_round"],
                "candidate_answer": item["candidate_answer"],
                "final_votes": "|".join(item["final_votes"]),
                "exact_match": str(item["exact_match"]).lower(),
                "candidate_correct": str(item["candidate_correct"]).lower(),
                "final_correct": str(item["final_correct"]).lower(),
                "saved_public_messages": item["saved_public_messages"],
            }
        )
    _write_csv(paths["earlystop"], early_rows, list(early_rows[0]))
    disclosure_rows = [
        {
            "task_id": audit["study_key"]["task_id"],
            "condition": audit["study_key"]["condition"],
            "repetition": audit["study_key"]["repetition"],
            "atomic_fact_count": len(audit["facts"]),
            "disclosed_fact_count": sum(
                item["disclosed"] for item in audit["judgments"]
            ),
            "disclosure_rate": audit["disclosure_rate"],
            "local_evidence_reanchors": audit["provider_metadata"].get(
                "local_evidence_reanchors", 0
            ),
            "audit_code_commit": audit["provider_metadata"].get(
                "audit_code_commit"
            ),
        }
        for audit in audits
    ]
    _write_csv(
        paths["disclosure"],
        disclosure_rows,
        list(disclosure_rows[0]),
    )
    return paths


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = write_confirmatory_summaries(
        root=root,
        output_dir=root / "reports" / "data",
    )
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
