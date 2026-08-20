from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
    re.compile(r"\bOPENAI_API_KEY\s*=", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|authorization)\s*[:=]\s*[^\s]{16,}", re.IGNORECASE),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(parent.resolve())
    return resolved


def _scan(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"secret-like content found in {path.name}")


def package(root: Path) -> tuple[Path, Path]:
    artifacts = (root / "artifacts").resolve()
    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)
    summary = json.loads(
        (root / "reports/data/hiddenbench-confirmatory-summary.json").read_text(
            encoding="utf-8"
        )
    )
    compact_json = artifacts / "hiddenbench-confirmatory-20260804.summary.json"
    shutil.copy2(
        root / "reports/data/hiddenbench-confirmatory-summary.json",
        compact_json,
    )
    compact_csv = artifacts / "hiddenbench-confirmatory-20260804.summary.csv"
    with compact_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "condition_task",
                "runs",
                "majority_accuracy",
                "vote_accuracy",
                "atomic_disclosure_rate",
                "false_consensus_rate",
            ]
        )
        for key, value in sorted(summary["by_condition_task"].items()):
            writer.writerow(
                [
                    key,
                    value["runs"],
                    value["majority_accuracy"],
                    value["vote_accuracy"],
                    value["atomic_disclosure_rate"],
                    value["false_consensus_rate"],
                ]
            )

    runs = artifacts / "hiddenbench-confirmatory-20260804.jsonl"
    trace = artifacts / "hiddenbench-confirmatory-20260804.trace.jsonl"
    with runs.open(encoding="utf-8") as source, trace.open(
        "w", encoding="utf-8", newline="\n"
    ) as destination:
        for line in source:
            row = json.loads(line)
            destination.write(
                json.dumps(
                    {
                        "key": row["key"],
                        "run_id": row["run"]["run_id"],
                        "selection_events": row["selection_events"],
                        "shadow_checkpoints": row["shadow_checkpoints"],
                        "early_stop": row["early_stop"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    copied = {
        "hiddenbench-confirmatory-20260804.earlystop.csv": root
        / "reports/data/hiddenbench-confirmatory-earlystop-cases.csv",
        "hiddenbench-confirmatory-20260804.atomic-disclosure.csv": root
        / "reports/data/hiddenbench-confirmatory-atomic-disclosure.csv",
        "hiddenbench-official-gpt41-short-summary.json": root
        / "reports/data/hiddenbench-official-gpt41-short-summary.json",
    }
    for name, source in copied.items():
        shutil.copy2(source, artifacts / name)

    provenance = artifacts / "hiddenbench-confirmatory-20260804.provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "run_count": summary["run_count"],
                "audit_count": summary["audit_count"],
                "run_api_requests": summary["run_api_requests"],
                "audit_api_requests": summary["audit_api_requests"],
                "run_commits": summary["run_commits"],
                "frozen_code_commits": summary["frozen_code_commits"],
                "audit_code_commits": summary["audit_code_commits"],
                "connectivity_probe_api_requests": 1,
                "partial_audit_backup": (
                    "hiddenbench-confirmatory-20260804.audits.v1-partial-194.jsonl"
                ),
                "audit_repair": (
                    "Near-match evidence quotes were locally reanchored only "
                    "inside cited owner-authored messages; all 210 audits were rerun."
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    names = [
        "hiddenbench-confirmatory-20260804.jsonl",
        "hiddenbench-confirmatory-20260804.audits.jsonl",
        "hiddenbench-confirmatory-20260804.audits.v1-partial-194.jsonl",
        "hiddenbench-confirmatory-20260804.trace.jsonl",
        "hiddenbench-confirmatory-20260804.summary.json",
        "hiddenbench-confirmatory-20260804.summary.csv",
        "hiddenbench-confirmatory-20260804.gate.json",
        "hiddenbench-confirmatory-20260804.earlystop.csv",
        "hiddenbench-confirmatory-20260804.atomic-disclosure.csv",
        "hiddenbench-confirmatory-20260804.provenance.json",
        "hiddenbench-official-gpt41-short-summary.json",
    ]
    official_dir = artifacts / "hiddenbench-official-short-20260804"
    for name in (
        "official_baseline.json",
        "official_reveal_all.json",
        "official_short_summary.json",
    ):
        path = _inside(official_dir / name, artifacts)
        if not path.is_file():
            raise FileNotFoundError(path)
        names.append(f"hiddenbench-official-short-20260804/{name}")

    paths = [_inside(artifacts / name, artifacts) for name in names]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        _scan(path)
    manifest = artifacts / "hiddenbench-confirmatory-20260804.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": "hiddenbench-confirmatory-v1",
                "files": [
                    {
                        "path": path.relative_to(artifacts).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": _sha(path),
                    }
                    for path in paths
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths.append(manifest)
    _scan(manifest)

    archive = release / "hiddenbench-confirmatory-20260804-raw.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(artifacts).as_posix())
    with ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("release ZIP CRC validation failed")
        for member in bundle.infolist():
            content = bundle.read(member).decode("utf-8", errors="ignore")
            for pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    raise ValueError(f"secret-like content in ZIP: {member.filename}")
    digest = _sha(archive)
    checksum = release / "hiddenbench-confirmatory-20260804-raw.sha256"
    checksum.write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return archive, checksum


def main() -> None:
    archive, checksum = package(Path(__file__).resolve().parents[1])
    print(archive)
    print(checksum)


if __name__ == "__main__":
    main()
