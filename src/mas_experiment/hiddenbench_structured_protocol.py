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
)
from mas_experiment.hiddenbench_prompts import (
    build_decide_user_prompt,
    build_exchange_user_prompt,
    build_full_profile_system_prompt,
    build_hidden_system_prompt,
    build_vote_user_prompt,
)


STRUCTURED_PROMPT_VERSION = "hiddenbench-structured-exchange-decide-v1"
EXCHANGE_ROUNDS = 2
DECIDE_PASSES = 1
TOTAL_MESSAGES = len(AGENT_IDS) * (EXCHANGE_ROUNDS + DECIDE_PASSES)


class StructuredStudyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: Literal["hiddenbench-structured-v1"]
    task_ids: tuple[int, ...]
    repetitions: int = Field(gt=0)
    base_seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: Literal[STRUCTURED_PROMPT_VERSION]
    exchange_rounds: Literal[2]
    decide_passes: Literal[1]
    experiment_workers: int = Field(ge=1, le=16)
    judge_workers: int = Field(ge=1, le=16)
    judge_model: str = Field(min_length=1)
    judge_prompt_version: str = Field(min_length=1)
    provider: DynamicProviderConfig
    baseline_commit: str = Field(min_length=7)

    @model_validator(mode="after")
    def validate_study(self) -> StructuredStudyConfig:
        if self.task_ids != (1, 5, 7, 25):
            raise ValueError("task_ids must be exactly 1, 5, 7, 25")
        if self.repetitions != 10:
            raise ValueError("repetitions must be exactly 10")
        if (
            len(AGENT_IDS) * (self.exchange_rounds + self.decide_passes)
            != TOTAL_MESSAGES
        ):
            raise ValueError("structured protocol message count mismatch")
        return self


class StructuredStudyKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    condition: Literal["structured"] = "structured"
    repetition: int = Field(ge=0)

    @property
    def value(self) -> str:
        return f"task-{self.task_id}:structured:rep-{self.repetition}"


class StructuredRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: StructuredStudyKey
    pair_seed: int
    assignment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    run: HiddenBenchRun


def load_structured_config(path: Path) -> StructuredStudyConfig:
    return StructuredStudyConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _structured_fingerprint(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    seed: int,
) -> str:
    payload = {
        "task": task.model_dump(mode="json"),
        "assignment": assignment.model_dump(mode="json"),
        "seed": seed,
        "prompt_version": STRUCTURED_PROMPT_VERSION,
        "exchange_rounds": EXCHANGE_ROUNDS,
        "decide_passes": DECIDE_PASSES,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def run_hiddenbench_structured_task(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    seed: int,
    assignment: HiddenBenchAssignment | None = None,
) -> HiddenBenchRawRun:
    resolved_assignment = assignment or assign_hidden_information(
        task,
        seed=seed,
    )
    if resolved_assignment.seed != seed:
        raise ValueError("structured assignment seed mismatch")
    hidden_system_prompts = {
        agent_id: build_hidden_system_prompt(
            task,
            resolved_assignment,
            agent_id,
        )
        for agent_id in AGENT_IDS
    }

    pre_votes = []
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
    for round_index in range(1, EXCHANGE_ROUNDS + 1):
        for agent_id in AGENT_IDS:
            turn_index = len(messages)
            visible_messages = tuple(messages)
            user_prompt = build_exchange_user_prompt(visible_messages)
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
                    f"task {task.id} exchange failed for {agent_id} "
                    f"at round {round_index}, turn {turn_index}"
                ) from error
            content = completion.text.strip()
            if not content:
                raise RuntimeError(
                    f"task {task.id} exchange returned empty text for "
                    f"{agent_id} at round {round_index}, turn {turn_index}"
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
                    provider_metadata=completion.provider_metadata,
                )
            )

    decide_round = EXCHANGE_ROUNDS + 1
    for agent_id in AGENT_IDS:
        turn_index = len(messages)
        visible_messages = tuple(messages)
        user_prompt = build_decide_user_prompt(visible_messages)
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
                f"task {task.id} decide failed for {agent_id} "
                f"at turn {turn_index}"
            ) from error
        content = completion.text.strip()
        if not content:
            raise RuntimeError(
                f"task {task.id} decide returned empty text for "
                f"{agent_id} at turn {turn_index}"
            )
        messages.append(
            HiddenBenchMessage(
                message_id=_message_id(
                    task.id,
                    decide_round,
                    turn_index,
                    agent_id,
                    content,
                ),
                round_index=decide_round,
                turn_index=turn_index,
                agent_id=agent_id,
                content=content,
                visible_message_ids=tuple(
                    message.message_id for message in visible_messages
                ),
                system_prompt=hidden_system_prompts[agent_id],
                user_prompt=user_prompt,
                provider_metadata=completion.provider_metadata,
            )
        )

    if len(messages) != TOTAL_MESSAGES:
        raise RuntimeError("structured protocol message count mismatch")

    post_votes = []
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

    full_votes = []
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

    fingerprint = _structured_fingerprint(
        task,
        resolved_assignment,
        seed,
    )
    all_items = (
        *pre_votes,
        *messages,
        *post_votes,
        *full_votes,
    )
    provider_metadata = _aggregate_run_metadata(all_items)
    provider_metadata.update(
        {
            "prompt_version": STRUCTURED_PROMPT_VERSION,
            "orchestration_mode": "structured",
            "selector_llm_calls": 0,
        }
    )
    raw = HiddenBenchRawRun(
        run_id=hashlib.sha256(
            f"{fingerprint}|raw".encode("utf-8")
        ).hexdigest()[:16],
        task=task,
        assignment=resolved_assignment,
        hidden_pre_votes=tuple(pre_votes),
        discussion_messages=tuple(messages),
        hidden_post_votes=tuple(post_votes),
        full_profile_votes=tuple(full_votes),
        provider_metadata=provider_metadata,
        configuration_fingerprint=fingerprint,
        code_commit=current_git_commit(),
    )
    return score_hiddenbench_run(raw)


def assignment_fingerprint(run: HiddenBenchRun) -> str:
    payload = json.dumps(
        run.assignment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
