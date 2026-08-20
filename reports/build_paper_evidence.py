from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SUMMARY_PATH = Path("reports/data/hiddenbench-aug02-complete-summary.json")
REFERENCE_PATH = Path("reports/data/hiddenbench-paper-references-20260805.json")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_locked_claims(evidence: dict[str, Any]) -> None:
    expected_totals = {
        "local_runs": 560,
        "discussion_vote_requests": 25531,
        "audit_requests": 397,
        "model_requests": 25928,
    }
    if evidence["totals"] != expected_totals:
        raise ValueError(f"paper totals drifted: {evidence['totals']!r}")
    if evidence["official_global_reveal"] != {
        "ID1": "10/10",
        "ID2": "10/10",
        "ID3": "10/10",
    }:
        raise ValueError("official-compatible global Reveal-All counts drifted")
    if evidence["mcnemar_p_values"] != [0.125, 0.125, 0.388]:
        raise ValueError(f"paired exact p-values drifted: {evidence['mcnemar_p_values']!r}")
    if evidence["early_stop_exception"] != "2-2 final tie":
        raise ValueError("early-stop exception must remain a 2-2 final tie")
    if not evidence["all_gates_passed"]:
        raise ValueError("one or more source experiment gates failed")
    if evidence["reference_count"] < 15:
        raise ValueError("paper requires at least 15 references")


def build_paper_evidence(root: Path, output: Path) -> dict[str, Any]:
    summary = _load_json(root / SUMMARY_PATH)
    references = _load_json(root / REFERENCE_PATH)
    scope = summary["scope"]
    paired = summary["paired_tests"]
    stats = summary["confirmatory"]["condition_statistics"]

    official_global_reveal = {}
    for task_id in (1, 2, 3):
        item = stats[f"official-global-reveal:ID{task_id}"]
        official_global_reveal[f"ID{task_id}"] = f"{item['successes']}/{item['runs']}"

    evidence: dict[str, Any] = {
        "schema_version": "hiddenbench-paper-evidence-v1",
        "paper_title": "基于 MAF 的多智能体私有信息披露机制复现与对比研究",
        "research_questions": {
            "RQ1": "完整披露私有信息是否提高 HiddenBench 任务正确率？",
            "RQ2": "相同发言预算下，动态发言机制是否优于固定轮转？",
            "RQ3": "多智能体错误共识由哪些信息处理环节造成？",
        },
        "totals": {
            "local_runs": scope["local_runs"],
            "discussion_vote_requests": scope["discussion_vote_api_requests"],
            "audit_requests": scope["audit_api_requests"],
            "model_requests": scope["total_model_requests"],
        },
        "official_global_reveal": official_global_reveal,
        "official_gpt41": summary["confirmatory"]["official_gpt41"],
        "condition_statistics": summary["confirmatory"]["condition_statistics"],
        "condition_metrics": summary["confirmatory"]["by_condition_task"],
        "paired_tests": paired,
        "mcnemar_p_values": [
            round(paired["fixed-60_vs_dynamic-60"]["p_value"], 3),
            round(paired["fixed-reveal-all_vs_dynamic-reveal-all"]["p_value"], 3),
            round(paired["fixed-12_vs_structured-12"]["p_value"], 3),
        ],
        "early_stop": summary["early_stop"],
        "early_stop_exception": "2-2 final tie",
        "disclosure_example": summary["disclosure_example"],
        "mast_cases": summary["mast_cases"],
        "method_boundaries": summary["method_boundaries"],
        "task_details": summary["task_details"],
        "stage_counts": summary["stage_counts"],
        "stage_api_requests": summary["stage_api_requests"],
        "gate_checks": summary["gate_checks"],
        "all_gates_passed": summary["all_gates_passed"],
        "official_code": summary["official_code"],
        "publication": summary["publication"],
        "blind_review": summary["blind_review"],
        "reference_count": len(references),
        "reference_keys": [item["key"] for item in references],
        "source_hashes": summary["source_sha256"],
    }
    _validate_locked_claims(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the locked evidence snapshot for the paper-style report.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/data/hiddenbench-paper-evidence-20260805.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    evidence = build_paper_evidence(root, output)
    print(json.dumps({"output": str(output), "totals": evidence["totals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
