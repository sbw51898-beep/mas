from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mas_experiment.hiddenbench_data import HiddenBenchTask


class OfficialSourceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OfficialTaskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    scenario: str
    correct_answer: str
    runs: int = Field(gt=0)
    average_accuracy: float = Field(ge=0, le=1)
    majority_accuracy: float = Field(ge=0, le=1)
    unanimous_correct_rate: float = Field(ge=0, le=1)
    false_consensus_rate: float = Field(ge=0, le=1)


class OfficialShortResults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    condition_id: int | str
    total_runs: int = Field(gt=0)
    by_task: dict[int, OfficialTaskMetrics]
    source: OfficialSourceRecord | None = None


def build_official_source_record(
    *,
    url: str,
    content: bytes,
) -> OfficialSourceRecord:
    return OfficialSourceRecord(
        url=url,
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _majority(votes: tuple[str, ...]) -> str | None:
    ranked = Counter(votes).most_common()
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def score_official_short_results(
    payload: dict[str, Any],
    tasks: tuple[HiddenBenchTask, ...],
    *,
    source: OfficialSourceRecord | None = None,
) -> OfficialShortResults:
    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != 1:
        raise ValueError("official short file must contain one condition")
    condition = conditions[0]
    if not isinstance(condition, dict):
        raise ValueError("official condition must be an object")
    runs = condition.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("official condition runs must be a non-empty list")

    short_tasks = {task.name: task for task in tasks if task.id in (1, 2, 3)}
    if set(short_tasks) != {
        "evacuation_west_city",
        "evacuation_north_hill",
        "evacuation_east_town",
    }:
        raise ValueError("official task mapping for IDs 1, 2, 3 is incomplete")
    grouped: dict[str, list[tuple[str, ...]]] = {
        name: [] for name in short_tasks
    }
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise ValueError(f"official run {index} must be an object")
        scenario = run.get("scenario")
        if scenario not in short_tasks:
            raise ValueError(f"unknown official scenario: {scenario}")
        final_votes = run.get("final_votes")
        if not isinstance(final_votes, list) or len(final_votes) != 4:
            raise ValueError("official run requires exactly four final votes")
        votes: list[str] = []
        for vote in final_votes:
            if not isinstance(vote, dict) or not isinstance(vote.get("vote"), str):
                raise ValueError("official final vote has invalid shape")
            answer = vote["vote"]
            if answer not in short_tasks[scenario].possible_answers:
                raise ValueError("official final vote is outside task answers")
            votes.append(answer)
        grouped[scenario].append(tuple(votes))

    by_task: dict[int, OfficialTaskMetrics] = {}
    for scenario, task_runs in grouped.items():
        if not task_runs:
            raise ValueError(f"official scenario has no runs: {scenario}")
        task = short_tasks[scenario]
        run_count = len(task_runs)
        correct_votes = sum(
            vote == task.correct_answer
            for votes in task_runs
            for vote in votes
        )
        majority_correct = sum(
            _majority(votes) == task.correct_answer for votes in task_runs
        )
        unanimous_correct = sum(
            len(set(votes)) == 1 and votes[0] == task.correct_answer
            for votes in task_runs
        )
        false_consensus = sum(
            len(set(votes)) == 1 and votes[0] != task.correct_answer
            for votes in task_runs
        )
        by_task[task.id] = OfficialTaskMetrics(
            task_id=task.id,
            scenario=scenario,
            correct_answer=task.correct_answer,
            runs=run_count,
            average_accuracy=correct_votes / (run_count * 4),
            majority_accuracy=majority_correct / run_count,
            unanimous_correct_rate=unanimous_correct / run_count,
            false_consensus_rate=false_consensus / run_count,
        )

    return OfficialShortResults(
        model=str(condition.get("model", "unknown")),
        condition_id=condition.get("condition_id", "unknown"),
        total_runs=len(runs),
        by_task=by_task,
        source=source,
    )
