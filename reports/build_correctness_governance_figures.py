from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


NAVY = "#17365D"
BLUE = "#2E74B5"
GRAY = "#5B6573"
LINE = "#8B98A7"
PALE_BLUE = "#EAF2F8"
PALE_GOLD = "#FFF4D6"
PALE_GREEN = "#E8F5E9"
PALE_RED = "#FCE8E6"
PALE_PURPLE = "#F1ECFA"


def _configure_fonts() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _box(
    axis,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    detail: str,
    *,
    fill: str,
    edge: str,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.016",
        linewidth=1.6,
        edgecolor=edge,
        facecolor=fill,
    )
    axis.add_patch(patch)
    axis.text(
        x + width / 2,
        y + height * 0.67,
        title,
        ha="center",
        va="center",
        fontsize=12.5,
        weight="bold",
        color=NAVY,
    )
    axis.text(
        x + width / 2,
        y + height * 0.30,
        detail,
        ha="center",
        va="center",
        fontsize=8.8,
        color=GRAY,
        linespacing=1.25,
    )


def _arrow(
    axis,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = LINE,
    connectionstyle: str = "arc3",
) -> None:
    axis.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.45,
            color=color,
            connectionstyle=connectionstyle,
            shrinkA=4,
            shrinkB=4,
        )
    )


def build_correctness_governance_figure(
    output: Path, dpi: int = 200
) -> Path:
    _configure_fonts()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(12, 6.75), dpi=160)
    figure.patch.set_facecolor("white")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    axis.text(
        0.04,
        0.95,
        "多智能体正确性治理：从错误链路到针对性干预",
        fontsize=20,
        weight="bold",
        color=NAVY,
        va="top",
    )
    axis.text(
        0.04,
        0.895,
        "最终正确率是结果指标；披露、利用、解释、协调与投票指标用于定位错误所在环节",
        fontsize=10.5,
        color=GRAY,
        va="top",
    )

    stages = [
        (
            0.035,
            "私有事实",
            "信息分散给不同 Agent\n单个 Agent 不掌握全景",
            PALE_GOLD,
            "#C69320",
        ),
        (
            0.225,
            "公开",
            "观测：披露率、首次轮次\n干预：结构化交换",
            PALE_BLUE,
            BLUE,
        ),
        (
            0.415,
            "读取与利用",
            "观测：后续引用、立场变化\n干预：证据覆盖提醒",
            PALE_GREEN,
            "#4C8C4A",
        ),
        (
            0.605,
            "解释与协调",
            "观测：事实-理由一致性\n干预：冲突核验、保留异议",
            PALE_PURPLE,
            "#7556A8",
        ),
        (
            0.795,
            "决策",
            "观测：投票、错误共识\n干预：异常复审、二次投票",
            PALE_RED,
            "#B85450",
        ),
    ]
    width = 0.16
    height = 0.19
    y = 0.56
    for x, title, detail, fill, edge in stages:
        _box(
            axis,
            x,
            y,
            width,
            height,
            title,
            detail,
            fill=fill,
            edge=edge,
        )
    for left, right in zip(stages, stages[1:]):
        _arrow(
            axis,
            (left[0] + width, y + height / 2),
            (right[0], y + height / 2),
        )

    _box(
        axis,
        0.69,
        0.24,
        0.24,
        0.15,
        "决策评估",
        "最终正确率、理由-投票一致性\n判断错误是否真正被消除",
        fill=PALE_RED,
        edge="#B85450",
    )
    _arrow(axis, (0.875, y), (0.82, 0.39), color="#B85450")

    _box(
        axis,
        0.38,
        0.24,
        0.24,
        0.15,
        "选择针对性干预",
        "先定位公开、利用、解释或决策失败\n再选协议，不用单一机制处理全部错误",
        fill=PALE_GOLD,
        edge="#C69320",
    )
    _arrow(axis, (0.69, 0.315), (0.62, 0.315), color="#C69320")
    _arrow(
        axis,
        (0.50, 0.24),
        (0.31, y),
        color="#C69320",
        connectionstyle="arc3,rad=-0.22",
    )

    axis.text(
        0.04,
        0.12,
        "治理原则：信息最终全部出现并不等于被及时、正确地使用；共识也不能替代正确性检验。",
        fontsize=10.2,
        color=GRAY,
    )
    figure.savefig(output, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the MAS correctness-governance loop figure."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/figures/mas-correctness-governance-loop.png"),
    )
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    print(build_correctness_governance_figure(args.output, args.dpi))


if __name__ == "__main__":
    main()
