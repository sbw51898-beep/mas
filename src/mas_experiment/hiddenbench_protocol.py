from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_atomic_disclosure import (
    append_reveal_all_block,
    decompose_private_facts,
)
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchMessage,
    HiddenBenchRawRun,
    HiddenBenchVote,
    PromptCompletion,
    VoteCondition,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_prompts import (
    build_discussion_user_prompt,
    build_full_profile_system_prompt,
    build_hidden_system_prompt,
    build_vote_repair_prompt,
    build_vote_user_prompt,
)


PROMPT_VERSION = "hiddenbench-appendix-a4-v1"


class PromptProvider(Protocol):
    async def complete(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        json_response: bool,
    ) -> PromptCompletion: ...


def parse_hiddenbench_vote(
    task: HiddenBenchTask,
    text: str,
) -> tuple[str, str]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("vote response does not contain a JSON object")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError("vote response contains invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("vote response JSON must be an object")
    if set(payload) != {"vote", "rationale"}:
        raise ValueError(
            'vote response must contain exactly "vote" and "rationale"'
        )
    vote = payload["vote"]
    rationale = payload["rationale"]
    if not isinstance(vote, str):
        raise ValueError("vote must be a string")
    if vote not in task.possible_answers:
        raise ValueError("vote must exactly match official possible_answers")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rationale must be a non-empty string")
    return vote, rationale.strip()


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _sum_numeric_mappings(
    mappings: tuple[Mapping[str, Any], ...],
) -> dict[str, int | float]:
    totals: dict[str, int | float] = {}
    for mapping in mappings:
        for key, value in mapping.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return totals


def _merge_completion_metadata(
    completions: tuple[PromptCompletion, ...],
    *,
    repair_requests: int,
) -> dict[str, Any]:
    metadata = tuple(
        _plain_mapping(completion.provider_metadata)
        for completion in completions
    )
    request_ids = [
        str(request_id)
        for item in metadata
        for request_id in item.get("request_ids", ())
        if request_id
    ]
    for item in metadata:
        request_id = item.get("request_id")
        if request_id and str(request_id) not in request_ids:
            request_ids.append(str(request_id))
    usage = _sum_numeric_mappings(
        tuple(_plain_mapping(item.get("usage")) for item in metadata)
    )
    first = metadata[0] if metadata else {}
    last = metadata[-1] if metadata else {}
    return {
        "provider": last.get("provider", first.get("provider", "unknown")),
        "model": last.get("model", first.get("model", "unknown")),
        "thinking": last.get("thinking", first.get("thinking")),
        "temperature": last.get(
            "temperature",
            first.get("temperature"),
        ),
        "api_requests": sum(
            int(item.get("api_requests", 0) or 0) for item in metadata
        ),
        "repair_requests": repair_requests,
        "usage": usage,
        "request_id": request_ids[-1] if request_ids else None,
        "request_ids": request_ids,
    }


async def complete_hiddenbench_vote(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    agent_id: str,
    condition: VoteCondition,
    system_prompt: str,
    user_prompt: str,
    seed: int,
) -> HiddenBenchVote:
    first = await provider.complete(
        agent_id=agent_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        seed=seed,
        json_response=True,
    )
    try:
        vote, rationale = parse_hiddenbench_vote(task, first.text)
    except ValueError as first_error:
        repair_prompt = build_vote_repair_prompt(task, first.text)
        repaired = await provider.complete(
            agent_id=agent_id,
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            seed=seed,
            json_response=True,
        )
        try:
            vote, rationale = parse_hiddenbench_vote(task, repaired.text)
        except ValueError as repair_error:
            raise ValueError(
                "model vote invalid after one repair request"
            ) from repair_error
        metadata = _merge_completion_metadata(
            (first, repaired),
            repair_requests=1,
        )
        metadata.update(
            {
                "invalid_raw_text": first.text,
                "repair_prompt": repair_prompt,
                "first_parse_error": str(first_error),
            }
        )
        raw_text = repaired.text
    else:
        metadata = _merge_completion_metadata(
            (first,),
            repair_requests=0,
        )
        raw_text = first.text

    return HiddenBenchVote(
        agent_id=agent_id,
        condition=condition,
        vote=vote,
        rationale=rationale,
        raw_text=raw_text,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        provider_metadata=metadata,
    )


def _message_id(
    task_id: int,
    round_index: int,
    turn_index: int,
    agent_id: str,
    content: str,
) -> str:
    payload = (
        f"{task_id}|{round_index}|{turn_index}|{agent_id}|{content}"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _configuration_fingerprint(
    task: HiddenBenchTask,
    *,
    seed: int,
    discussion_rounds: int,
    assignment: Any,
    disclosure_first: bool = False,
    mechanical_reveal_all: bool = False,
) -> str:
    payload = {
        "task": task.model_dump(mode="json"),
        "seed": seed,
        "discussion_rounds": discussion_rounds,
        "assignment": assignment.model_dump(mode="json"),
        "agent_ids": AGENT_IDS,
        "prompt_version": PROMPT_VERSION,
        "disclosure_first": disclosure_first,
        "mechanical_reveal_all": mechanical_reveal_all,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _aggregate_run_metadata(
    votes_and_messages: tuple[HiddenBenchVote | HiddenBenchMessage, ...],
) -> dict[str, Any]:
    items = tuple(item.provider_metadata for item in votes_and_messages)
    usage = _sum_numeric_mappings(
        tuple(_plain_mapping(item.get("usage")) for item in items)
    )
    return {
        "logical_response_slots": len(items),
        "api_requests": sum(
            int(item.get("api_requests", 0) or 0) for item in items
        ),
        "repair_requests": sum(
            int(item.get("repair_requests", 0) or 0) for item in items
        ),
        "usage": usage,
        "prompt_version": PROMPT_VERSION,
    }


async def run_hiddenbench_task(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    seed: int,
    discussion_rounds: int = 15,
    disclosure_first: bool = False,
    mechanical_reveal_all: bool = False,
) -> HiddenBenchRawRun:
    if discussion_rounds not in (3, 4, 8, 15):
        raise ValueError(
            "discussion_rounds must be 3, 4, 8 or 15 "
            "(12/16/32/60 messages)"
        )
    assignment = assign_hidden_information(task, seed=seed)
    atomic_facts = decompose_private_facts(assignment)
    hidden_system_prompts = {
        agent_id: build_hidden_system_prompt(
            task,
            assignment,
            agent_id,
        )
        for agent_id in AGENT_IDS
    }

    pre_votes: list[HiddenBenchVote] = []
    for agent_id in AGENT_IDS:
        try:
            pre_votes.append(
                await complete_hiddenbench_vote(
                    task,
                    provider,
                    agent_id=agent_id,
                    condition="hidden_pre",
                    system_prompt=hidden_system_prompts[agent_id],
                    user_prompt=build_vote_user_prompt(
                        task,
                        (),
                        phase="hidden_pre",
                    ),
                    seed=seed,
                )
            )
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} hidden_pre failed for {agent_id}"
            ) from error

    messages: list[HiddenBenchMessage] = []
    for round_index in range(1, discussion_rounds + 1):
        for agent_id in AGENT_IDS:
            turn_index = len(messages)
            visible_messages = tuple(messages)
            user_prompt = build_discussion_user_prompt(
                visible_messages,
                disclosure_first=disclosure_first and round_index == 1,
            )
            try:
                completion = await provider.complete(
                    agent_id=agent_id,
                    system_prompt=hidden_system_prompts[agent_id],
                    user_prompt=user_prompt,
                    seed=seed,
                    json_response=False,
                )
            except Exception as error:
                raise RuntimeError(
                    f"task {task.id} discussion failed for {agent_id} "
                    f"at round {round_index}, turn {turn_index}"
                ) from error
            content = completion.text.strip()
            if not content:
                raise RuntimeError(
                    f"task {task.id} discussion returned empty text for "
                    f"{agent_id} at round {round_index}, turn {turn_index}"
                )
            appended_fact_ids: tuple[str, ...] = ()
            if mechanical_reveal_all and round_index == 1:
                owner_facts = tuple(
                    fact
                    for fact in atomic_facts
                    if fact.owner_agent_id == agent_id
                )
                content, appended_fact_ids = append_reveal_all_block(
                    content,
                    owner_facts,
                )
            message_metadata = dict(completion.provider_metadata)
            message_metadata.update(
                {
                    "mechanical_reveal_all": bool(appended_fact_ids),
                    "appended_fact_ids": list(appended_fact_ids),
                }
            )
            messages.append(
                HiddenBenchMessage(
                    message_id=_message_id(
                        task.id,
                        round_index,
                        turn_index,
                        agent_id,
                        content,
                    ),
                    round_index=round_index,
                    turn_index=turn_index,
                    agent_id=agent_id,
                    content=content,
                    visible_message_ids=tuple(
                        message.message_id
                        for message in visible_messages
                    ),
                    system_prompt=hidden_system_prompts[agent_id],
                    user_prompt=user_prompt,
                    provider_metadata=message_metadata,
                )
            )

    post_votes: list[HiddenBenchVote] = []
    public_history = tuple(messages)
    for agent_id in AGENT_IDS:
        try:
            post_votes.append(
                await complete_hiddenbench_vote(
                    task,
                    provider,
                    agent_id=agent_id,
                    condition="hidden_post",
                    system_prompt=hidden_system_prompts[agent_id],
                    user_prompt=build_vote_user_prompt(
                        task,
                        public_history,
                        phase="hidden_post",
                    ),
                    seed=seed,
                )
            )
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} hidden_post failed for {agent_id}"
            ) from error

    full_votes: list[HiddenBenchVote] = []
    for agent_id in AGENT_IDS:
        try:
            full_votes.append(
                await complete_hiddenbench_vote(
                    task,
                    provider,
                    agent_id=agent_id,
                    condition="full_profile",
                    system_prompt=build_full_profile_system_prompt(
                        task,
                        agent_id=agent_id,
                        seed=seed,
                    ),
                    user_prompt=build_vote_user_prompt(
                        task,
                        (),
                        phase="full_profile",
                    ),
                    seed=seed,
                )
            )
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} full_profile failed for {agent_id}"
            ) from error

    fingerprint = _configuration_fingerprint(
        task,
        seed=seed,
        discussion_rounds=discussion_rounds,
        assignment=assignment,
        disclosure_first=disclosure_first,
        mechanical_reveal_all=mechanical_reveal_all,
    )
    all_items = (
        *pre_votes,
        *messages,
        *post_votes,
        *full_votes,
    )
    return HiddenBenchRawRun(
        run_id=hashlib.sha256(
            f"{fingerprint}|raw".encode("utf-8")
        ).hexdigest()[:16],
        task=task,
        assignment=assignment,
        hidden_pre_votes=tuple(pre_votes),
        discussion_messages=tuple(messages),
        hidden_post_votes=tuple(post_votes),
        full_profile_votes=tuple(full_votes),
        provider_metadata={
            **_aggregate_run_metadata(all_items),
            "mechanical_reveal_all": mechanical_reveal_all,
        },
        configuration_fingerprint=fingerprint,
        code_commit=current_git_commit(),
    )
