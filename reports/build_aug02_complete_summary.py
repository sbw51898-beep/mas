from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


RUN_SOURCES = {
    "governance_20260802": "artifacts/hiddenbench-governance-20260802.jsonl",
    "structured_20260802": "artifacts/hiddenbench-structured-20260802.jsonl",
    "contrast_20260803": "artifacts/hiddenbench-contrast-20260803.jsonl",
    "earlystop_20260803": "artifacts/hiddenbench-earlystop-20260803.jsonl",
    "confirmatory_20260804": "artifacts/hiddenbench-confirmatory-20260804.jsonl",
    "official_global_reveal_20260804": (
        "artifacts/hiddenbench-official-reveal-supplement-20260804.jsonl"
    ),
}
EXPECTED_RUN_COUNTS = {
    "governance_20260802": 80,
    "structured_20260802": 40,
    "contrast_20260803": 120,
    "earlystop_20260803": 80,
    "confirmatory_20260804": 210,
    "official_global_reveal_20260804": 30,
}
AUDIT_SOURCES = {
    "governance_20260802": (
        "artifacts/hiddenbench-governance-20260802.ai-disclosure.jsonl"
    ),
    "structured_20260802": (
        "artifacts/hiddenbench-structured-20260802.ai-disclosure.jsonl"
    ),
    "contrast_20260803": (
        "artifacts/hiddenbench-contrast-20260803.ai-disclosure.jsonl"
    ),
    "earlystop_20260803": (
        "artifacts/hiddenbench-earlystop-20260803.ai-disclosure.jsonl"
    ),
    "confirmatory_20260804": (
        "artifacts/hiddenbench-confirmatory-20260804.audits.jsonl"
    ),
}
EXPECTED_AUDIT_COUNTS = {
    "governance_20260802": 80,
    "structured_20260802": 40,
    "contrast_20260803": 40,
    "earlystop_20260803": 80,
    "confirmatory_20260804": 210,
}
GATE_SOURCES = {
    "governance_20260802": "artifacts/hiddenbench-governance-20260802.gate.json",
    "structured_20260802": "artifacts/hiddenbench-structured-20260802.gate.json",
    "contrast_20260803": "artifacts/hiddenbench-contrast-20260803.gate.json",
    "earlystop_20260803": "artifacts/hiddenbench-earlystop-20260803.gate.json",
    "confirmatory_20260804": "artifacts/hiddenbench-confirmatory-20260804.gate.json",
    "official_global_reveal_20260804": (
        "artifacts/hiddenbench-official-reveal-supplement-20260804.gate.json"
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _jsonl_stats(path: Path, *, run_file: bool) -> tuple[int, int]:
    rows = 0
    api_requests = 0
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} is not an object")
            rows += 1
            metadata = (
                row["run"]["provider_metadata"]
                if run_file
                else row["provider_metadata"]
            )
            api_requests += int(metadata.get("api_requests", 0))
    return rows, api_requests


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _governance_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for raw in _load_csv(
        root / "artifacts/hiddenbench-governance-20260802.summary.csv"
    ):
        rows.append(
            {
                "task_id": int(raw["task_id"]),
                "condition": raw["condition"],
                "runs": int(raw["repetitions"]),
                "majority_correct": int(raw["post_majority_correct_count"]),
                "wrong_consensus": int(raw["wrong_consensus_count"]),
                "ai_disclosure_rate": float(raw["ai_disclosure_mean"]),
                "rule_disclosure_rate": float(raw["rule_disclosure_mean"]),
                "ai_rule_agreement": float(raw["ai_rule_agreement"]),
            }
        )
    return rows


def _structured_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for raw in _load_csv(
        root / "artifacts/hiddenbench-structured-20260802.summary.csv"
    ):
        rows.append(
            {
                "task_id": int(raw["task_id"]),
                "condition": raw["condition"],
                "runs": int(raw["repetitions"]),
                "majority_correct": int(raw["post_majority_correct_count"]),
                "wrong_consensus": int(raw["wrong_consensus_count"]),
                "ai_disclosure_rate": float(raw["ai_disclosure_mean"]),
            }
        )
    return rows


def build_complete_summary(root: Path) -> dict[str, Any]:
    root = root.resolve()
    stage_counts: dict[str, int] = {}
    stage_api_requests: dict[str, int] = {}
    audit_counts: dict[str, int] = {}
    audit_api_requests: dict[str, int] = {}
    source_sha256: dict[str, str] = {}

    for stage, relative in RUN_SOURCES.items():
        path = root / relative
        count, requests = _jsonl_stats(path, run_file=True)
        if count != EXPECTED_RUN_COUNTS[stage]:
            raise ValueError(
                f"{stage} run count mismatch: expected "
                f"{EXPECTED_RUN_COUNTS[stage]}, got {count}"
            )
        stage_counts[stage] = count
        stage_api_requests[stage] = requests
        source_sha256[path.name] = _sha256(path)

    for stage, relative in AUDIT_SOURCES.items():
        path = root / relative
        count, requests = _jsonl_stats(path, run_file=False)
        if count != EXPECTED_AUDIT_COUNTS[stage]:
            raise ValueError(
                f"{stage} audit count mismatch: expected "
                f"{EXPECTED_AUDIT_COUNTS[stage]}, got {count}"
            )
        audit_counts[stage] = count
        audit_api_requests[stage] = requests
        source_sha256[path.name] = _sha256(path)

    gate_checks: dict[str, dict[str, bool]] = {}
    for stage, relative in GATE_SOURCES.items():
        path = root / relative
        gate = _load_json(path)
        checks = {str(key): bool(value) for key, value in gate["checks"].items()}
        if not gate.get("passed") or not all(checks.values()):
            raise ValueError(f"formal gate failed: {stage}")
        gate_checks[stage] = checks
        source_sha256[path.name] = _sha256(path)

    confirmatory = _load_json(
        root / "reports/data/hiddenbench-confirmatory-summary.json"
    )
    hardened = _load_json(
        root / "reports/data/hiddenbench-hardened-analysis-20260804.json"
    )
    blind = _load_json(
        root
        / "artifacts/hiddenbench-stability-20260729.blind-review.gpt.summary.json"
    )
    governance_config = _load_json(
        root / "configs/hiddenbench-ai-disclosure-stability-v2.json"
    )
    structured_config = _load_json(
        root / "configs/hiddenbench-structured-20260802.json"
    )
    contrast_config = _load_json(
        root / "configs/hiddenbench-contrast-20260803.json"
    )
    earlystop_config = _load_json(
        root / "configs/hiddenbench-earlystop-20260803.json"
    )
    confirmatory_config = _load_json(
        root / "configs/hiddenbench-confirmatory-20260804.json"
    )
    supplement_config = _load_json(
        root / "configs/hiddenbench-official-reveal-supplement-20260804.json"
    )

    discussion_vote_requests = sum(stage_api_requests.values())
    disclosure_audit_requests = sum(audit_api_requests.values())
    local_runs = sum(stage_counts.values())
    if (local_runs, discussion_vote_requests, disclosure_audit_requests) != (
        560,
        25531,
        397,
    ):
        raise ValueError(
            "locked cumulative totals changed: "
            f"runs={local_runs}, run_requests={discussion_vote_requests}, "
            f"audit_requests={disclosure_audit_requests}"
        )
    if confirmatory["run_count"] != 210 or confirmatory["audit_count"] != 210:
        raise ValueError("confirmatory summary scope mismatch")
    if hardened["scope"]["official_reveal_supplement_runs"] != 30:
        raise ValueError("official reveal supplement scope mismatch")

    blind_metrics = blind["metrics"]
    historical = confirmatory["historical_appendix"]
    summary = {
        "schema_version": "hiddenbench-aug02-complete-summary-v1",
        "reporting_window": {
            "start": "2026-08-02",
            "end": "2026-08-04",
            "generated_on": "2026-08-05",
        },
        "scope": {
            "local_runs": local_runs,
            "discussion_vote_api_requests": discussion_vote_requests,
            "audit_api_requests": disclosure_audit_requests,
            "total_model_requests": (
                discussion_vote_requests + disclosure_audit_requests
            ),
            "confirmatory_runs": confirmatory["run_count"],
            "official_global_reveal_runs": hardened["scope"][
                "official_reveal_supplement_runs"
            ],
        },
        "stage_counts": stage_counts,
        "stage_api_requests": stage_api_requests,
        "audit_counts": audit_counts,
        "audit_api_requests": audit_api_requests,
        "all_gates_passed": True,
        "gate_checks": gate_checks,
        "exploratory": {
            "governance_rows": _governance_rows(root),
            "structured_rows": _structured_rows(root),
            "correct_runs_by_condition": historical[
                "correct_runs_by_condition"
            ],
            "earlystop_by_task": historical["earlystop_by_task"],
            "task_ids": governance_config["task_ids"],
        },
        "confirmatory": {
            "task_ids": confirmatory["task_ids"],
            "condition_count": confirmatory["condition_count"],
            "by_condition_task": confirmatory["by_condition_task"],
            "condition_statistics": hardened["condition_statistics"],
            "official_gpt41": hardened["official_gpt41"],
        },
        "paired_tests": hardened["paired_exact_tests"],
        "early_stop": hardened["early_stop"],
        "disclosure_example": hardened["disclosure_example"],
        "task_details": hardened["task_details"],
        "mast_cases": hardened["mast_cases"],
        "blind_review": {
            "status": "not_human_gold",
            "reviewer": blind["reviewer_id"],
            "population_size": blind["population_size"],
            "reviewed_size": blind["reviewed_size"],
            "reviewed_disclosed": blind["reviewed_disclosed"],
            "reviewed_undisclosed": blind["reviewed_undisclosed"],
            "ai_human_label_agreement_estimate": blind_metrics[
                "ai_human_agreement"
            ],
            "estimated_precision": blind_metrics["ai_precision"],
            "estimated_recall": blind_metrics["ai_recall"],
            "revised_disclosure_rate": blind_metrics[
                "revised_disclosure_rate"
            ],
            "note": blind["note"],
        },
        "configs": {
            "governance": governance_config,
            "structured": structured_config,
            "contrast": contrast_config,
            "earlystop": earlystop_config,
            "confirmatory": confirmatory_config,
            "official_global_reveal": supplement_config,
        },
        "method_boundaries": {
            "framework": (
                "Microsoft Agent Framework is the Agent/model execution layer; "
                "protocols, schedulers, reveal, voting, audits, and gates are "
                "project code."
            ),
            "selector": (
                "The five-factor dynamic selector is an external centralized "
                "scheduler with access to the complete private-fact assignment."
            ),
            "generation_seed": (
                "Pair seeds control fact assignment only; generation seed was "
                "not transmitted to DeepSeek."
            ),
            "blind_review": (
                "Codex model-assisted review; not a human gold standard."
            ),
            "protocol_split": (
                "The earlier owner-by-owner mechanical reveal differs from the "
                "official-compatible global first-round Reveal-All supplement."
            ),
        },
        "official_code": {
            "paper": "Li, Naito, and Shirado, arXiv:2505.11556",
            "repository": "https://github.com/Yassellee/HiddenBench_ICML",
            "verified_commit": "3be6ca16973e4fb751ffc0dfb7eb11f2d28335d1",
            "results": (
                "https://huggingface.co/datasets/"
                "YuxuanLi1225/HiddenBench-results"
            ),
            "implementation": "Author-written Python simulator, not MAF.",
            "short_reference_model": "gpt-4.1",
        },
        "publication": {
            "repository": "https://github.com/sbw51898-beep/mas",
            "pull_request": "https://github.com/sbw51898-beep/mas/pull/5",
            "branch": "codex/budget-matched-dynamic",
            "report_commit": "76e74cda72d90c008fec87f11a4ddd983b4ae296",
            "release": (
                "https://github.com/sbw51898-beep/mas/releases/tag/"
                "hiddenbench-confirmatory-20260804"
            ),
        },
        "source_sha256": dict(sorted(source_sha256.items())),
    }
    return summary


def write_complete_summary(root: Path, output: Path) -> Path:
    summary = build_complete_summary(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "reports/data/hiddenbench-aug02-complete-summary.json"
    print(write_complete_summary(root, output))


if __name__ == "__main__":
    main()
