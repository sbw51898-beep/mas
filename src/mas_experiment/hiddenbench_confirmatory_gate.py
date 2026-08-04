from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.hiddenbench_atomic_disclosure import (
    AtomicDisclosureAudit,
    decompose_private_facts,
    validate_atomic_evidence,
)
from mas_experiment.hiddenbench_confirmatory_domain import ConfirmatoryStudyConfig
from mas_experiment.hiddenbench_confirmatory_study import (
    ConfirmatoryRunRecord,
    expected_confirmatory_keys,
)
from mas_experiment.hiddenbench_domain import AGENT_IDS
from mas_experiment.hiddenbench_reporting import _assert_no_secrets
from mas_experiment.hiddenbench_stability_domain import derive_pair_seed


class ConfirmatoryGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: dict[str, bool]
    api_requests: int = Field(ge=0)
    audit_api_requests: int = Field(ge=0)
    passed: bool


def _run_items(record: ConfirmatoryRunRecord) -> tuple[object, ...]:
    return (
        *record.run.hidden_pre_votes,
        *record.run.discussion_messages,
        *(
            vote
            for checkpoint in record.shadow_checkpoints
            for vote in checkpoint.votes
        ),
        *record.run.hidden_post_votes,
        *record.run.full_profile_votes,
    )


def _no_secrets(value: object) -> bool:
    try:
        _assert_no_secrets(value)
    except ValueError:
        return False
    return True


def _provider_matches(
    record: ConfirmatoryRunRecord,
    config: ConfirmatoryStudyConfig,
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


def _condition_shapes(records: tuple[ConfirmatoryRunRecord, ...]) -> bool:
    ok = True
    for record in records:
        condition = record.key.condition
        messages = record.run.discussion_messages
        if condition in {
            "fixed-60",
            "dynamic-60",
            "fixed-reveal-all",
            "dynamic-reveal-all",
        }:
            ok &= len(messages) == 60
        elif condition in {"structured-12", "fixed-12"}:
            ok &= len(messages) == 12
        else:
            ok &= len(messages) == 0
            ok &= len(record.run.hidden_post_votes) == 1
        if condition.startswith("dynamic"):
            ok &= Counter(message.agent_id for message in messages) == {
                agent_id: 15 for agent_id in AGENT_IDS
            }
            ok &= len(record.selection_events) == 60
            ok &= (
                record.run.provider_metadata.get("selector_llm_calls") == 0
            )
    return bool(ok)


def build_confirmatory_gate(
    config: ConfirmatoryStudyConfig,
    records: tuple[ConfirmatoryRunRecord, ...],
    audits: tuple[AtomicDisclosureAudit, ...],
    *,
    dataset_path: Path | None = None,
) -> ConfirmatoryGate:
    expected = tuple(key.value for key in expected_confirmatory_keys(config))
    run_keys = tuple(record.key.value for record in records)
    audit_keys = tuple(audit.study_key.value for audit in audits)

    dataset_ok = True
    if dataset_path is not None:
        dataset_ok = (
            dataset_path.is_file()
            and hashlib.sha256(dataset_path.read_bytes()).hexdigest().casefold()
            == config.dataset_sha256.casefold()
        )

    pairs: dict[tuple[int, int], list[ConfirmatoryRunRecord]] = {}
    for record in records:
        pairs.setdefault(
            (record.key.task_id, record.key.repetition), []
        ).append(record)
    pair_ok = len(pairs) == len(config.task_ids) * config.repetitions
    for (task_id, repetition), group in pairs.items():
        pair_ok &= len(group) == len(config.conditions)
        pair_ok &= {item.key.condition for item in group} == set(
            config.conditions
        )
        pair_ok &= len({item.pair_seed for item in group}) == 1
        pair_ok &= len({item.assignment_fingerprint for item in group}) == 1
        pair_ok &= all(
            item.pair_seed
            == derive_pair_seed(
                config.base_seed,
                task_id=task_id,
                repetition=repetition,
            )
            for item in group
        )

    shadow_ok = all(
        (
            len(record.shadow_checkpoints) == 15
            and tuple(
                checkpoint.round_index
                for checkpoint in record.shadow_checkpoints
            )
            == tuple(range(1, 16))
        )
        if record.key.condition == "fixed-60"
        else not record.shadow_checkpoints
        for record in records
    )

    records_by_key = {record.key.value: record for record in records}
    evidence_ok = len(audits) == len(expected)
    reveal_ok = True
    for audit in audits:
        record = records_by_key.get(audit.study_key.value)
        if record is None:
            evidence_ok = False
            continue
        facts = decompose_private_facts(record.run.assignment)
        evidence_ok &= audit.facts == facts
        try:
            validate_atomic_evidence(record.run, facts, audit.judgments)
        except (ValueError, TypeError):
            evidence_ok = False
        recomputed_rate = (
            sum(item.disclosed for item in audit.judgments)
            / len(audit.judgments)
        )
        evidence_ok &= abs(recomputed_rate - audit.disclosure_rate) < 1e-12
        if audit.study_key.condition.endswith("reveal-all"):
            reveal_ok &= audit.disclosure_rate == 1.0
            reveal_ok &= all(item.disclosed for item in audit.judgments)

    run_api_requests = sum(
        int(item.provider_metadata.get("api_requests", 0) or 0)
        for record in records
        for item in _run_items(record)
    )
    audit_api_requests = sum(
        int(audit.provider_metadata.get("api_requests", 0) or 0)
        for audit in audits
    )
    audit_commits = {
        str(audit.provider_metadata.get("audit_code_commit", ""))
        for audit in audits
    }
    checks = {
        "complete_run_matrix": (
            len(run_keys) == len(expected) and set(run_keys) == set(expected)
        ),
        "unique_run_keys": len(set(run_keys)) == len(run_keys),
        "complete_atomic_audits": (
            len(audit_keys) == len(expected) and set(audit_keys) == set(expected)
        ),
        "unique_audit_keys": len(set(audit_keys)) == len(audit_keys),
        "deterministic_row_order": run_keys == expected and audit_keys == expected,
        "task_and_dataset_hashes": dataset_ok
        and {record.key.task_id for record in records}.issubset(
            set(config.task_ids)
        ),
        "paired_seeds_and_assignments": bool(pair_ok),
        "condition_shapes_and_budgets": _condition_shapes(records),
        "complete_shadow_checkpoints": shadow_ok,
        "reveal_all_is_complete": bool(reveal_ok),
        "valid_atomic_evidence": bool(evidence_ok),
        "provider_settings": all(
            _provider_matches(record, config) for record in records
        ),
        "code_commit_provenance": all(
            record.frozen_code_commit == config.frozen_code_commit
            and record.run_commit == record.run.code_commit
            for record in records
        ),
        "audit_code_provenance": (
            len(audit_commits) == 1
            and all(
                re.fullmatch(r"[0-9a-f]{40}", commit) is not None
                for commit in audit_commits
            )
        ),
        "credential_leak_scan": _no_secrets(
            [record.model_dump(mode="json") for record in records]
        )
        and _no_secrets(
            [audit.model_dump(mode="json") for audit in audits]
        ),
    }
    return ConfirmatoryGate(
        checks=checks,
        api_requests=run_api_requests,
        audit_api_requests=audit_api_requests,
        passed=all(checks.values()),
    )
