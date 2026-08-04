from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mas_experiment.audit import (
    GitWorktreeError,
    inspect_git_worktree,
    require_clean_confirmatory_state,
    require_clean_git_commit,
)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD").casefold()


def test_clean_repo_returns_exact_head(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)

    state = inspect_git_worktree(repo)

    assert state.commit == head
    assert state.dirty is False
    assert state.porcelain == ()
    assert require_clean_git_commit(repo, head) == head


def test_untracked_file_blocks_formal_run(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    (repo / "new.py").write_text("print('dirty')\n", encoding="utf-8")

    with pytest.raises(GitWorktreeError, match="dirty"):
        require_clean_git_commit(repo, head)


def test_expected_commit_mismatch_blocks_formal_run(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)

    with pytest.raises(GitWorktreeError, match="frozen_code_commit"):
        require_clean_git_commit(repo, "0" * 40)


def test_detached_head_blocks_formal_run(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    _git(repo, "checkout", "--detach", head)

    with pytest.raises(GitWorktreeError, match="named branch"):
        require_clean_git_commit(repo, head)


def test_confirmatory_state_accepts_config_only_child_commit(
    tmp_path: Path,
) -> None:
    repo, runtime_commit = _repo(tmp_path)
    (repo / "config.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "config.json")
    _git(repo, "commit", "-m", "freeze config")

    state = require_clean_confirmatory_state(repo, runtime_commit)

    assert state.commit == _git(repo, "rev-parse", "HEAD").casefold()


def test_confirmatory_state_rejects_runtime_code_after_frozen_parent(
    tmp_path: Path,
) -> None:
    repo, runtime_commit = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "changed.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "src/changed.py")
    _git(repo, "commit", "-m", "change runtime")

    with pytest.raises(GitWorktreeError, match="src/tests"):
        require_clean_confirmatory_state(repo, runtime_commit)
