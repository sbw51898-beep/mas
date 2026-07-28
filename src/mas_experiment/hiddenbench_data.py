from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


EXPECTED_RECORD_COUNT = 65


class HiddenBenchTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    description: str
    shared_information: tuple[str, ...]
    hidden_information: tuple[str, ...]
    possible_answers: tuple[str, ...]
    correct_answer: str
    rationale: str | None = None

    @model_validator(mode="after")
    def validate_task(self) -> HiddenBenchTask:
        if self.correct_answer not in self.possible_answers:
            raise ValueError(
                "correct_answer must belong to possible_answers"
            )
        if not self.hidden_information:
            raise ValueError("hidden_information must not be empty")
        if len(set(self.possible_answers)) != len(self.possible_answers):
            raise ValueError("possible_answers must be unique")
        return self


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hiddenbench_tasks(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[HiddenBenchTask, ...]:
    actual_sha256 = sha256_file(path)
    if actual_sha256.casefold() != expected_sha256.casefold():
        raise ValueError(
            "HiddenBench SHA-256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("HiddenBench dataset root must be a list")

    tasks = tuple(HiddenBenchTask.model_validate(item) for item in payload)
    if len(tasks) != EXPECTED_RECORD_COUNT:
        raise ValueError(
            "HiddenBench snapshot must contain "
            f"{EXPECTED_RECORD_COUNT} tasks, got {len(tasks)}"
        )
    task_ids = [task.id for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("duplicate HiddenBench task ID")
    return tasks


def load_hiddenbench_task(
    path: Path,
    *,
    task_id: int,
    expected_sha256: str,
) -> HiddenBenchTask:
    tasks = load_hiddenbench_tasks(
        path,
        expected_sha256=expected_sha256,
    )
    for task in tasks:
        if task.id == task_id:
            return task
    raise ValueError(f"HiddenBench task ID not found: {task_id}")
