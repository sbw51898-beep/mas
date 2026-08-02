from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BlindReviewMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str
    turn_index: int
    content: str


class BlindReviewCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    blind_id: str
    study_key: str
    task_id: int
    condition: Literal["fixed", "dynamic"]
    fact_id: str
    owner_agent_id: str
    fact: str
    owner_messages: tuple[BlindReviewMessage, ...]
    ai_disclosed: bool
    rule_disclosed: bool

    @property
    def agreement_stratum(self) -> str:
        label = "disclosed" if self.ai_disclosed else "undisclosed"
        return f"agree-{label}:task-{self.task_id}:{self.condition}"

    def blind_payload(self) -> dict[str, Any]:
        return {
            "blind_id": self.blind_id,
            "fact": self.fact,
            "owner_agent_id": self.owner_agent_id,
            "owner_messages": [
                item.model_dump(mode="json")
                for item in self.owner_messages
            ],
        }


class ReviewJudgment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    blind_id: str
    disclosed: bool
    evidence_message_ids: tuple[str, ...] = ()
    evidence_quote: str = ""
    reason: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    reviewer_id: str = "unassigned"


class WeightedReviewMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    population_size: int
    reviewed_size: int
    estimated_tp: float
    estimated_fp: float
    estimated_tn: float
    estimated_fn: float
    ai_human_agreement: float
    ai_precision: float
    ai_recall: float
    revised_disclosure_rate: float


def append_artifact_label(base: Path, label: str) -> Path:
    return base.with_name(f"{base.name}.{label}")


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def parse_human_disclosed(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes", "y", "是"}:
        return True
    if normalized in {"false", "0", "no", "n", "否"}:
        return False
    raise ValueError(
        "human_disclosed requires an explicit true/false or 是/否 label"
    )


def build_blind_queue_row(case: BlindReviewCase) -> dict[str, str]:
    payload = case.blind_payload()
    return {
        "blind_id": str(payload["blind_id"]),
        "fact": str(payload["fact"]),
        "owner_agent_id": str(payload["owner_agent_id"]),
        "owner_messages_json": json.dumps(
            payload["owner_messages"],
            ensure_ascii=False,
        ),
        "human_disclosed": "",
        "human_evidence_message_ids": "",
        "human_evidence_quote": "",
        "human_reason": "",
        "human_reviewer_id": "",
    }


def validate_review_judgment_evidence(
    case: BlindReviewCase,
    judgment: ReviewJudgment,
) -> None:
    if judgment.blind_id != case.blind_id:
        raise ValueError("review judgment blind ID does not match case")
    if not judgment.disclosed:
        if judgment.evidence_message_ids or judgment.evidence_quote:
            raise ValueError(
                "undisclosed review evidence fields must be empty"
            )
        return
    if not judgment.evidence_message_ids or not judgment.evidence_quote:
        raise ValueError("disclosed review requires evidence")
    messages = {
        item.message_id: item.content
        for item in case.owner_messages
    }
    referenced = []
    for message_id in judgment.evidence_message_ids:
        if message_id not in messages:
            raise ValueError(
                "review evidence must reference an owner-authored message"
            )
        referenced.append(messages[message_id])
    if not any(judgment.evidence_quote in text for text in referenced):
        raise ValueError(
            "review evidence quote must be an exact substring"
        )


def make_blind_id(*, seed: int, study_key: str, fact_id: str) -> str:
    digest = hashlib.sha256(
        f"{seed}|{study_key}|{fact_id}".encode("utf-8")
    ).hexdigest()
    return f"BR-{digest[:12].upper()}"


def _allocate_proportional(
    group_sizes: dict[str, int],
    sample_size: int,
) -> dict[str, int]:
    total = sum(group_sizes.values())
    if sample_size >= total:
        return dict(group_sizes)
    if sample_size < len(group_sizes):
        raise ValueError(
            "sample size must cover every non-empty task-condition stratum"
        )

    raw = {
        key: sample_size * size / total
        for key, size in group_sizes.items()
    }
    allocation = {
        key: min(size, max(1, math.floor(raw[key])))
        for key, size in group_sizes.items()
    }
    while sum(allocation.values()) < sample_size:
        candidates = [
            key
            for key, size in group_sizes.items()
            if allocation[key] < size
        ]
        key = max(
            candidates,
            key=lambda item: (
                raw[item] - allocation[item],
                group_sizes[item],
                item,
            ),
        )
        allocation[key] += 1
    while sum(allocation.values()) > sample_size:
        candidates = [
            key
            for key, count in allocation.items()
            if count > 1
        ]
        key = min(
            candidates,
            key=lambda item: (
                raw[item] - allocation[item],
                -group_sizes[item],
                item,
            ),
        )
        allocation[key] -= 1
    return allocation


def select_blind_review_sample(
    population: tuple[BlindReviewCase, ...],
    *,
    agreement_sample_per_ai_label: int,
    seed: int,
) -> tuple[BlindReviewCase, ...]:
    selected = [
        item
        for item in population
        if item.ai_disclosed != item.rule_disclosed
    ]
    rng = random.Random(seed)

    for ai_label in (True, False):
        groups: dict[str, list[BlindReviewCase]] = defaultdict(list)
        for item in population:
            if (
                item.ai_disclosed == item.rule_disclosed
                and item.ai_disclosed is ai_label
            ):
                groups[item.agreement_stratum].append(item)
        allocation = _allocate_proportional(
            {key: len(items) for key, items in groups.items()},
            agreement_sample_per_ai_label,
        )
        for key in sorted(groups):
            items = sorted(groups[key], key=lambda item: item.blind_id)
            group_rng = random.Random(f"{seed}|{key}")
            group_rng.shuffle(items)
            selected.extend(items[: allocation[key]])

    rng.shuffle(selected)
    return tuple(selected)


def compute_weighted_review_metrics(
    population: tuple[BlindReviewCase, ...],
    reviewed: tuple[ReviewJudgment, ...],
) -> WeightedReviewMetrics:
    case_by_id = {item.blind_id: item for item in population}
    judgment_by_id = {item.blind_id: item for item in reviewed}
    if len(case_by_id) != len(population):
        raise ValueError("population blind IDs must be unique")
    if len(judgment_by_id) != len(reviewed):
        raise ValueError("review judgments must have unique blind IDs")
    unknown = set(judgment_by_id) - set(case_by_id)
    if unknown:
        raise ValueError(f"unknown blind review IDs: {sorted(unknown)}")

    disagreement_ids = {
        item.blind_id
        for item in population
        if item.ai_disclosed != item.rule_disclosed
    }
    missing_disagreements = disagreement_ids - set(judgment_by_id)
    if missing_disagreements:
        raise ValueError(
            "all AI-rule disagreements require review: "
            f"{sorted(missing_disagreements)}"
        )

    population_by_stratum: dict[str, list[BlindReviewCase]] = defaultdict(list)
    reviewed_by_stratum: dict[str, list[BlindReviewCase]] = defaultdict(list)
    for item in population:
        if item.ai_disclosed == item.rule_disclosed:
            population_by_stratum[item.agreement_stratum].append(item)
    for blind_id in judgment_by_id:
        item = case_by_id[blind_id]
        if item.ai_disclosed == item.rule_disclosed:
            reviewed_by_stratum[item.agreement_stratum].append(item)

    weights: dict[str, float] = {}
    for blind_id in disagreement_ids:
        weights[blind_id] = 1.0
    for stratum, items in population_by_stratum.items():
        reviewed_items = reviewed_by_stratum.get(stratum, [])
        if not reviewed_items:
            raise ValueError(f"agreement stratum has no review sample: {stratum}")
        weight = len(items) / len(reviewed_items)
        for item in reviewed_items:
            weights[item.blind_id] = weight

    tp = fp = tn = fn = 0.0
    for blind_id, judgment in judgment_by_id.items():
        case = case_by_id[blind_id]
        weight = weights[blind_id]
        if case.ai_disclosed and judgment.disclosed:
            tp += weight
        elif case.ai_disclosed and not judgment.disclosed:
            fp += weight
        elif not case.ai_disclosed and judgment.disclosed:
            fn += weight
        else:
            tn += weight

    estimated_total = tp + fp + tn + fn
    if not math.isclose(estimated_total, len(population)):
        raise ValueError(
            f"review weights estimate {estimated_total}, "
            f"expected {len(population)}"
        )
    return WeightedReviewMetrics(
        population_size=len(population),
        reviewed_size=len(reviewed),
        estimated_tp=tp,
        estimated_fp=fp,
        estimated_tn=tn,
        estimated_fn=fn,
        ai_human_agreement=(tp + tn) / estimated_total,
        ai_precision=tp / (tp + fp),
        ai_recall=tp / (tp + fn),
        revised_disclosure_rate=(tp + fn) / estimated_total,
    )
