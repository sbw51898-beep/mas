import json
from pathlib import Path

from reports.build_paper_evidence import build_paper_evidence


ROOT = Path(__file__).resolve().parents[1]


def test_paper_evidence_locks_headline_results(tmp_path: Path) -> None:
    output = tmp_path / "paper-evidence.json"

    evidence = build_paper_evidence(ROOT, output)

    assert output.exists()
    assert evidence["totals"] == {
        "local_runs": 560,
        "discussion_vote_requests": 25531,
        "audit_requests": 397,
        "model_requests": 25928,
    }
    assert evidence["official_global_reveal"] == {
        "ID1": "10/10",
        "ID2": "10/10",
        "ID3": "10/10",
    }
    assert evidence["mcnemar_p_values"] == [0.125, 0.125, 0.388]
    assert evidence["early_stop_exception"] == "2-2 final tie"
    assert evidence["all_gates_passed"] is True


def test_paper_evidence_records_method_boundaries_and_sources(tmp_path: Path) -> None:
    output = tmp_path / "paper-evidence.json"

    evidence = build_paper_evidence(ROOT, output)

    assert evidence["method_boundaries"]["framework"]
    assert "external centralized scheduler" in evidence["method_boundaries"]["selector"]
    assert "generation seed was not transmitted" in evidence["method_boundaries"]["generation_seed"]
    assert evidence["source_hashes"]
    assert evidence["reference_count"] >= 15
    reloaded = json.loads(output.read_text(encoding="utf-8"))
    assert reloaded == evidence
