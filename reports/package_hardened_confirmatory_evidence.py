from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"evidence path is outside repository root: {path}") from error


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {line_number} is not an object")
            yield value


def _trace_row(row: dict) -> dict:
    key = row["key"]
    run = row["run"]
    metrics = run["metrics"]
    votes = [vote["vote"] for vote in run["hidden_post_votes"]]
    return {
        "api_requests": metrics["api_requests"],
        "assignment_fingerprint": row["assignment_fingerprint"],
        "condition": key["condition"],
        "discussion_messages": len(run["discussion_messages"]),
        "frozen_code_commit": row["frozen_code_commit"],
        "majority_correct": metrics["post_majority_correct"],
        "pair_seed": row["pair_seed"],
        "repetition": key["repetition"],
        "run_commit": row["run_commit"],
        "run_id": run["run_id"],
        "task_id": key["task_id"],
        "task_name": run["task"]["name"],
        "unanimous": metrics["post_unanimous"],
        "votes": votes,
    }


def _write_deterministic_zip(
    *,
    root: Path,
    paths: Iterable[Path],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted((_relative_posix(root, path), path) for path in paths)
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for archive_name, path in entries:
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


def package_evidence(
    *,
    root: Path,
    input_paths: tuple[Path, ...],
    raw_runs_path: Path,
    release_dir: Path,
    stem: str,
    generated_at: str | None = None,
) -> dict[str, Path]:
    root = root.resolve()
    input_paths = tuple(path.resolve() for path in input_paths)
    raw_runs_path = raw_runs_path.resolve()
    release_dir = release_dir.resolve()
    for path in (*input_paths, raw_runs_path):
        if not path.is_file():
            raise FileNotFoundError(path)
        _relative_posix(root, path)

    config_path = next(
        (path for path in input_paths if path.parent.name == "configs"),
        None,
    )
    if config_path is None:
        raise ValueError("evidence package requires one config under configs/")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    rows = list(_iter_jsonl(raw_runs_path))
    if not rows:
        raise ValueError("raw supplement JSONL is empty")

    trace_path = release_dir / f"{stem}.trace.jsonl"
    provenance_path = release_dir / f"{stem}.provenance.json"
    manifest_path = release_dir / f"{stem}.manifest.json"
    zip_path = release_dir / f"{stem}-raw.zip"
    sha_path = release_dir / f"{stem}-raw.sha256"
    release_dir.mkdir(parents=True, exist_ok=True)

    trace_rows = [_trace_row(row) for row in rows]
    trace_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in trace_rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    provider = config.get("provider", {})
    provenance = {
        "configuration_path": _relative_posix(root, config_path),
        "configuration_sha256": _sha256(config_path),
        "configuration_version": config.get("configuration_version"),
        "frozen_code_commit": config.get("frozen_code_commit"),
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": provider.get("model"),
        "raw_runs_path": _relative_posix(root, raw_runs_path),
        "raw_runs_sha256": _sha256(raw_runs_path),
        "run_count": len(rows),
        "total_api_requests": sum(
            int(row["run"]["metrics"]["api_requests"]) for row in rows
        ),
    }
    _write_json(provenance_path, provenance)

    packaged_paths = tuple(dict.fromkeys((*input_paths, trace_path, provenance_path)))
    manifest = {
        "files": [
            {
                "bytes": path.stat().st_size,
                "path": _relative_posix(root, path),
                "sha256": _sha256(path),
            }
            for path in sorted(
                packaged_paths,
                key=lambda value: _relative_posix(root, value),
            )
        ],
        "generated_at": provenance["generated_at"],
        "manifest_version": "1",
    }
    _write_json(manifest_path, manifest)
    _write_deterministic_zip(
        root=root,
        paths=(*packaged_paths, manifest_path),
        destination=zip_path,
    )
    sha_path.write_text(
        f"{_sha256(zip_path)}  {zip_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "manifest": manifest_path,
        "provenance": provenance_path,
        "sha256": sha_path,
        "trace": trace_path,
        "zip": zip_path,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    stem = "hiddenbench-official-reveal-supplement-20260804"
    raw = root / "artifacts" / f"{stem}.jsonl"
    outputs = package_evidence(
        root=root,
        input_paths=(
            root / "configs" / f"{stem}.json",
            raw,
            root / "artifacts" / f"{stem}.gate.json",
            root
            / "reports"
            / "data"
            / "hiddenbench-official-reveal-supplement-summary.json",
            root / "reports" / "data" / "hiddenbench-hardened-analysis-20260804.json",
            root / "reports" / "data" / "hiddenbench-hardened-statistics-20260804.csv",
            root / "reports" / "data" / "hiddenbench-mast-cases-20260804.csv",
        ),
        raw_runs_path=raw,
        release_dir=root / "release",
        stem=stem,
        generated_at="2026-08-04T00:00:00Z",
    )
    for name, path in sorted(outputs.items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
