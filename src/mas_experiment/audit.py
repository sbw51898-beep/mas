from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from mas_experiment.domain import AgentRole, Question


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    commit = result.stdout.strip().casefold()
    return commit or "unknown"


def configuration_fingerprint(
    question: Question,
    roles: tuple[AgentRole, ...],
    *,
    seed: int,
) -> str:
    payload = {
        "question": question.model_dump(mode="json"),
        "roles": [role.model_dump(mode="json") for role in roles],
        "seed": seed,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_sha256_manifest(
    paths: Sequence[Path],
    destination: Path,
) -> Path:
    files = []
    for path in paths:
        content = path.read_bytes()
        files.append(
            {
                "path": path.name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "manifest_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
