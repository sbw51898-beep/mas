from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
)


_RECOMMENDATION_CUE = re.compile(
    r"\b(?:"
    r"(?:choose|chooses|choosing|chose|chosen|"
    r"select|selects|selecting|selected|"
    r"recommend|recommends|recommending|recommended|"
    r"support|supports|supporting|supported|"
    r"agree|agrees|agreed|agreeing)\s+(?:on\s+)?"
    r"|"
    r"(?:vote|votes|voted|voting)\s+for\s+)",
    flags=re.IGNORECASE,
)


class ConsensusDynamics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    first_consensus_turn: int | None
    first_consensus_answer: str | None
    first_stable_consensus_turn: int | None
    stable_consensus_confirmed_turn: int | None
    first_stable_consensus_answer: str | None
    first_stable_consensus_correct: bool | None
    final_consensus_answer: str | None
    final_consensus_correct: bool | None
    consensus_flips: int = Field(ge=0)
    post_stable_message_count: int = Field(ge=0)
    repeated_confirmation_count: int = Field(ge=0)
    position_by_message: dict[str, str | None]


def _distance(
    left: tuple[int, int],
    right: tuple[int, int],
) -> int:
    if left[1] < right[0]:
        return right[0] - left[1]
    if right[1] < left[0]:
        return left[0] - right[1]
    return 0


def extract_expressed_position(
    text: str,
    possible_answers: tuple[str, ...],
) -> str | None:
    cue_spans = tuple(
        (match.start(), match.end())
        for match in _RECOMMENDATION_CUE.finditer(text)
    )
    if not cue_spans:
        return None

    eligible: list[str] = []
    for answer in possible_answers:
        answer_spans = tuple(
            (match.start(), match.end())
            for match in re.finditer(
                re.escape(answer),
                text,
                flags=re.IGNORECASE,
            )
        )
        if answer_spans and min(
            _distance(cue, answer_span)
            for cue in cue_spans
            for answer_span in answer_spans
        ) <= 80:
            eligible.append(answer)
    if len(eligible) != 1:
        return None
    return eligible[0]


def _unanimous_answer(
    positions: Mapping[str, str],
) -> str | None:
    if set(positions) != set(AGENT_IDS):
        return None
    answers = set(positions.values())
    return next(iter(answers)) if len(answers) == 1 else None


def analyze_consensus_dynamics(
    *,
    messages: tuple[HiddenBenchMessage, ...],
    possible_answers: tuple[str, ...],
    correct_answer: str,
    new_rule_disclosures_by_message: Mapping[
        str,
        tuple[str, ...] | list[str] | set[str],
    ],
) -> ConsensusDynamics:
    positions: dict[str, str] = {}
    position_by_message: dict[str, str | None] = {}
    unanimous_after_message: list[str | None] = []
    first_consensus_turn: int | None = None
    first_consensus_answer: str | None = None
    consensus_flips = 0
    last_consensus_answer: str | None = None

    for ordinal, message in enumerate(messages, start=1):
        expressed = extract_expressed_position(
            message.content,
            possible_answers,
        )
        position_by_message[message.message_id] = expressed
        if expressed is not None:
            positions[message.agent_id] = expressed
        unanimous = _unanimous_answer(positions)
        unanimous_after_message.append(unanimous)
        if unanimous is None:
            continue
        if first_consensus_turn is None:
            first_consensus_turn = ordinal
            first_consensus_answer = unanimous
        if (
            last_consensus_answer is not None
            and unanimous != last_consensus_answer
        ):
            consensus_flips += 1
        last_consensus_answer = unanimous

    stable_start_index: int | None = None
    stable_confirmed_index: int | None = None
    stable_answer: str | None = None
    for index, answer in enumerate(unanimous_after_message):
        confirmation_index = index + 4
        if answer is None or confirmation_index >= len(messages):
            continue
        if all(
            candidate == answer
            for candidate in unanimous_after_message[
                index : confirmation_index + 1
            ]
        ):
            stable_start_index = index
            stable_confirmed_index = confirmation_index
            stable_answer = answer
            break

    post_stable_message_count = 0
    repeated_confirmation_count = 0
    if (
        stable_confirmed_index is not None
        and stable_answer is not None
    ):
        post_stable = messages[stable_confirmed_index + 1 :]
        post_stable_message_count = len(post_stable)
        repeated_confirmation_count = sum(
            position_by_message[message.message_id] == stable_answer
            and not new_rule_disclosures_by_message.get(
                message.message_id
            )
            for message in post_stable
        )

    final_answer = unanimous_after_message[-1] if messages else None
    return ConsensusDynamics(
        first_consensus_turn=first_consensus_turn,
        first_consensus_answer=first_consensus_answer,
        first_stable_consensus_turn=(
            stable_start_index + 1
            if stable_start_index is not None
            else None
        ),
        stable_consensus_confirmed_turn=(
            stable_confirmed_index + 1
            if stable_confirmed_index is not None
            else None
        ),
        first_stable_consensus_answer=stable_answer,
        first_stable_consensus_correct=(
            stable_answer == correct_answer
            if stable_answer is not None
            else None
        ),
        final_consensus_answer=final_answer,
        final_consensus_correct=(
            final_answer == correct_answer
            if final_answer is not None
            else None
        ),
        consensus_flips=consensus_flips,
        post_stable_message_count=post_stable_message_count,
        repeated_confirmation_count=repeated_confirmation_count,
        position_by_message=position_by_message,
    )
