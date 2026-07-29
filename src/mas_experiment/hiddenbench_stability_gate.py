from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mas_experiment.hiddenbench_ai_disclosure import (
    DisclosureAudit,
    validate_disclosure_evidence,
)
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_reporting import _assert_no_secrets
from mas_experiment.hiddenbench_stability_domain import (
    StabilityStudyConfig,
    StudyKey,
    StudyRunRecord,
    derive_pair_seed,
)
from mas_experiment.hiddenbench_stability_protocol import (
    expected_study_keys,
)


class StabilityGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: dict[str, bool]
    passed: bool


def _provider_items(record: StudyRunRecord) -> tuple[object, ...]:
    run = record.run
    return (
        *run.hidden_pre_votes,
        *run.discussion_messages,
        *run.hidden_post_votes,
        *run.full_profile_votes,
    )


def _contains_no_secrets(value: object) -> bool:
    try:
        _assert_no_secrets(value)
    except ValueError:
        return False
    return True


def build_stability_gate(
    config: StabilityStudyConfig,
    records: tuple[StudyRunRecord, ...],
    audits: tuple[DisclosureAudit, ...],
    *,
    dataset_path: Path | None = None,
    expected_keys: tuple[StudyKey, ...] | None = None,
) -> StabilityGate:
    expected = tuple(
        key.value
        for key in (
            expected_keys or expected_study_keys(config)
        )
    )
    run_keys = tuple(record.key.value for record in records)
    audit_keys = tuple(audit.study_key.value for audit in audits)

    dataset_ok = True
    if dataset_path is not None:
        dataset_ok = (
            dataset_path.is_file()
            and hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            == config.dataset_sha256
        )

    pairs: dict[tuple[int, int], list[StudyRunRecord]] = {}
    for record in records:
        pairs.setdefault(
            (record.key.task_id, record.key.repetition),
            [],
        ).append(record)
    expected_pairs = {
        (key.task_id, key.repetition)
        for key in (
            expected_keys or expected_study_keys(config)
        )
    }
    paired_ok = set(pairs) == expected_pairs
    for (task_id, repetition), pair_records in pairs.items():
        paired_ok &= len(pair_records) == len(config.conditions)
        paired_ok &= {
            item.key.condition for item in pair_records
        } == set(config.conditions)
        paired_ok &= len(
            {item.pair_seed for item in pair_records}
        ) == 1
        paired_ok &= len(
            {
                item.assignment_fingerprint
                for item in pair_records
            }
        ) == 1
        paired_ok &= all(
            item.pair_seed
            == derive_pair_seed(
                config.base_seed,
                task_id=task_id,
                repetition=repetition,
            )
            for item in pair_records
        )

    budget_ok = True
    visibility_ok = True
    provider_ok = True
    selector_ok = True
    for record in records:
        messages = record.run.discussion_messages
        budget_ok &= len(messages) == config.total_speeches
        budget_ok &= Counter(
            message.agent_id for message in messages
        ) == {
            agent_id: config.speeches_per_agent
            for agent_id in AGENT_IDS
        }
        visibility_ok &= all(
            message.turn_index == index
            and message.round_index == index // len(AGENT_IDS) + 1
            and message.visible_message_ids
            == tuple(
                previous.message_id
                for previous in messages[:index]
            )
            for index, message in enumerate(messages)
        )
        for item in _provider_items(record):
            metadata = item.provider_metadata
            if metadata.get("provider") == "stability-offline":
                provider_ok &= (
                    metadata.get("model") == "stability-offline-v1"
                    and float(metadata.get("temperature", -1)) == 0
                    and metadata.get("thinking") == "disabled"
                )
            else:
                provider_ok &= (
                    metadata.get("model") == config.provider.model
                    and float(metadata.get("temperature", -1))
                    == config.provider.temperature
                    and metadata.get("thinking")
                    == config.provider.thinking
                )
        selector_ok &= (
            record.run.provider_metadata.get(
                "selector_llm_calls",
                0,
            )
            == 0
        )

    records_by_key = {
        record.key.value: record for record in records
    }
    evidence_ok = len(audits) == len(expected)
    for audit in audits:
        record = records_by_key.get(audit.study_key.value)
        if record is None:
            evidence_ok = False
            continue
        try:
            validate_disclosure_evidence(
                record.run,
                audit.judgments,
            )
        except (ValueError, TypeError):
            evidence_ok = False

    checks = {
        "complete_run_matrix": (
            len(run_keys) == len(expected)
            and set(run_keys) == set(expected)
        ),
        "unique_run_keys": len(set(run_keys)) == len(run_keys),
        "complete_ai_audits": (
            len(audit_keys) == len(expected)
            and set(audit_keys) == set(expected)
        ),
        "unique_audit_keys": (
            len(set(audit_keys)) == len(audit_keys)
        ),
        "task_and_dataset_hashes": (
            dataset_ok
            and {
                record.key.task_id for record in records
            }.issubset(set(config.task_ids))
        ),
        "paired_seeds_and_assignments": paired_ok,
        "provider_settings": provider_ok,
        "equal_speech_budgets": budget_ok,
        "sequential_visibility": visibility_ok,
        "zero_selector_llm_calls": selector_ok,
        "valid_ai_evidence": evidence_ok,
        "credential_leak_scan": (
            _contains_no_secrets(
                [record.model_dump(mode="json") for record in records]
            )
            and _contains_no_secrets(
                [audit.model_dump(mode="json") for audit in audits]
            )
        ),
        "deterministic_row_order": (
            run_keys == expected and audit_keys == expected
        ),
    }
    return StabilityGate(
        checks=checks,
        passed=all(checks.values()),
    )
