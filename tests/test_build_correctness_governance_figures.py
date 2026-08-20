from pathlib import Path

from PIL import Image

from reports.build_correctness_governance_figures import (
    build_correctness_governance_figure,
)


def test_correctness_governance_figure_is_large(tmp_path: Path) -> None:
    output = tmp_path / "governance.png"

    build_correctness_governance_figure(output)

    with Image.open(output) as image:
        assert image.width >= 1800
        assert image.height >= 1000


def test_correctness_governance_figure_is_not_blank(tmp_path: Path) -> None:
    output = tmp_path / "governance.png"

    build_correctness_governance_figure(output)

    with Image.open(output).convert("RGB") as image:
        colors = image.resize((100, 56)).getcolors(maxcolors=5600)
        assert colors is not None
        assert len(colors) >= 10
