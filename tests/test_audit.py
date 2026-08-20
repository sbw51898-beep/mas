from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import mas_experiment.audit as audit
from mas_experiment.audit import (
    configuration_fingerprint,
    current_git_commit,
    write_sha256_manifest,
)
from mas_experiment.datasets import SCREENING_QUESTIONS, SCREENING_ROLES


def test_configuration_fingerprint_is_deterministic_and_seed_sensitive() -> None:
    question = SCREENING_QUESTIONS[0]

    first = configuration_fingerprint(
        question,
        SCREENING_ROLES,
        seed=7,
    )
    second = configuration_fingerprint(
        question,
        SCREENING_ROLES,
        seed=7,
    )
    changed = configuration_fingerprint(
        question,
        SCREENING_ROLES,
        seed=8,
    )

    assert first == second
    assert len(first) == 64
    assert changed != first


def test_manifest_records_relative_names_sizes_and_sha256(tmp_path) -> None:
    result = tmp_path / "result.jsonl"
    report = tmp_path / "result.md"
    result.write_text('{"ok":true}\n', encoding="utf-8")
    report.write_text("# Report\n", encoding="utf-8")
    target = tmp_path / "result.manifest.json"

    written = write_sha256_manifest((result, report), target)
    manifest = json.loads(written.read_text(encoding="utf-8"))

    assert written == target
    assert {entry["path"] for entry in manifest["files"]} == {
        result.name,
        report.name,
    }
    by_path = {entry["path"]: entry for entry in manifest["files"]}
    assert by_path[result.name]["bytes"] == len(result.read_bytes())
    assert by_path[result.name]["sha256"] == hashlib.sha256(
        result.read_bytes()
    ).hexdigest()


def test_current_git_commit_normalizes_git_output(monkeypatch) -> None:
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="ABCDEF1234\n",
        ),
    )

    assert current_git_commit() == "abcdef1234"


def test_git_commands_decode_output_as_utf8_on_windows(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="?? 中文报告.docx\n", stderr="")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)

    assert audit._git(tmp_path, "status", "--porcelain=v1") == "?? 中文报告.docx"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"
