from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from reports.package_hardened_confirmatory_evidence import package_evidence


def test_package_evidence_writes_trace_provenance_manifest_and_zip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True)
    (root / "artifacts").mkdir()
    (root / "reports" / "data").mkdir(parents=True)
    (root / "configs" / "study.json").write_text(
        json.dumps(
            {
                "configuration_version": "test-v1",
                "frozen_code_commit": "abc123",
                "provider": {"model": "deepseek-v4-flash"},
            }
        ),
        encoding="utf-8",
    )
    row = {
        "key": {"task_id": 1, "condition": "official-global-reveal", "repetition": 0},
        "pair_seed": 7,
        "assignment_fingerprint": "assignment-sha",
        "run_commit": "run-commit",
        "frozen_code_commit": "abc123",
        "run": {
            "run_id": "run-1",
            "task": {"name": "example", "correct_answer": "West City"},
            "discussion_messages": [{"content": "message"}],
            "hidden_post_votes": [
                {"vote": "West City"},
                {"vote": "West City"},
                {"vote": "West City"},
                {"vote": "West City"},
            ],
            "metrics": {
                "post_majority_correct": True,
                "post_unanimous": True,
                "api_requests": 72,
            },
        },
    }
    raw = root / "artifacts" / "runs.jsonl"
    raw.write_text(json.dumps(row) + "\n", encoding="utf-8")
    gate = root / "artifacts" / "gate.json"
    gate.write_text('{"passed":true}\n', encoding="utf-8")
    summary = root / "reports" / "data" / "summary.json"
    summary.write_text('{"runs":1}\n', encoding="utf-8")

    outputs = package_evidence(
        root=root,
        input_paths=(root / "configs" / "study.json", raw, gate, summary),
        raw_runs_path=raw,
        release_dir=root / "release",
        stem="test-package",
        generated_at="2026-08-04T00:00:00Z",
    )

    trace_rows = [
        json.loads(line)
        for line in outputs["trace"].read_text(encoding="utf-8").splitlines()
    ]
    assert trace_rows == [
        {
            "api_requests": 72,
            "assignment_fingerprint": "assignment-sha",
            "condition": "official-global-reveal",
            "discussion_messages": 1,
            "frozen_code_commit": "abc123",
            "majority_correct": True,
            "pair_seed": 7,
            "repetition": 0,
            "run_commit": "run-commit",
            "run_id": "run-1",
            "task_id": 1,
            "task_name": "example",
            "unanimous": True,
            "votes": ["West City", "West City", "West City", "West City"],
        }
    ]
    provenance = json.loads(outputs["provenance"].read_text(encoding="utf-8"))
    assert provenance["configuration_version"] == "test-v1"
    assert provenance["frozen_code_commit"] == "abc123"
    assert provenance["model"] == "deepseek-v4-flash"

    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    assert manifest["generated_at"] == "2026-08-04T00:00:00Z"
    assert {item["path"] for item in manifest["files"]} == {
        "configs/study.json",
        "artifacts/runs.jsonl",
        "artifacts/gate.json",
        "reports/data/summary.json",
        "release/test-package.trace.jsonl",
        "release/test-package.provenance.json",
    }

    with zipfile.ZipFile(outputs["zip"]) as archive:
        assert set(archive.namelist()) == {
            item["path"] for item in manifest["files"]
        } | {"release/test-package.manifest.json"}
    expected = hashlib.sha256(outputs["zip"].read_bytes()).hexdigest()
    assert outputs["sha256"].read_text(encoding="utf-8") == (
        f"{expected}  test-package-raw.zip\n"
    )
