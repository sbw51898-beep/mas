from __future__ import annotations

from typing import Literal

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    HiddenBenchAssignment,
    HiddenBenchMessage,
    stable_shuffle,
)


VotePhase = Literal["hidden_pre", "hidden_post", "full_profile"]

_SYSTEM_TEMPLATE = """{description}

You have received the following information, notice the order of this information is
randomly shuffled, the order of facts does not indicate importance or relationship,
please reason carefully:
{information}
Keep your response concise-just one or two sentences."""

_FIRST_SPEAKER_PROMPT = "You are the first to speak."
_LATER_SPEAKER_TEMPLATE = """Previous messages from other people:
{messages}
It’s your turn to speak."""

_DISCLOSURE_FIRST_PROMPT = (
    "Before discussing the decision, first state the decision-relevant "
    "facts you personally received that the group may not have. Keep it "
    "to one or two sentences, then give your current view."
)


def _format_information(information: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in information)


def _format_messages(
    messages: tuple[HiddenBenchMessage, ...],
) -> str:
    return "\n".join(
        f"{message.agent_id}: {message.content}" for message in messages
    )


def _vote_format(task: HiddenBenchTask) -> str:
    possible_answers = " | ".join(task.possible_answers)
    return (
        "Please decide and provide your rationale in the following JSON "
        "format:\n"
        "{\n"
        f'  "vote": "<one exact answer from: {possible_answers}>",\n'
        '  "rationale": "<a concise rationale>"\n'
        "}\n"
        "Return only the JSON object."
    )


def build_hidden_system_prompt(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    agent_id: str,
) -> str:
    return _SYSTEM_TEMPLATE.format(
        description=task.description,
        information=_format_information(
            assignment.visible_information_for(agent_id)
        ),
    )


def build_full_profile_system_prompt(
    task: HiddenBenchTask,
    *,
    agent_id: str,
    seed: int,
) -> str:
    information = [
        *task.shared_information,
        *task.hidden_information,
    ]
    stable_shuffle(
        information,
        seed=seed,
        namespace=f"{task.id}:{agent_id}:full_profile",
    )
    return _SYSTEM_TEMPLATE.format(
        description=task.description,
        information=_format_information(tuple(information)),
    )


def build_discussion_user_prompt(
    visible_messages: tuple[HiddenBenchMessage, ...],
    *,
    disclosure_first: bool = False,
) -> str:
    if disclosure_first:
        return _DISCLOSURE_FIRST_PROMPT
    if not visible_messages:
        return _FIRST_SPEAKER_PROMPT
    return _LATER_SPEAKER_TEMPLATE.format(
        messages=_format_messages(visible_messages)
    )


def build_vote_user_prompt(
    task: HiddenBenchTask,
    visible_messages: tuple[HiddenBenchMessage, ...],
    *,
    phase: VotePhase,
) -> str:
    vote_format = _vote_format(task)
    if phase == "hidden_post":
        return (
            "Previous messages from other people:\n"
            f"{_format_messages(visible_messages)}\n"
            f"{vote_format}"
        )
    if phase not in {"hidden_pre", "full_profile"}:
        raise ValueError(f"unknown HiddenBench vote phase: {phase}")
    return vote_format


def build_vote_repair_prompt(
    task: HiddenBenchTask,
    invalid_text: str,
) -> str:
    possible_answers = " | ".join(task.possible_answers)
    return (
        "Return only one valid JSON object with exactly two string fields: "
        '"vote" and "rationale". '
        f'The "vote" must exactly equal one of: {possible_answers}.\n'
        "Invalid response:\n"
        f"{invalid_text}"
    )
