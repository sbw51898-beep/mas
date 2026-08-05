from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


NAVY = "#17365D"
BLUE = "#2E74B5"
PALE_BLUE = "#EAF2F8"
PALE_GOLD = "#FFF4D6"
PALE_GREEN = "#E8F5E9"
PALE_RED = "#FCE8E6"
GRAY = "#5B6573"
LINE = "#8B98A7"


def _configure_fonts() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
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
    fill: str = PALE_BLUE,
    edge: str = BLUE,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=1.7,
        edgecolor=edge,
        facecolor=fill,
    )
    axis.add_patch(patch)
    axis.text(x + width / 2, y + height * 0.64, title, ha="center", va="center", fontsize=13, weight="bold", color=NAVY)
    axis.text(x + width / 2, y + height * 0.30, detail, ha="center", va="center", fontsize=9.2, color=GRAY, linespacing=1.25)


def _arrow(axis, start: tuple[float, float], end: tuple[float, float], *, color: str = LINE) -> None:
    axis.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.5,
            color=color,
            shrinkA=4,
            shrinkB=4,
        )
    )


def _new_canvas(title: str, subtitle: str):
    figure, axis = plt.subplots(figsize=(12, 6.75), dpi=160)
    figure.patch.set_facecolor("white")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    axis.text(0.04, 0.945, title, fontsize=20, weight="bold", color=NAVY, va="top")
    axis.text(0.04, 0.895, subtitle, fontsize=10.5, color=GRAY, va="top")
    return figure, axis


def _draw_architecture(path: Path, dpi: int = 200) -> None:
    figure, axis = _new_canvas(
        "基于 MAF 的信息披露治理系统结构",
        "MAF 只负责 Agent/模型执行；调度、披露、投票和审计由项目代码实现",
    )
    y = 0.58
    w = 0.15
    h = 0.18
    xs = [0.04, 0.225, 0.41, 0.595, 0.78]
    _box(axis, xs[0], y, w, h, "HiddenBench 任务", "公共背景\n四条私有事实", fill=PALE_GOLD, edge="#C69320")
    _box(axis, xs[1], y, w, h, "事实分配", "pair seed 仅控制\n私有事实归属")
    _box(axis, xs[2], y, w, h, "MAF 执行层", "4 个 Agent\n调用 DeepSeek", fill=PALE_GREEN, edge="#4C8C4A")
    _box(axis, xs[3], y, w, h, "公开讨论", "固定轮转 / 动态发言\n结构化 / Reveal-All")
    _box(axis, xs[4], y, w, h, "结果评估", "多数票、披露率\n正确率与统计检验", fill=PALE_RED, edge="#B85450")
    for left, right in zip(xs, xs[1:]):
        _arrow(axis, (left + w, y + h / 2), (right, y + h / 2))

    _box(
        axis,
        0.56,
        0.23,
        0.22,
        0.16,
        "外部集中式动态调度器",
        "读取完整私有事实分配\n按内容评分选择下一位发言者",
        fill=PALE_GOLD,
        edge="#C69320",
    )
    _arrow(axis, (0.67, 0.39), (0.67, y), color="#C69320")
    _box(
        axis,
        0.79,
        0.23,
        0.17,
        0.16,
        "披露审计",
        "AI 判断 + 规则证据\n原子事实级 m/n",
        fill="#F1ECFA",
        edge="#7556A8",
    )
    _arrow(axis, (0.875, y), (0.875, 0.39), color="#7556A8")
    axis.text(0.04, 0.12, "边界：generation seed 未传给 DeepSeek；因此重复实验控制事实分配，但不保证逐字生成可复现。", fontsize=10.2, color=GRAY)
    figure.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _draw_experiment_flow(path: Path, dpi: int = 200) -> None:
    figure, axis = _new_canvas(
        "HiddenBench 对照实验流程",
        "相同任务、相同模型和相同预算下比较治理条件，并将探索性与确认性实验分开报告",
    )
    positions = [
        (0.05, 0.63, "任务锁定", "官方短题 ID1-ID3\n固定公共信息与答案", PALE_GOLD, "#C69320"),
        (0.28, 0.63, "成对事实分配", "相同 pair seed\n保持 Agent 私有事实一致", PALE_BLUE, BLUE),
        (0.51, 0.63, "讨论条件", "固定 / 动态\n结构化 / Reveal-All", PALE_GREEN, "#4C8C4A"),
        (0.74, 0.63, "统一预算运行", "同模型、同 Prompt\n同发言次数与重复数", PALE_BLUE, BLUE),
        (0.74, 0.28, "统计与案例分析", "Wilson 区间、McNemar\nMAST 与逐轮编码", PALE_RED, "#B85450"),
        (0.51, 0.28, "披露审计", "AI 原子判断\n规则证据与分歧复核", "#F1ECFA", "#7556A8"),
        (0.28, 0.28, "投票与正确性", "多数票 / 平票\n任务答案与错误共识", PALE_BLUE, BLUE),
        (0.05, 0.28, "结论边界", "观察、统计支持\n与尚不能证明的推测", PALE_GOLD, "#C69320"),
    ]
    w = 0.18
    h = 0.16
    for x, y, title, detail, fill, edge in positions:
        _box(axis, x, y, w, h, title, detail, fill=fill, edge=edge)
    top_centers = [(x + w, 0.71) for x, *_ in positions[:3]]
    top_targets = [(x, 0.71) for x, *_ in positions[1:4]]
    for start, end in zip(top_centers, top_targets):
        _arrow(axis, start, end)
    _arrow(axis, (0.83, 0.63), (0.83, 0.44))
    _arrow(axis, (0.74, 0.36), (0.69, 0.36))
    _arrow(axis, (0.51, 0.36), (0.46, 0.36))
    _arrow(axis, (0.28, 0.36), (0.23, 0.36))
    axis.text(0.05, 0.12, "配对原则：先冻结固定轮转轨迹和条件，再比较相同 60 次发言预算的动态机制，避免把预算差异误认为治理效果。", fontsize=10.2, color=GRAY)
    figure.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def build_figures(root: Path, output_dir: Path) -> list[Path]:
    del root
    _configure_fonts()
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture = output_dir / "maf-governance-architecture.png"
    flow = output_dir / "hiddenbench-experiment-flow.png"
    _draw_architecture(architecture)
    _draw_experiment_flow(flow)
    return [architecture, flow]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build figures for the HiddenBench paper-style report.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("reports/figures"))
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    paths = build_figures(root, output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
