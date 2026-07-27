from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mas_experiment.domain import ExperimentResult


_SECRET_KEY_PARTS = ("api_key", "authorization", "token", "secret")


def _sanitize(value: Any, *, key: str = "") -> Any:
    normalized_key = key.casefold()
    if any(part in normalized_key for part in _SECRET_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_sanitize(item) for item in value]
    return value


def append_result(path: str | Path, result: ExperimentResult) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = result.model_dump(mode="json")
    sanitized = _sanitize(record)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(sanitized, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def read_results(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
