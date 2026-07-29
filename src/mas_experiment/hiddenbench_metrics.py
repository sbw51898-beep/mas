from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
    HiddenBenchMetrics,
    HiddenBenchRawRun,
    HiddenBenchRun,
    HiddenBenchVote,
    MastCandidate,
)


EVIDENCE_RULE_VERSION = "lexical-semantic-v2"
MIN_MATCHED_TERMS = 6
MIN_FACT_COVERAGE = 0.55
MIN_RELAXED_MATCHED_TERMS = 4
MIN_RELAXED_FACT_COVERAGE = 0.30
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
}
_NEGATION_MARKERS = {
    "avoid",
    "cannot",
    "contaminated",
    "eliminate",
    "not ",
    "reject",
    "unsafe",
}
_ENTITY_PATTERN = re.compile(
    r"\b(station|hospital|restaurant|lab|option|data\s+center)"
    r"\s+([a-z0-9]+)\b",
    flags=re.IGNORECASE,
)
_EVIDENCE_GENERIC_TERMS = {
    "agent",
    "based",
    "center",
    "choice",
    "choose",
    "community",
    "confirm",
    "crew",
    "data",
    "fact",
    "field",
    "given",
    "hospital",
    "hotline",
    "information",
    "inspect",
    "lab",
    "maintenance",
    "morning",
    "option",
    "recommend",
    "repair",
    "report",
    "reports",
    "restaurant",
    "station",
    "team",
}
_INVALID_ENTITY_VALUES = {
    "are",
    "has",
    "have",
    "is",
    "may",
    "should",
    "was",
    "were",
    "will",
}
_CONCEPT_STEMS = {
    "access",
    "avail",
    "block",
    "contamin",
    "expos",
    "fail",
    "hazard",
    "offline",
    "open",
    "outag",
    "power",
    "risk",
    "safe",
    "toxin",
    "unsafe",
}


class RuleDisclosureEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact: str
    owner_agent_id: str
    disclosed: bool
    evidence_message_ids: tuple[str, ...]
    cross_agent_use_message_ids: tuple[str, ...]
    rule_version: str


def _light_stem(term: str) -> str:
    aliases = {
        "batteries": "battery",
        "contaminated": "contamin",
        "contamination": "contamin",
        "depleted": "deplet",
        "discourage": "discourag",
        "discourages": "discourag",
        "discouraging": "discourag",
        "exposed": "expos",
        "exposure": "expos",
        "expired": "expir",
        "expires": "expir",
        "expiring": "expir",
        "failed": "fail",
        "failure": "fail",
        "failures": "fail",
        "functioning": "function",
        "operational": "function",
        "outage": "outag",
        "outages": "outag",
        "possible": "uncertain",
        "potential": "uncertain",
        "innovation": "innov",
        "innovative": "innov",
        "safety": "safe",
        "suggesting": "uncertain",
        "toxins": "toxin",
    }
    if term in aliases:
        return aliases[term]
    for suffix in ("ingly", "edly", "ation", "ments", "ment", "ing", "ied", "ed"):
        if term.endswith(suffix) and len(term) - len(suffix) >= 4:
            return term[: -len(suffix)]
    if term.endswith("ies") and len(term) > 5:
        return f"{term[:-3]}y"
    if term.endswith("s") and len(term) > 4:
        return term[:-1]
    return term


def _semantic_concepts(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.casefold())
    concepts: set[str] = set()
    contamination_absent = bool(
        re.search(
            r"\b(?:no|without)\s+(?:signs?\s+of\s+)?contamin"
            r"|\bavoid\w*\s+(?:all\s+)?contamin",
            normalized,
        )
    )
    if contamination_absent:
        concepts.add("contamination-absent")
    elif re.search(r"\b(?:contamin\w*|toxin\w*|toxic)\b", normalized):
        concepts.add("contamination-present")

    if re.search(r"\b(?:safe|safety|confirmed safe)\b", normalized):
        concepts.add("safe")
    if re.search(r"\b(?:unsafe|hazard\w*|danger\w*)\b", normalized):
        concepts.add("unsafe")

    if re.search(
        r"\b(?:power outage|power cut\w*|no power|without power|offline)\b",
        normalized,
    ) or re.search(r"\bbatter\w*\b.*\bdeplet\w*\b", normalized):
        concepts.add("power-unavailable")
    elif re.search(r"\b(?:has|reliable|available)\s+(?:solar\s+)?power\b", normalized):
        concepts.add("power-available")

    if re.search(r"\b(?:expos\w*|ventilat\w*)\b", normalized):
        concepts.add("air-exposure")
    if re.search(r"\b(?:possible|potential|suggest\w*|risk)\b", normalized):
        concepts.add("uncertain")
    if re.search(
        r"\b(?:block\w*|stuck|closed|jammed|unreachable|halted)\b",
        normalized,
    ):
        concepts.add("access-blocked")
    if re.search(r"\b(?:open|passable|accessible|cleared)\b", normalized):
        concepts.add("access-open")
    if re.search(r"\b(?:fail\w*|non functional|not functional)\b", normalized):
        concepts.add("system-failed")
    if re.search(r"\b(?:work\w*|function\w*|operational|normal)\b", normalized):
        concepts.add("system-working")
    if re.search(r"\bdiscourag\w*\b.*\binnov\w*\b", normalized):
        concepts.add("innovation-discouraged")
    if re.search(r"\bnorovirus\b.*\boutbreak\b|\boutbreak\b.*\bnorovirus\b", normalized):
        concepts.add("norovirus-outbreak")
    if re.search(
        r"\b(?:resign\w*|los\w*|loss)\b.*\b(?:engineer|manager|staff|personnel)\b"
        r"|\b(?:engineer|manager|staff|personnel)\b.*\b(?:resign\w*|los\w*|loss)\b",
        normalized,
    ):
        concepts.add("personnel-loss")
    if re.search(r"\b(?:expir\w*|cannot be renewed|nonrenewable)\b", normalized):
        concepts.add("expiration")
    if re.search(r"\bcold\s+menu\b", normalized):
        concepts.add("cold-menu")
    return concepts


def _entity_anchors(text: str) -> set[str]:
    return {
        match.group(2).casefold()
        for match in _ENTITY_PATTERN.finditer(text)
        if match.group(2).casefold() not in _INVALID_ENTITY_VALUES
    }


def _entity_mentions(text: str) -> set[tuple[str, str]]:
    return {
        (
            re.sub(r"\s+", " ", match.group(1).casefold()),
            match.group(2).casefold(),
        )
        for match in _ENTITY_PATTERN.finditer(text)
        if match.group(2).casefold() not in _INVALID_ENTITY_VALUES
    }


def _entities_conflict(fact: str, text: str) -> bool:
    fact_entities = _entity_mentions(fact)
    text_entities = _entity_mentions(text)
    return bool(
        fact_entities
        and text_entities
        and not fact_entities.intersection(text_entities)
        and not _has_short_entity_reference(fact_entities, text)
    )


def _has_short_entity_reference(
    fact_entities: set[tuple[str, str]],
    text: str,
) -> bool:
    text_casefold = text.casefold()
    for _, value in fact_entities:
        if len(value) > 1 and re.search(
            rf"\b{re.escape(value)}\b",
            text_casefold,
        ):
            return True
        if len(value) == 1 and re.search(
            rf"\b{re.escape(value)}(?:['’]s)\b",
            text_casefold,
        ):
            return True
    return False


def _evidence_stems(text: str) -> set[str]:
    entities = _entity_anchors(text)
    return {
        stem
        for term in fact_content_terms(text)
        if term not in _EVIDENCE_GENERIC_TERMS and term not in entities
        for stem in (_light_stem(term),)
        if stem not in _CONCEPT_STEMS
    }


def _claims_conflict(
    fact_concepts: set[str],
    text_concepts: set[str],
) -> bool:
    incompatible_pairs = (
        ("contamination-absent", "contamination-present"),
        ("safe", "unsafe"),
        ("power-unavailable", "power-available"),
        ("access-blocked", "access-open"),
        ("system-failed", "system-working"),
    )
    return any(
        fact_value in fact_concepts
        and text_value in text_concepts
        and fact_value not in text_concepts
        for fact_value, text_value in incompatible_pairs
    )


def fact_content_terms(text: str) -> tuple[str, ...]:
    terms = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    return tuple(
        dict.fromkeys(
            term
            for term in terms
            if term not in _STOPWORDS and len(term) > 1
        )
    )


def _entity_is_mentioned(fact: str, text: str) -> bool:
    fact_entities = _entity_mentions(fact)
    return bool(
        fact_entities.intersection(_entity_mentions(text))
        or _has_short_entity_reference(fact_entities, text)
    )


def _hybrid_fragment_match(
    fact: str,
    text: str,
    *,
    minimum_stems: int,
    minimum_coverage: float,
) -> bool:
    if _entities_conflict(fact, text):
        return False
    fact_concepts = _semantic_concepts(fact)
    text_concepts = _semantic_concepts(text)
    if _claims_conflict(fact_concepts, text_concepts):
        return False

    fact_stems = _evidence_stems(fact)
    text_stems = _evidence_stems(text)
    shared_stems = fact_stems & text_stems
    shared_concepts = fact_concepts & text_concepts
    if shared_concepts and shared_stems:
        return True
    if _entity_is_mentioned(fact, text) and (
        shared_concepts or len(shared_stems) >= 3
    ):
        return True
    return (
        len(shared_stems) >= minimum_stems
        and len(shared_stems) / max(len(fact_stems), 1)
        >= minimum_coverage
    )


def _fact_atoms(fact: str) -> tuple[str, ...]:
    atoms: list[str] = []
    for line in fact.splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if not stripped or stripped.endswith(":"):
            continue
        atoms.extend(
            fragment.strip()
            for fragment in re.split(r"(?<=[.!?])\s+", stripped)
            if fragment.strip()
        )
    return tuple(atoms)


def _criterion_claim_match(fact: str, text: str) -> bool:
    current_entity: str | None = None
    claims: list[tuple[str, str, str]] = []
    for raw_line in fact.splitlines():
        line = raw_line.strip().lstrip("-*").strip()
        if line.endswith(":") and not line.startswith("("):
            current_entity = line[:-1].strip().casefold()
            continue
        match = re.fullmatch(r"\(([a-z])\)\s*([ny])", line, re.IGNORECASE)
        if current_entity and match:
            claims.append(
                (
                    current_entity,
                    match.group(1).casefold(),
                    match.group(2).casefold(),
                )
            )
    if not claims:
        return False

    text_casefold = text.casefold()
    negative = bool(re.search(r"\b(?:fail\w*|not meet\w*)\b", text_casefold))
    positive = bool(re.search(r"\b(?:meet\w*|satisf\w*|pass\w*)\b", text_casefold))
    for entity, criterion, value in claims:
        if entity not in text_casefold:
            continue
        if not re.search(rf"\({re.escape(criterion)}\)", text_casefold):
            continue
        if (value == "n" and negative) or (value == "y" and positive):
            return True
    return False


def lexical_fact_match(fact: str, text: str) -> bool:
    fact_terms = set(fact_content_terms(fact))
    text_terms = set(fact_content_terms(text))
    if not fact_terms:
        return False
    if _entities_conflict(fact, text):
        return False
    if _claims_conflict(_semantic_concepts(fact), _semantic_concepts(text)):
        return False
    matched = fact_terms & text_terms
    if (
        len(matched) >= MIN_MATCHED_TERMS
        and len(matched) / len(fact_terms) >= MIN_FACT_COVERAGE
    ):
        return True

    if _criterion_claim_match(fact, text):
        return True
    if _hybrid_fragment_match(
        fact,
        text,
        minimum_stems=MIN_RELAXED_MATCHED_TERMS,
        minimum_coverage=MIN_RELAXED_FACT_COVERAGE,
    ):
        return True
    return any(
        _hybrid_fragment_match(
            atom,
            text,
            minimum_stems=3,
            minimum_coverage=0.30,
        )
        for atom in _fact_atoms(fact)
    )


def _validate_votes(votes: tuple[HiddenBenchVote, ...]) -> None:
    if len(votes) != len(AGENT_IDS):
        raise ValueError("each HiddenBench vote phase requires four votes")
    if {vote.agent_id for vote in votes} != set(AGENT_IDS):
        raise ValueError("each HiddenBench agent must vote exactly once")


def _accuracy(
    votes: tuple[HiddenBenchVote, ...],
    correct_answer: str,
) -> float:
    return sum(vote.vote == correct_answer for vote in votes) / len(votes)


def _majority_correct(
    votes: tuple[HiddenBenchVote, ...],
    correct_answer: str,
) -> bool:
    return (
        sum(vote.vote == correct_answer for vote in votes)
        > len(votes) / 2
    )


def _unanimous(votes: tuple[HiddenBenchVote, ...]) -> bool:
    return len({vote.vote for vote in votes}) == 1


def _post_vote_by_agent(
    votes: tuple[HiddenBenchVote, ...],
) -> dict[str, HiddenBenchVote]:
    return {vote.agent_id: vote for vote in votes}


def _information_flow(
    assignment: HiddenBenchAssignment,
    messages: tuple[HiddenBenchMessage, ...],
) -> tuple[
    dict[str, HiddenBenchMessage],
    dict[str, tuple[HiddenBenchMessage, ...]],
]:
    evidence = _rule_disclosure_evidence(assignment, messages)
    messages_by_id = {
        message.message_id: message for message in messages
    }
    disclosed: dict[str, HiddenBenchMessage] = {}
    cross_uses: dict[str, tuple[HiddenBenchMessage, ...]] = {}
    for fact, item in evidence.items():
        if item.evidence_message_ids:
            disclosed[fact] = messages_by_id[
                item.evidence_message_ids[0]
            ]
        if item.cross_agent_use_message_ids:
            cross_uses[fact] = tuple(
                messages_by_id[message_id]
                for message_id in item.cross_agent_use_message_ids
            )
    return disclosed, cross_uses


def _rule_disclosure_evidence(
    assignment: HiddenBenchAssignment,
    messages: tuple[HiddenBenchMessage, ...],
) -> dict[str, RuleDisclosureEvidence]:
    evidence: dict[str, RuleDisclosureEvidence] = {}
    for owner, fact in assignment.private_information.items():
        owner_disclosure = next(
            (
                message
                for message in messages
                if message.agent_id == owner
                and lexical_fact_match(fact, message.content)
            ),
            None,
        )
        uses = (
            tuple(
                message
                for message in messages
                if message.turn_index > owner_disclosure.turn_index
                and message.agent_id != owner
                and lexical_fact_match(fact, message.content)
            )
            if owner_disclosure is not None
            else ()
        )
        evidence[fact] = RuleDisclosureEvidence(
            fact=fact,
            owner_agent_id=owner,
            disclosed=owner_disclosure is not None,
            evidence_message_ids=(
                (owner_disclosure.message_id,)
                if owner_disclosure is not None
                else ()
            ),
            cross_agent_use_message_ids=tuple(
                message.message_id for message in uses
            ),
            rule_version=EVIDENCE_RULE_VERSION,
        )
    return evidence


def rule_disclosure_evidence(
    run: HiddenBenchRawRun,
) -> dict[str, RuleDisclosureEvidence]:
    return _rule_disclosure_evidence(
        run.assignment,
        run.discussion_messages,
    )


def _fm24_candidates(
    assignment: HiddenBenchAssignment,
    messages: tuple[HiddenBenchMessage, ...],
    disclosed: Mapping[str, HiddenBenchMessage],
) -> list[MastCandidate]:
    candidates: list[MastCandidate] = []
    for owner, fact in assignment.private_information.items():
        if fact in disclosed:
            continue
        owner_messages = tuple(
            message for message in messages if message.agent_id == owner
        )
        candidates.append(
            MastCandidate(
                failure_mode="FM-2.4",
                agent_id=owner,
                owner_agent_id=owner,
                fact=fact,
                evidence_message_ids=tuple(
                    message.message_id for message in owner_messages
                ),
                evidence_text=tuple(
                    message.content for message in owner_messages
                )
                or ("No public discussion message was available.",),
                rule_version=EVIDENCE_RULE_VERSION,
            )
        )
    return candidates


def _fm25_candidates(
    assignment: HiddenBenchAssignment,
    messages: tuple[HiddenBenchMessage, ...],
    post_votes: tuple[HiddenBenchVote, ...],
    disclosed: Mapping[str, HiddenBenchMessage],
) -> list[MastCandidate]:
    candidates: list[MastCandidate] = []
    post_by_agent = _post_vote_by_agent(post_votes)
    for owner, fact in assignment.private_information.items():
        disclosure = disclosed.get(fact)
        if disclosure is None:
            continue
        for agent_id in AGENT_IDS:
            if agent_id == owner:
                continue
            later_messages = tuple(
                message
                for message in messages
                if message.agent_id == agent_id
                and message.turn_index > disclosure.turn_index
            )
            post_vote = post_by_agent[agent_id]
            used = any(
                lexical_fact_match(fact, message.content)
                for message in later_messages
            ) or lexical_fact_match(fact, post_vote.rationale)
            if used:
                continue
            candidates.append(
                MastCandidate(
                    failure_mode="FM-2.5",
                    agent_id=agent_id,
                    owner_agent_id=owner,
                    fact=fact,
                    evidence_message_ids=(disclosure.message_id,),
                    evidence_text=(
                        f"Fact disclosed by {owner}: {fact}",
                        f"Post rationale by {agent_id}: "
                        f"{post_vote.rationale}",
                    ),
                    rule_version=EVIDENCE_RULE_VERSION,
                )
            )
    return candidates


def _fm26_candidates(
    task: HiddenBenchTask,
    votes: tuple[HiddenBenchVote, ...],
) -> list[MastCandidate]:
    candidates: list[MastCandidate] = []
    for vote in votes:
        rationale_casefold = vote.rationale.casefold()
        if any(marker in rationale_casefold for marker in _NEGATION_MARKERS):
            continue
        mentioned = [
            answer
            for answer in task.possible_answers
            if answer.casefold() in rationale_casefold
        ]
        if len(mentioned) != 1 or mentioned[0] == vote.vote:
            continue
        candidates.append(
            MastCandidate(
                failure_mode="FM-2.6",
                agent_id=vote.agent_id,
                evidence_text=(
                    vote.rationale,
                    f"Recorded vote: {vote.vote}",
                ),
                rule_version=EVIDENCE_RULE_VERSION,
            )
        )
    return candidates


def _plain_usage(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def compute_hiddenbench_metrics(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    pre_votes: tuple[HiddenBenchVote, ...],
    messages: tuple[HiddenBenchMessage, ...],
    post_votes: tuple[HiddenBenchVote, ...],
    full_votes: tuple[HiddenBenchVote, ...],
    *,
    provider_metadata: Mapping[str, Any] | None = None,
) -> tuple[HiddenBenchMetrics, tuple[MastCandidate, ...]]:
    for votes in (pre_votes, post_votes, full_votes):
        _validate_votes(votes)

    y_pre = _accuracy(pre_votes, task.correct_answer)
    y_post = _accuracy(post_votes, task.correct_answer)
    y_full = _accuracy(full_votes, task.correct_answer)
    disclosed, cross_uses = _information_flow(assignment, messages)
    candidates = [
        *_fm24_candidates(assignment, messages, disclosed),
        *_fm25_candidates(
            assignment,
            messages,
            post_votes,
            disclosed,
        ),
        *_fm26_candidates(
            task,
            (*pre_votes, *post_votes, *full_votes),
        ),
    ]
    metadata = dict(provider_metadata or {})
    metrics = HiddenBenchMetrics(
        y_pre_average=y_pre,
        y_post_average=y_post,
        y_full_average=y_full,
        integration_gain=y_post - y_pre,
        full_profile_gap=y_post - y_full,
        pre_majority_correct=_majority_correct(
            pre_votes,
            task.correct_answer,
        ),
        post_majority_correct=_majority_correct(
            post_votes,
            task.correct_answer,
        ),
        full_majority_correct=_majority_correct(
            full_votes,
            task.correct_answer,
        ),
        pre_unanimous=_unanimous(pre_votes),
        post_unanimous=_unanimous(post_votes),
        full_unanimous=_unanimous(full_votes),
        consensus_round=None,
        private_fact_disclosure_rate=(
            len(disclosed) / len(assignment.private_information)
        ),
        cross_agent_use_rate=(
            len(cross_uses) / len(assignment.private_information)
        ),
        api_requests=int(metadata.get("api_requests", 0) or 0),
        repair_requests=int(metadata.get("repair_requests", 0) or 0),
        usage=_plain_usage(metadata.get("usage")),
    )
    return metrics, tuple(candidates)


def score_hiddenbench_run(raw_run: HiddenBenchRawRun) -> HiddenBenchRun:
    metrics, candidates = compute_hiddenbench_metrics(
        raw_run.task,
        raw_run.assignment,
        raw_run.hidden_pre_votes,
        raw_run.discussion_messages,
        raw_run.hidden_post_votes,
        raw_run.full_profile_votes,
        provider_metadata=raw_run.provider_metadata,
    )
    return HiddenBenchRun.model_validate(
        {
            **raw_run.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
            "mast_candidates": [
                candidate.model_dump(mode="json")
                for candidate in candidates
            ],
        }
    )
