from pathlib import Path

from PIL import Image

from reports.build_paper_figures import build_figures


ROOT = Path(__file__).resolve().parents[1]


def test_paper_figures_are_large_and_reproducible(tmp_path: Path) -> None:
    paths = build_figures(ROOT, tmp_path)

    assert {path.name for path in paths} == {
        "maf-governance-architecture.png",
        "hiddenbench-experiment-flow.png",
    }
    for path in paths:
        assert path.exists()
        with Image.open(path) as image:
            assert image.width >= 1600
            assert image.height >= 900


def test_paper_figures_are_not_blank(tmp_path: Path) -> None:
    paths = build_figures(ROOT, tmp_path)

    for path in paths:
        with Image.open(path).convert("RGB") as image:
            colors = image.resize((80, 45)).getcolors(maxcolors=80 * 45)
            assert colors is not None
            assert len(colors) >= 8
