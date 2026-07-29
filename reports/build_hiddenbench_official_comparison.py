from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_IDS = (1, 5, 7, 25)
OFFICIAL_REPOSITORY_COMMIT = "3be6ca16973e4fb751ffc0dfb7eb11f2d28335d1"
OFFICIAL_FILES = {
    "hidden_manual_adapted_gpt-4.1.json": {
        "sha256": "1c425d73ff384a182ecc3a5109546eaaf62618e076300c8d3ccf384ae031d9cf",
        "source_path": (
            "paper/hidden_manual_adapted/"
            "hidden_manual_adapted_gpt-4.1.json"
        ),
    },
    "hidden_generated_gpt-4.1.json": {
        "sha256": "e0ea7e3d1f2ba96f636c0eafd8fd485e73b2785e7ee9911e3000d253cd613a84",
        "source_path": (
            "paper/hidden_generated/hidden_generated_gpt-4.1.json"
        ),
    },
    "full_profile_gpt-4.1.json": {
        "sha256": "262ce811e96f1d28a0ef1bdb69e42487acbd8da0c56d67c327351cd6c2bb1e55",
        "source_path": "paper/full_profile/full_profile_gpt-4.1.json",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_official(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    conditions = payload["conditions"]
    if len(conditions) != 1:
        raise ValueError(f"{path.name}: expected one condition")
    if conditions[0]["model"] != "gpt-4.1":
        raise ValueError(f"{path.name}: unexpected model")
    return conditions[0]["runs"]


def _individual_accuracy(
    votes: list[dict[str, Any]], correct_answer: str
) -> float:
    if not votes:
        return 0.0
    return sum(vote.get("vote") == correct_answer for vote in votes) / len(
        votes
    )


def _majority_accuracy(
    votes: list[dict[str, Any]], correct_answer: str
) -> float:
    if not votes:
        return 0.0
    return float(
        sum(vote.get("vote") == correct_answer for vote in votes)
        > len(votes) / 2
    )


def _score_runs(
    runs: list[dict[str, Any]], correct_answer: str
) -> dict[str, Any]:
    pre_average = [
        _individual_accuracy(run["initial_votes"], correct_answer)
        for run in runs
    ]
    post_average = [
        _individual_accuracy(run["final_votes"], correct_answer)
        for run in runs
    ]
    pre_majority = [
        _majority_accuracy(run["initial_votes"], correct_answer)
        for run in runs
    ]
    post_majority = [
        _majority_accuracy(run["final_votes"], correct_answer)
        for run in runs
    ]
    return {
        "runs": len(runs),
        "pre_average_accuracy": mean(pre_average),
        "post_average_accuracy": mean(post_average),
        "pre_majority_accuracy": mean(pre_majority),
        "post_majority_accuracy": mean(post_majority),
        "final_majority_distribution": dict(
            sorted(Counter(run.get("majority_vote") for run in runs).items())
        ),
        "rounds": sorted({len(run.get("rounds", [])) for run in runs}),
    }


def _load_local_summary(path: Path) -> dict[tuple[int, str], dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            (int(row["task_id"]), row["condition"]): row
            for row in csv.DictReader(handle)
        }


def build_rows(
    *,
    official_dir: Path,
    benchmark_path: Path,
    local_summary_path: Path,
) -> list[dict[str, Any]]:
    for filename, metadata in OFFICIAL_FILES.items():
        path = official_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = _sha256(path)
        if actual != metadata["sha256"]:
            raise ValueError(
                f"{filename}: SHA-256 mismatch: "
                f"expected {metadata['sha256']}, got {actual}"
            )

    tasks = {
        int(task["id"]): task
        for task in json.loads(benchmark_path.read_text(encoding="utf-8"))
        if int(task["id"]) in TASK_IDS
    }
    if set(tasks) != set(TASK_IDS):
        raise ValueError("the four selected task IDs were not found")

    manual_runs = _load_official(
        official_dir / "hidden_manual_adapted_gpt-4.1.json"
    )
    generated_runs = _load_official(
        official_dir / "hidden_generated_gpt-4.1.json"
    )
    full_runs = _load_official(official_dir / "full_profile_gpt-4.1.json")
    local = _load_local_summary(local_summary_path)

    rows: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        task = tasks[task_id]
        scenario = task["name"]
        correct_answer = task["correct_answer"]
        if task_id <= 8:
            hidden_filename = "hidden_manual_adapted_gpt-4.1.json"
            hidden_pool = manual_runs
        else:
            hidden_filename = "hidden_generated_gpt-4.1.json"
            hidden_pool = generated_runs
        hidden_task_runs = [
            run for run in hidden_pool if run["scenario"] == scenario
        ]
        full_task_runs = [
            run for run in full_runs if run["scenario"] == scenario
        ]
        if len(hidden_task_runs) != 10 or len(full_task_runs) != 10:
            raise ValueError(
                f"{scenario}: expected 10 hidden and 10 full runs, got "
                f"{len(hidden_task_runs)} and {len(full_task_runs)}"
            )
        hidden = _score_runs(hidden_task_runs, correct_answer)
        full = _score_runs(full_task_runs, correct_answer)
        fixed = local[(task_id, "fixed")]
        dynamic = local[(task_id, "dynamic")]
        rows.append(
            {
                "task_id": task_id,
                "scenario": scenario,
                "correct_answer": correct_answer,
                "official_hidden_file": hidden_filename,
                "official_hidden_runs": hidden["runs"],
                "official_hidden_rounds": json.dumps(hidden["rounds"]),
                "official_hidden_pre_average_accuracy": hidden[
                    "pre_average_accuracy"
                ],
                "official_hidden_post_average_accuracy": hidden[
                    "post_average_accuracy"
                ],
                "official_hidden_pre_majority_accuracy": hidden[
                    "pre_majority_accuracy"
                ],
                "official_hidden_post_majority_accuracy": hidden[
                    "post_majority_accuracy"
                ],
                "official_hidden_final_distribution": json.dumps(
                    hidden["final_majority_distribution"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "official_full_runs": full["runs"],
                "official_full_rounds": json.dumps(full["rounds"]),
                "official_full_pre_average_accuracy": full[
                    "pre_average_accuracy"
                ],
                "official_full_pre_majority_accuracy": full[
                    "pre_majority_accuracy"
                ],
                "official_full_final_distribution": json.dumps(
                    full["final_majority_distribution"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "deepseek_fixed_post_majority_accuracy": int(
                    fixed["post_majority_correct_count"]
                )
                / int(fixed["repetitions"]),
                "deepseek_dynamic_post_majority_accuracy": int(
                    dynamic["post_majority_correct_count"]
                )
                / int(dynamic["repetitions"]),
                "deepseek_fixed_wrong_consensus_rate": int(
                    fixed["wrong_consensus_count"]
                )
                / int(fixed["repetitions"]),
                "deepseek_dynamic_wrong_consensus_rate": int(
                    dynamic["wrong_consensus_count"]
                )
                / int(dynamic["repetitions"]),
                "deepseek_fixed_ai_disclosure": float(
                    fixed["ai_disclosure_mean"]
                ),
                "deepseek_dynamic_ai_disclosure": float(
                    dynamic["ai_disclosure_mean"]
                ),
            }
        )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _percent(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# HiddenBench 官方 GPT-4.1 四题结果与本实验对照",
        "",
        "## 口径",
        "",
        "- 官方逐题数值不是从论文总表反推，而是从 HiddenBench 官方公开结果包逐 session 重新计分。",
        "- 官方计分严格复用仓库 `src/hiddenbench/metrics.py` 的定义：平均正确率是每轮四名 Agent 正确票比例；多数正确率要求正确票严格超过一半。",
        "- 本实验的 DeepSeek 数值只与同一题、同一隐藏信息结构做描述性对照。模型、编排实现和实验日期均不同，不能把差值单独归因于 Microsoft Agent Framework。",
        "",
        "## 逐题结果",
        "",
        "| ID | 场景 | 官方 GPT-4.1 Hidden 前/后平均正确率 | 官方 Hidden 前/后多数正确率 | 官方 Full 前平均/多数正确率 | 本实验固定/动态后多数正确率 |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {task_id} | `{scenario}` | {pre_avg} / {post_avg} | "
            "{pre_maj} / {post_maj} | {full_avg} / {full_maj} | "
            "{fixed} / {dynamic} |".format(
                **row,
                pre_avg=_percent(
                    row["official_hidden_pre_average_accuracy"]
                ),
                post_avg=_percent(
                    row["official_hidden_post_average_accuracy"]
                ),
                pre_maj=_percent(
                    row["official_hidden_pre_majority_accuracy"]
                ),
                post_maj=_percent(
                    row["official_hidden_post_majority_accuracy"]
                ),
                full_avg=_percent(
                    row["official_full_pre_average_accuracy"]
                ),
                full_maj=_percent(
                    row["official_full_pre_majority_accuracy"]
                ),
                fixed=_percent(
                    row["deepseek_fixed_post_majority_accuracy"]
                ),
                dynamic=_percent(
                    row["deepseek_dynamic_post_majority_accuracy"]
                ),
            )
        )
    lines.extend(
        [
            "",
            "每题官方 Hidden 和 Full Profile 均为 10 个 session。官方 Hidden 为 15 轮讨论；公开 Full Profile 文件中这四题均记录 1 轮。",
            "",
            "## 来源冻结",
            "",
            f"- HiddenBench 官方代码提交：`{OFFICIAL_REPOSITORY_COMMIT}`。",
            "- 官方结果数据集：`YuxuanLi1225/HiddenBench-results`。",
        ]
    )
    for filename, metadata in OFFICIAL_FILES.items():
        lines.append(
            f"- `{metadata['source_path']}`：SHA-256 "
            f"`{metadata['sha256']}`。"
        )
    lines.extend(
        [
            "- 本地对照：`artifacts/hiddenbench-stability-20260729.summary.csv`。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=ROOT / ".tmp" / "hiddenbench-official",
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "hiddenbench" / "benchmark.json",
    )
    parser.add_argument(
        "--local-summary",
        type=Path,
        default=(
            ROOT
            / "artifacts"
            / "hiddenbench-stability-20260729.summary.csv"
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=(
            ROOT
            / "reports"
            / "HiddenBench_官方GPT4.1四题对照_2026-07-30.csv"
        ),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=(
            ROOT
            / "reports"
            / "HiddenBench_官方GPT4.1四题对照_2026-07-30.md"
        ),
    )
    args = parser.parse_args()
    rows = build_rows(
        official_dir=args.official_dir,
        benchmark_path=args.benchmark,
        local_summary_path=args.local_summary,
    )
    write_csv(rows, args.output_csv)
    write_markdown(rows, args.output_md)
    print(args.output_csv)
    print(args.output_md)


if __name__ == "__main__":
    main()
