from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

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


EVIDENCE_RULE_VERSION = "lexical-v1"
MIN_MATCHED_TERMS = 6
MIN_FACT_COVERAGE = 0.55
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


def fact_content_terms(text: str) -> tuple[str, ...]:
    terms = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    return tuple(
        dict.fromkeys(
            term
            for term in terms
            if term not in _STOPWORDS and len(term) > 1
        )
    )


def lexical_fact_match(fact: str, text: str) -> bool:
    fact_terms = set(fact_content_terms(fact))
    text_terms = set(fact_content_terms(text))
    if not fact_terms:
        return False
    matched = fact_terms & text_terms
    return (
        len(matched) >= MIN_MATCHED_TERMS
        and len(matched) / len(fact_terms) >= MIN_FACT_COVERAGE
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
    disclosed: dict[str, HiddenBenchMessage] = {}
    cross_uses: dict[str, tuple[HiddenBenchMessage, ...]] = {}
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
        if owner_disclosure is None:
            continue
        disclosed[fact] = owner_disclosure
        uses = tuple(
            message
            for message in messages
            if message.turn_index > owner_disclosure.turn_index
            and message.agent_id != owner
            and lexical_fact_match(fact, message.content)
        )
        if uses:
            cross_uses[fact] = uses
    return disclosed, cross_uses


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
