from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.hiddenbench_atomic_disclosure import (
    REVEAL_ALL_HEADER,
    decompose_private_facts,
)
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_official_reveal_supplement import (
    OfficialRevealSupplementConfig,
    OfficialRevealSupplementRecord,
    expected_official_reveal_keys,
)
from mas_experiment.hiddenbench_reporting import _assert_no_secrets
from mas_experiment.hiddenbench_stability_domain import (
    assignment_fingerprint,
    derive_pair_seed,
)


class OfficialRevealSupplementGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: dict[str, bool]
    api_requests: int = Field(ge=0)
    passed: bool


def _run_items(record: OfficialRevealSupplementRecord) -> tuple[object, ...]:
    return (
        *record.run.hidden_pre_votes,
        *record.run.discussion_messages,
        *record.run.hidden_post_votes,
        *record.run.full_profile_votes,
    )


def _provider_matches(
    record: OfficialRevealSupplementRecord,
    config: OfficialRevealSupplementConfig,
) -> bool:
    for item in _run_items(record):
        metadata = item.provider_metadata
        if metadata.get("provider") == "stability-offline":
            if not (
                metadata.get("model") == "stability-offline-v1"
                and float(metadata.get("temperature", -1)) == 0
                and metadata.get("thinking") == "disabled"
            ):
                return False
        elif not (
            metadata.get("model") == config.provider.model
            and float(metadata.get("temperature", -1))
            == config.provider.temperature
            and metadata.get("thinking") == config.provider.thinking
        ):
            return False
    return True


def _global_reveal_timing(record: OfficialRevealSupplementRecord) -> bool:
    facts = decompose_private_facts(record.run.assignment)
    expected_ids = tuple(fact.fact_id for fact in facts)
    messages = record.run.discussion_messages
    if len(messages) != 60:
        return False
    for message in messages[:4]:
        if message.provider_metadata.get("global_reveal_round_one") is not True:
            return False
        if tuple(message.provider_metadata.get("appended_fact_ids", ())) != expected_ids:
            return False
        if f"[{REVEAL_ALL_HEADER}]" not in message.content:
            return False
        if not all(fact.text in message.content for fact in facts):
            return False
    for message in messages[4:]:
        if message.provider_metadata.get("global_reveal_round_one") is not False:
            return False
        if message.provider_metadata.get("appended_fact_ids", ()) not in ([], ()):
            return False
        if f"[{REVEAL_ALL_HEADER}]" in message.content:
            return False
    return True


def build_official_reveal_gate(
    config: OfficialRevealSupplementConfig,
    records: tuple[OfficialRevealSupplementRecord, ...],
    *,
    dataset_path: Path | None = None,
) -> OfficialRevealSupplementGate:
    expected = tuple(
        key.value for key in expected_official_reveal_keys(config)
    )
    keys = tuple(record.key.value for record in records)
    dataset_ok = True
    if dataset_path is not None:
        dataset_ok = (
            dataset_path.is_file()
            and hashlib.sha256(dataset_path.read_bytes()).hexdigest().casefold()
            == config.dataset_sha256.casefold()
        )
    pair_ok = all(
        record.pair_seed
        == derive_pair_seed(
            config.base_seed,
            task_id=record.key.task_id,
            repetition=record.key.repetition,
        )
        and record.assignment_fingerprint == assignment_fingerprint(record.run)
        for record in records
    )
    budget_ok = all(
        len(record.run.discussion_messages) == 60
        and Counter(
            message.agent_id for message in record.run.discussion_messages
        )
        == {agent_id: 15 for agent_id in AGENT_IDS}
        for record in records
    )
    provenance_ok = all(
        record.frozen_code_commit.casefold()
        == config.frozen_code_commit.casefold()
        and record.run_commit == record.run.code_commit
        for record in records
    )
    try:
        _assert_no_secrets(
            [record.model_dump(mode="json") for record in records]
        )
        secret_ok = True
    except ValueError:
        secret_ok = False
    checks = {
        "complete_run_matrix": (
            len(keys) == len(expected) and set(keys) == set(expected)
        ),
        "unique_run_keys": len(set(keys)) == len(keys),
        "deterministic_row_order": keys == expected,
        "task_and_dataset_hashes": dataset_ok
        and {record.key.task_id for record in records}.issubset(
            set(config.task_ids)
        ),
        "paired_seed_and_assignment": pair_ok,
        "message_budget": budget_ok,
        "official_global_reveal_timing": all(
            _global_reveal_timing(record) for record in records
        ),
        "provider_settings": all(
            _provider_matches(record, config) for record in records
        ),
        "code_commit_provenance": provenance_ok,
        "credential_leak_scan": secret_ok,
    }
    api_requests = sum(
        int(item.provider_metadata.get("api_requests", 0) or 0)
        for record in records
        for item in _run_items(record)
    )
    return OfficialRevealSupplementGate(
        checks=checks,
        api_requests=api_requests,
        passed=all(checks.values()),
    )

