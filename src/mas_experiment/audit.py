from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mas_experiment.domain import AgentRole, Question


class GitWorktreeError(RuntimeError):
    """Raised when a formal run cannot be tied to frozen Git state."""


class GitWorktreeState(BaseModel):
    model_config = ConfigDict(frozen=True)

    commit: str
    branch: str
    dirty: bool
    porcelain: tuple[str, ...]


def _git(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitWorktreeError(f"git command failed: {' '.join(args)}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise GitWorktreeError(
            f"git command failed ({' '.join(args)}): {detail}"
        )
    return result.stdout.strip()


def inspect_git_worktree(path: Path) -> GitWorktreeState:
    resolved = path.resolve()
    commit = _git(resolved, "rev-parse", "HEAD").casefold()
    branch = _git(resolved, "branch", "--show-current")
    porcelain = tuple(
        line
        for line in _git(
            resolved,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).splitlines()
        if line.strip()
    )
    return GitWorktreeState(
        commit=commit,
        branch=branch,
        dirty=bool(porcelain),
        porcelain=porcelain,
    )


def require_clean_git_commit(path: Path, expected_commit: str) -> str:
    state = inspect_git_worktree(path)
    if not state.branch:
        raise GitWorktreeError("formal run requires a named branch")
    if state.dirty:
        raise GitWorktreeError(
            "formal run requires a clean worktree; dirty entries: "
            + ", ".join(state.porcelain)
        )
    normalized_expected = expected_commit.strip().casefold()
    if state.commit != normalized_expected:
        raise GitWorktreeError(
            "frozen_code_commit does not equal HEAD: "
            f"expected {normalized_expected}, found {state.commit}"
        )
    return state.commit


def require_clean_confirmatory_state(
    path: Path,
    frozen_code_commit: str,
) -> GitWorktreeState:
    """Require a clean config-only child of the frozen runtime commit."""
    state = inspect_git_worktree(path)
    if not state.branch:
        raise GitWorktreeError("formal run requires a named branch")
    if state.dirty:
        raise GitWorktreeError(
            "formal run requires a clean worktree; dirty entries: "
            + ", ".join(state.porcelain)
        )
    normalized = frozen_code_commit.strip().casefold()
    parent = _git(path.resolve(), "rev-parse", "HEAD^").casefold()
    if parent != normalized:
        raise GitWorktreeError(
            "formal confirmatory HEAD must be the config-only child of "
            f"frozen_code_commit {normalized}; found parent {parent}"
        )
    runtime_changes = tuple(
        line
        for line in _git(
            path.resolve(),
            "diff",
            "--name-only",
            f"{normalized}..HEAD",
            "--",
            "src",
            "tests",
        ).splitlines()
        if line.strip()
    )
    if runtime_changes:
        raise GitWorktreeError(
            "config-only freeze changed src/tests: "
            + ", ".join(runtime_changes)
        )
    return state


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
