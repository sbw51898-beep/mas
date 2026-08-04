from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reports.build_aug02_complete_summary import (
    build_complete_summary,
    write_complete_summary,
)


ROOT = Path(__file__).parents[1]


def test_complete_summary_locks_scope_and_boundaries() -> None:
    summary = build_complete_summary(ROOT)

    assert summary["scope"] == {
        "local_runs": 560,
        "discussion_vote_api_requests": 25531,
        "audit_api_requests": 397,
        "total_model_requests": 25928,
        "confirmatory_runs": 210,
        "official_global_reveal_runs": 30,
    }
    assert summary["stage_counts"] == {
        "governance_20260802": 80,
        "structured_20260802": 40,
        "contrast_20260803": 120,
        "earlystop_20260803": 80,
        "confirmatory_20260804": 210,
        "official_global_reveal_20260804": 30,
    }
    assert summary["audit_counts"] == {
        "governance_20260802": 80,
        "structured_20260802": 40,
        "contrast_20260803": 40,
        "earlystop_20260803": 80,
        "confirmatory_20260804": 210,
    }
    assert summary["blind_review"]["status"] == "not_human_gold"
    assert summary["blind_review"]["reviewed_size"] == 144
    assert summary["early_stop"]["classifications"] == {
        "same-majority": 29,
        "final-tie": 1,
    }
    assert summary["early_stop"]["candidate_correct"] == 17
    assert summary["early_stop"]["final_correct"] == 17
    assert (
        summary["paired_tests"]["fixed-60_vs_dynamic-60"]["p_value"]
        == 0.125
    )
    assert round(
        summary["paired_tests"]["fixed-12_vs_structured-12"]["p_value"],
        3,
    ) == 0.388
    assert summary["disclosure_example"]["arithmetic"] == (
        "3 disclosed / 4 total = 75.0%"
    )
    assert summary["method_boundaries"]["blind_review"] == (
        "Codex model-assisted review; not a human gold standard."
    )
    assert summary["method_boundaries"]["generation_seed"] == (
        "Pair seeds control fact assignment only; generation seed was not "
        "transmitted to DeepSeek."
    )


def test_complete_summary_is_byte_deterministic_and_source_backed(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_complete_summary(ROOT, first)
    write_complete_summary(ROOT, second)

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["all_gates_passed"] is True
    assert set(payload["source_sha256"]) >= {
        "hiddenbench-governance-20260802.jsonl",
        "hiddenbench-structured-20260802.jsonl",
        "hiddenbench-contrast-20260803.jsonl",
        "hiddenbench-earlystop-20260803.jsonl",
        "hiddenbench-confirmatory-20260804.jsonl",
        "hiddenbench-official-reveal-supplement-20260804.jsonl",
    }
    for digest in payload["source_sha256"].values():
        assert len(digest) == 64
        int(digest, 16)
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
