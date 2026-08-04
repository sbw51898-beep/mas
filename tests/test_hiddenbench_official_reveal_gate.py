from __future__ import annotations

from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_dynamic_domain import DynamicProviderConfig
from mas_experiment.hiddenbench_official_reveal_gate import (
    build_official_reveal_gate,
)
from mas_experiment.hiddenbench_official_reveal_supplement import (
    OfficialRevealSupplementConfig,
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


@pytest.mark.asyncio
async def test_complete_offline_supplement_passes_named_gate_checks(
    tmp_path: Path,
) -> None:
    output = tmp_path / "supplement.jsonl"
    await run_official_reveal_supplement(
        tasks=(TASK,),
        config=_config(),
        provider_factory=StabilityOfflineProvider,
        output=output,
        resume=False,
    )
    records = read_official_reveal_records(output, config=_config())

    complete = build_official_reveal_gate(
        _config(),
        records,
        dataset_path=DATASET,
    )
    missing = build_official_reveal_gate(
        _config(),
        records[:-1],
        dataset_path=DATASET,
    )

    assert complete.passed is True
    assert all(complete.checks.values())
    assert complete.api_requests == 0
    assert missing.passed is False
    assert missing.checks["complete_run_matrix"] is False
    assert set(complete.checks) == {
        "complete_run_matrix",
        "unique_run_keys",
        "deterministic_row_order",
        "task_and_dataset_hashes",
        "paired_seed_and_assignment",
        "message_budget",
        "official_global_reveal_timing",
        "provider_settings",
        "code_commit_provenance",
        "credential_leak_scan",
    }

