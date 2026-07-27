from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from mas_experiment.domain import Message, Question


@dataclass(frozen=True)
class InformationMeasures:
    information_coverage: float
    cross_agent_input_use_rate: float
    ignored_input_candidate_rate: float


def keyword_variants(keyword: str) -> tuple[str, ...]:
    variants = [keyword]
    if "_" in keyword:
        suffix = keyword.rsplit("_", maxsplit=1)[1]
        if "=" in suffix:
            variants.append(suffix)
    return tuple(dict.fromkeys(variants))


def keyword_present(text: str, keyword: str) -> bool:
    normalized = text.casefold()
    return any(
        variant.casefold() in normalized
        for variant in keyword_variants(keyword)
    )


def contains_any_keyword(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword_present(text, keyword) for keyword in keywords)


def calculate_information_measures(
    question: Question,
    messages: Sequence[Message],
    *,
    initial_message_count: int,
) -> InformationMeasures:
    keyword_owners = tuple(
        (agent_id, keyword)
        for agent_id, keywords in question.information_keywords.items()
        for keyword in keywords
        if keyword
    )
    follow_ups = tuple(messages[initial_message_count:])
    covered = sum(
        any(
            message.speaker == owner
            and keyword_present(message.content, keyword)
            for message in follow_ups
        )
        for owner, keyword in keyword_owners
    )
    coverage = covered / len(keyword_owners) if keyword_owners else 0.0

    message_by_id = {message.message_id: message for message in messages}
    cross_agent_uses = 0
    eligible_for_ignored_review = 0
    ignored_candidates = 0
    for message in follow_ups:
        foreign_keywords = tuple(
            (owner, keyword)
            for owner, keyword in keyword_owners
            if owner != message.speaker
        )

        visible_message_objects = tuple(
            message_by_id[message_id]
            for message_id in message.visible_history_ids
            if message_id in message_by_id
        )
        available_foreign_keywords = tuple(
            keyword
            for owner, keyword in foreign_keywords
            if any(
                visible.speaker == owner
                and keyword_present(visible.content, keyword)
                for visible in visible_message_objects
            )
        )
        uses_foreign_input = contains_any_keyword(
            message.content,
            available_foreign_keywords,
        )
        cross_agent_uses += uses_foreign_input
        foreign_input_available = bool(available_foreign_keywords)
        if foreign_input_available:
            eligible_for_ignored_review += 1
            ignored_candidates += not uses_foreign_input

    use_rate = (
        cross_agent_uses / len(follow_ups) if follow_ups else 0.0
    )
    ignored_rate = (
        ignored_candidates / eligible_for_ignored_review
        if eligible_for_ignored_review
        else 0.0
    )
    return InformationMeasures(
        information_coverage=coverage,
        cross_agent_input_use_rate=use_rate,
        ignored_input_candidate_rate=ignored_rate,
    )
