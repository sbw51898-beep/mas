from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicSelectorConfig,
    SelectorCandidateScore,
    load_dynamic_pilot_config,
)


ROOT = Path(__file__).parents[1]


def test_committed_config_enforces_equal_total_and_per_agent_budgets() -> None:
    config = load_dynamic_pilot_config(
        ROOT / "configs" / "hiddenbench-dynamic-pilot.json"
    )

    assert config.pilot_task_ids == (1, 5, 7)
    assert config.total_speeches == 60
    assert config.speeches_per_agent == 15
    assert config.total_speeches == 4 * config.speeches_per_agent
    assert config.selector_llm_calls == 0
    assert sum(config.selector.model_dump().values()) == pytest.approx(1.0)
    assert config.frozen_baseline.jsonl_sha256 == (
        "e3064a90e7fff6313821240828bc28afe"
        "ed44500be47c60eb6d195799672e4eb"
    )


def test_candidate_score_rejects_factor_above_one() -> None:
    with pytest.raises(ValidationError):
        SelectorCandidateScore(
            agent_id="agent-a",
            disagreement=1.1,
            undisclosed=0,
            related_discussion=0,
            response_due=0,
            waiting=0,
            weighted_total=0,
            remaining_quota=15,
            raw_waiting=1,
            latest_stance="West City",
            evidence_atom_ids=(),
            selected=False,
            tie_break_reason=None,
        )


def test_selector_config_rejects_weights_not_summing_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        DynamicSelectorConfig(
            disagreement=0.5,
            undisclosed=0.5,
            related_discussion=0.5,
            response_due=0,
            waiting=0,
        )
