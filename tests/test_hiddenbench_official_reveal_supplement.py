from __future__ import annotations

from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_dynamic_domain import DynamicProviderConfig
from mas_experiment.hiddenbench_official_reveal_supplement import (
    OfficialRevealSupplementConfig,
    expected_official_reveal_keys,
    read_official_reveal_records,
    run_official_reveal_supplement,
)
from mas_experiment.providers import StabilityOfflineProvider


ROOT = Path(__file__).parents[1]
DATASET = ROOT / "data" / "hiddenbench" / "benchmark.json"
DATASET_SHA = (
    "2815afffca4e470d1dfbc81e625160447df1109ce371968181c9e1e6b90443a3"
)
TASK = load_hiddenbench_task(
    DATASET,
    task_id=1,
    expected_sha256=DATASET_SHA,
)


def _config() -> OfficialRevealSupplementConfig:
    locked = OfficialRevealSupplementConfig(
        configuration_version="hiddenbench-official-reveal-supplement-v1",
        task_ids=(1, 2, 3),
        repetitions=10,
        base_seed=20260804,
        dataset_sha256=DATASET_SHA,
        frozen_code_commit="0" * 40,
        experiment_workers=1,
        provider=DynamicProviderConfig(
            model="deepseek-v4-flash",
            temperature=0,
            thinking="disabled",
        ),
    )
    return locked.model_copy(
        update={"task_ids": (1,), "repetitions": 2}
    )


def test_expected_keys_use_task_then_repetition_order() -> None:
    assert [
        key.value for key in expected_official_reveal_keys(_config())
    ] == [
        "task-1:official-global-reveal:rep-0",
        "task-1:official-global-reveal:rep-1",
    ]


@pytest.mark.asyncio
async def test_official_reveal_study_is_append_only_and_resumable(
    tmp_path: Path,
) -> None:
    output = tmp_path / "supplement.jsonl"

    first = await run_official_reveal_supplement(
        tasks=(TASK,),
        config=_config(),
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=False,
    )
    resumed = await run_official_reveal_supplement(
        tasks=(TASK,),
        config=_config(),
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=True,
    )

    records = read_official_reveal_records(output, config=_config())
    assert first.executed_runs == 2
    assert first.skipped_runs == 0
    assert resumed.executed_runs == 0
    assert resumed.skipped_runs == 2
    assert len(records) == 2
    assert [record.key.value for record in records] == [
        "task-1:official-global-reveal:rep-0",
        "task-1:official-global-reveal:rep-1",
    ]
    for record in records:
        messages = record.run.discussion_messages
        assert len(messages) == 60
        assert all(
            message.provider_metadata["global_reveal_round_one"] is True
            and len(message.provider_metadata["appended_fact_ids"]) == 4
            for message in messages[:4]
        )
        assert all(
            message.provider_metadata["global_reveal_round_one"] is False
            and message.provider_metadata["appended_fact_ids"] == []
            for message in messages[4:]
        )


def test_reader_rejects_a_non_prefix_row(tmp_path: Path) -> None:
    output = tmp_path / "supplement.jsonl"
    output.write_text(
        '{"key":{"task_id":1,"condition":"official-global-reveal",'
        '"repetition":1}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid supplement record"):
        read_official_reveal_records(output, config=_config())

