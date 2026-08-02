from __future__ import annotations

import hashlib
import json

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
    HiddenBenchRawRun,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicHiddenBenchRun,
    DynamicPilotConfig,
    SelectorCandidateScore,
    SelectorEvent,
)
from mas_experiment.hiddenbench_dynamic_selector import select_dynamic_speaker
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_prompts import (
    build_discussion_user_prompt,
    build_full_profile_system_prompt,
    build_hidden_system_prompt,
    build_vote_user_prompt,
)
from mas_experiment.hiddenbench_protocol import (
    PROMPT_VERSION,
    PromptProvider,
    _aggregate_run_metadata,
    _message_id,
    complete_hiddenbench_vote,
)


def _dynamic_fingerprint(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    config: DynamicPilotConfig,
    baseline_run_id: str,
    disclosure_first: bool = False,
) -> str:
    payload = {
        "task": task.model_dump(mode="json"),
        "assignment": assignment.model_dump(mode="json"),
        "pilot_config": config.model_dump(mode="json"),
        "baseline_run_id": baseline_run_id,
        "prompt_version": PROMPT_VERSION,
        "orchestration_mode": "dynamic",
        "disclosure_first": disclosure_first,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def run_hiddenbench_dynamic_task(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    seed: int,
    assignment: HiddenBenchAssignment,
    baseline_run_id: str,
    config: DynamicPilotConfig,
    disclosure_first: bool = False,
) -> DynamicHiddenBenchRun:
    if assignment.task_id != task.id:
        raise ValueError("assignment task ID mismatch")
    if assignment.seed != seed:
        raise ValueError("assignment seed mismatch")
    if config.total_speeches != 60 or config.speeches_per_agent != 15:
        raise ValueError("dynamic protocol requires 60 speeches and 15 each")

    hidden_system_prompts = {
        agent_id: build_hidden_system_prompt(task, assignment, agent_id)
        for agent_id in AGENT_IDS
    }
    pre_votes = []
    for agent_id in AGENT_IDS:
        try:
            vote = await complete_hiddenbench_vote(
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
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} hidden_pre failed for {agent_id}"
            ) from error
        pre_votes.append(vote)

    pre_stances = {vote.agent_id: vote.vote for vote in pre_votes}
    messages: list[HiddenBenchMessage] = []
    events: list[SelectorEvent] = []
    remaining_quotas = {
        agent_id: config.speeches_per_agent for agent_id in AGENT_IDS
    }
    last_spoken_turns = {agent_id: -1 for agent_id in AGENT_IDS}

    forced_agents = tuple(AGENT_IDS) if disclosure_first else ()
    turn_index = 0
    while turn_index < config.total_speeches:
        if turn_index < len(forced_agents):
            agent_id = forced_agents[turn_index]
            candidate_scores = (
                SelectorCandidateScore(
                    agent_id=agent_id,
                    disagreement=0.0,
                    undisclosed=0.0,
                    related_discussion=0.0,
                    response_due=0.0,
                    waiting=0.0,
                    weighted_total=0.0,
                    remaining_quota=remaining_quotas[agent_id],
                    raw_waiting=0,
                    latest_stance=None,
                    selected=True,
                ),
            )
            round_index = 1
            user_prompt = build_discussion_user_prompt(
                tuple(messages),
                disclosure_first=True,
            )
        else:
            agent_id, candidate_scores = select_dynamic_speaker(
                task=task,
                assignment=assignment,
                pre_stances=pre_stances,
                public_messages=tuple(messages),
                remaining_quotas=remaining_quotas,
                last_spoken_turns=last_spoken_turns,
                config=config.selector,
                turn_index=turn_index,
            )
            round_index = turn_index // 4 + 1
            user_prompt = build_discussion_user_prompt(
                tuple(messages),
            )
        events.append(
            SelectorEvent(
                task_id=task.id,
                turn_index=turn_index,
                round_index=round_index,
                selected_agent_id=agent_id,
                candidates=candidate_scores,
            )
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
                f"at turn {turn_index}"
            ) from error
        content = completion.text.strip()
        if not content:
            raise RuntimeError(
                f"task {task.id} discussion returned empty text for "
                f"{agent_id} at turn {turn_index}"
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
                    message.message_id for message in messages
                ),
                system_prompt=hidden_system_prompts[agent_id],
                user_prompt=user_prompt,
                provider_metadata=completion.provider_metadata,
            )
        )
        remaining_quotas[agent_id] -= 1
        last_spoken_turns[agent_id] = turn_index
        turn_index += 1

    if remaining_quotas != {agent_id: 0 for agent_id in AGENT_IDS}:
        raise RuntimeError("dynamic protocol did not exhaust equal quotas")

    post_votes = []
    public_history = tuple(messages)
    for agent_id in AGENT_IDS:
        try:
            vote = await complete_hiddenbench_vote(
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
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} hidden_post failed for {agent_id}"
            ) from error
        post_votes.append(vote)

    full_votes = []
    for agent_id in AGENT_IDS:
        try:
            vote = await complete_hiddenbench_vote(
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
        except Exception as error:
            raise RuntimeError(
                f"task {task.id} full_profile failed for {agent_id}"
            ) from error
        full_votes.append(vote)

    fingerprint = _dynamic_fingerprint(
        task,
        assignment,
        config,
        baseline_run_id,
        disclosure_first=disclosure_first,
    )
    all_items = (*pre_votes, *messages, *post_votes, *full_votes)
    provider_metadata = _aggregate_run_metadata(all_items)
    provider_metadata.update(
        {
            "selector_llm_calls": 0,
            "orchestration_mode": "dynamic",
            "prompt_version": PROMPT_VERSION,
        }
    )
    raw = HiddenBenchRawRun(
        run_id=hashlib.sha256(
            f"{fingerprint}|raw".encode("utf-8")
        ).hexdigest()[:16],
        task=task,
        assignment=assignment,
        hidden_pre_votes=tuple(pre_votes),
        discussion_messages=tuple(messages),
        hidden_post_votes=tuple(post_votes),
        full_profile_votes=tuple(full_votes),
        provider_metadata=provider_metadata,
        configuration_fingerprint=fingerprint,
        code_commit=current_git_commit(),
    )
    return DynamicHiddenBenchRun(
        baseline_run_id=baseline_run_id,
        dynamic_configuration_fingerprint=fingerprint,
        run=score_hiddenbench_run(raw),
        selection_events=tuple(events),
    )
