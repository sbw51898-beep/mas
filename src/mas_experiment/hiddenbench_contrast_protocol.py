from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mas_experiment.audit import current_git_commit
from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
    HiddenBenchRawRun,
    HiddenBenchRun,
    assign_hidden_information,
)
from mas_experiment.hiddenbench_dynamic_domain import DynamicProviderConfig
from mas_experiment.hiddenbench_metrics import score_hiddenbench_run
from mas_experiment.hiddenbench_protocol import (
    PromptProvider,
    _aggregate_run_metadata,
    _message_id,
    complete_hiddenbench_vote,
    run_hiddenbench_task,
)
from mas_experiment.hiddenbench_prompts import (
    build_full_profile_system_prompt,
    build_hidden_system_prompt,
    build_vote_user_prompt,
)


CONTRAST_PROMPT_VERSION = "hiddenbench-contrast-v1"
SINGLE_AGENT_ID = "agent-a"


class ContrastStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: Literal["hiddenbench-contrast-v1"]
    task_ids: tuple[int, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: Literal[CONTRAST_PROMPT_VERSION]
    conditions: tuple[Literal["single-direct", "single-reflect", "fixed-12"], ...]
    reflect_rounds: int = Field(gt=0)
    fixed_discussion_rounds: int = Field(ge=1)
    experiment_workers: int = Field(ge=1, le=16)
    judge_workers: int = Field(ge=1, le=16)
    judge_model: str = Field(min_length=1)
    judge_prompt_version: str = Field(min_length=1)
    provider: DynamicProviderConfig
    baseline_commit: str = Field(min_length=7)

    @model_validator(mode="after")
    def validate_study(self) -> ContrastStudyConfig:
        if self.task_ids != (1, 5, 7, 25):
            raise ValueError("task_ids must be exactly 1, 5, 7, 25")
        if self.repetitions != 10:
            raise ValueError("repetitions must be exactly 10")
        if self.reflect_rounds != 15:
            raise ValueError("single-agent reflection requires 15 rounds")
        if self.fixed_discussion_rounds != 3:
            raise ValueError("fixed-12 baseline requires 3 discussion rounds")
        return self


class ContrastStudyKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: Literal["single-direct", "single-reflect", "fixed-12"]
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return f"task-{self.task_id}:{self.condition}:rep-{self.repetition}"


class ContrastRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ContrastStudyKey
    pair_seed: int
    assignment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    run: HiddenBenchRun


def load_contrast_config(path: Path) -> ContrastStudyConfig:
    return ContrastStudyConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _contrast_fingerprint(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    seed: int,
    condition: str,
) -> str:
    payload = {
        "task": task.model_dump(mode="json"),
        "assignment": assignment.model_dump(mode="json"),
        "seed": seed,
        "condition": condition,
        "prompt_version": CONTRAST_PROMPT_VERSION,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


_REFLECT_FIRST_PROMPT = (
    "You are analyzing this decision alone. State your current choice and "
    "the evidence you have for it. Keep it to one or two sentences."
)
_REFLECT_TEMPLATE = """Previous reflections:
{history}
Continue reflecting: state the strongest evidence for your current choice
and one reason it may be wrong. Keep it to one or two sentences."""


async def _run_single_agent(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    seed: int,
    assignment: HiddenBenchAssignment,
    reflect_rounds: int,
) -> HiddenBenchRawRun:
    agent_id = SINGLE_AGENT_ID
    system_prompt = build_hidden_system_prompt(
        task,
        assignment,
        agent_id,
    )

    pre_votes = []
    pre_votes.append(
        await complete_hiddenbench_vote(
            task,
            provider,
            agent_id=agent_id,
            condition="hidden_pre",
            system_prompt=system_prompt,
            user_prompt=build_vote_user_prompt(
                task,
                (),
                phase="hidden_pre",
            ),
            seed=seed,
        )
    )

    messages: list[HiddenBenchMessage] = []
    if reflect_rounds:
        for round_index in range(1, reflect_rounds + 1):
            turn_index = len(messages)
            visible_messages = tuple(messages)
            if not visible_messages:
                user_prompt = _REFLECT_FIRST_PROMPT
            else:
                user_prompt = _REFLECT_TEMPLATE.format(
                    history="\n".join(
                        f"{message.agent_id}: {message.content}"
                        for message in visible_messages
                    )
                )
            completion = await provider.complete(
                agent_id=agent_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                seed=seed,
                json_response=False,
            )
            content = completion.text.strip()
            if not content:
                raise RuntimeError(
                    f"task {task.id} reflection returned empty text at "
                    f"round {round_index}"
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
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    provider_metadata=completion.provider_metadata,
                )
            )

    post_votes = []
    post_votes.append(
        await complete_hiddenbench_vote(
            task,
            provider,
            agent_id=agent_id,
            condition="hidden_post",
            system_prompt=system_prompt,
            user_prompt=build_vote_user_prompt(
                task,
                tuple(messages),
                phase="hidden_post",
            ),
            seed=seed,
        )
    )

    full_votes = []
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

    condition = "single-reflect" if reflect_rounds else "single-direct"
    fingerprint = _contrast_fingerprint(
        task,
        assignment,
        seed,
        condition,
    )
    all_items = (*pre_votes, *messages, *post_votes, *full_votes)
    provider_metadata = _aggregate_run_metadata(all_items)
    provider_metadata.update(
        {
            "prompt_version": CONTRAST_PROMPT_VERSION,
            "orchestration_mode": condition,
            "selector_llm_calls": 0,
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
    return score_hiddenbench_run(raw, validate_four_votes=False)


async def run_contrast_condition(
    *,
    task: HiddenBenchTask,
    condition: str,
    provider: PromptProvider,
    seed: int,
    assignment: HiddenBenchAssignment | None,
    config: ContrastStudyConfig,
) -> HiddenBenchRun:
    if condition == "fixed-12":
        raw = await run_hiddenbench_task(
            task,
            provider,
            seed=seed,
            discussion_rounds=config.fixed_discussion_rounds,
            disclosure_first=False,
        )
        return score_hiddenbench_run(raw)
    reflect_rounds = (
        config.reflect_rounds if condition == "single-reflect" else 0
    )
    resolved_assignment = assignment or assign_hidden_information(
        task,
        seed=seed,
    )
    raw = await _run_single_agent(
        task,
        provider,
        seed=seed,
        assignment=resolved_assignment,
        reflect_rounds=reflect_rounds,
    )
    return raw


def assignment_fingerprint(run: HiddenBenchRun) -> str:
    payload = json.dumps(
        run.assignment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
