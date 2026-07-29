from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_dynamic_domain import (
    FrozenBaselineConfig,
    load_dynamic_pilot_config,
)
from mas_experiment.hiddenbench_dynamic_gate import (
    load_and_validate_frozen_baseline,
)


ROOT = Path(__file__).parents[1]
CONFIG = load_dynamic_pilot_config(
    ROOT / "configs" / "hiddenbench-dynamic-pilot.json"
)


def test_committed_frozen_baseline_validates_three_pilot_tasks() -> None:
    runs = load_and_validate_frozen_baseline(ROOT, CONFIG)

    assert set(runs) == {1, 5, 7}
    assert all(len(run.discussion_messages) == 60 for run in runs.values())
    assert all(
        len({vote.vote for vote in run.hidden_post_votes}) == 1
        and run.hidden_post_votes[0].vote != run.task.correct_answer
        for run in runs.values()
    )


def copied_config(tmp_path: Path):
    frozen = CONFIG.frozen_baseline
    names = {
        "jsonl": Path(frozen.jsonl).name,
        "report": Path(frozen.report).name,
        "config": Path(frozen.config).name,
    }
    for key, name in names.items():
        shutil.copy2(ROOT / getattr(frozen, key), tmp_path / name)
    copied = FrozenBaselineConfig(
        **{
            **frozen.model_dump(),
            **names,
        }
    )
    return CONFIG.model_copy(update={"frozen_baseline": copied})


def test_tampered_baseline_is_rejected_before_json_parse(
    tmp_path: Path,
) -> None:
    config = copied_config(tmp_path)
    path = tmp_path / config.frozen_baseline.jsonl
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="baseline JSONL SHA-256 mismatch"):
        load_and_validate_frozen_baseline(tmp_path, config)


def test_tampered_baseline_config_is_rejected(tmp_path: Path) -> None:
    config = copied_config(tmp_path)
    path = tmp_path / config.frozen_baseline.config
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline config SHA-256 mismatch"):
        load_and_validate_frozen_baseline(tmp_path, config)
