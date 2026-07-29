from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mas_experiment.hiddenbench_data import load_hiddenbench_task
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_stability_domain import (
    load_stability_config,
)
from mas_experiment.hiddenbench_stability_protocol import (
    expected_study_keys,
    read_completed_study_records,
    run_stability_study,
    run_study_pair,
)
from mas_experiment.providers import ScriptedPromptProvider


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_stability_config(
    ROOT / "configs/hiddenbench-ai-disclosure-stability.json"
)
TASK = load_hiddenbench_task(
    ROOT / "data/hiddenbench/benchmark.json",
    task_id=1,
    expected_sha256=CONFIG.dataset_sha256,
)


def vote_text(vote: str) -> str:
    return json.dumps(
        {"vote": vote, "rationale": f"Evidence favors {vote}."}
    )


def protocol_script() -> tuple[str, ...]:
    return (
        *(vote_text("West City") for _ in range(4)),
        *(
            f"I recommend West City. Discussion statement {index:02d}."
            for index in range(60)
        ),
        *(vote_text("West City") for _ in range(4)),
        *(vote_text("West City") for _ in range(4)),
    )


def test_expected_matrix_has_eighty_unique_keys() -> None:
    keys = expected_study_keys(CONFIG)

    assert len(keys) == 80
    assert len({key.value for key in keys}) == 80


@pytest.mark.asyncio
async def test_pair_reuses_seed_assignment_and_budget() -> None:
    fixed, dynamic = await run_study_pair(
        task=TASK,
        repetition=2,
        config=CONFIG,
        fixed_provider=ScriptedPromptProvider(protocol_script()),
        dynamic_provider=ScriptedPromptProvider(protocol_script()),
    )

    assert fixed.pair_seed == dynamic.pair_seed
    assert fixed.assignment_fingerprint == dynamic.assignment_fingerprint
    assert len(fixed.run.discussion_messages) == 60
    assert len(dynamic.run.discussion_messages) == 60
    assert Counter(
        message.agent_id
        for message in dynamic.run.discussion_messages
    ) == {agent: 15 for agent in AGENT_IDS}


@pytest.mark.asyncio
async def test_resume_skips_complete_pair_without_provider_call(
    tmp_path: Path,
) -> None:
    fixed, dynamic = await run_study_pair(
        task=TASK,
        repetition=0,
        config=CONFIG,
        fixed_provider=ScriptedPromptProvider(protocol_script()),
        dynamic_provider=ScriptedPromptProvider(protocol_script()),
    )
    output = tmp_path / "study.jsonl"
    output.write_text(
        "\n".join(
            record.model_dump_json()
            for record in (fixed, dynamic)
        )
        + "\n",
        encoding="utf-8",
    )

    def provider_factory() -> ScriptedPromptProvider:
        raise AssertionError("resume should not create a provider")

    result = await run_stability_study(
        tasks=(TASK,),
        config=CONFIG,
        provider_factory=provider_factory,
        output=output,
        resume=True,
        requested_pairs=((1, 0),),
    )

    assert result.executed_pairs == ()
    assert result.skipped_pairs == ("task-1:rep-0",)


@pytest.mark.asyncio
async def test_partial_pair_is_rejected_on_resume(
    tmp_path: Path,
) -> None:
    fixed, _ = await run_study_pair(
        task=TASK,
        repetition=1,
        config=CONFIG,
        fixed_provider=ScriptedPromptProvider(protocol_script()),
        dynamic_provider=ScriptedPromptProvider(protocol_script()),
    )
    output = tmp_path / "study.jsonl"
    output.write_text(
        fixed.model_dump_json() + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="partial pair"):
        read_completed_study_records(output)
