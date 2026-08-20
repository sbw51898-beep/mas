"""Build two label-blind human disclosure-review workbooks.

The source queue contains only the evidence shown to reviewers.  Existing AI
and rule labels stay in frozen artifacts and are never copied into either
review workbook.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUEUE_RELATIVE_PATH = Path(
    "artifacts/hiddenbench-stability-20260729.blind-review.queue.csv"
)
REVIEWER_A_NAME = "盲审签核表_审阅者A_2026-08-17.xlsx"
REVIEWER_B_NAME = "盲审签核表_审阅者B_2026-08-17.xlsx"
MANIFEST_NAME = "dual-blind-review-pack-20260817.manifest.json"
ORDER_SEED_A = 2026081701
ORDER_SEED_B = 2026081702
ARTIFACT_BUILDER = Path(__file__).with_name(
    "build_dual_blind_review_pack_artifact.mjs"
)
DEFAULT_NODE = Path(
    "C:/Users/liuli/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/node/bin/node.exe"
)
DEFAULT_ARTIFACT_MODULE = Path(
    "C:/Users/liuli/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_queue(queue_path: Path) -> list[dict[str, Any]]:
    required = {
        "blind_id",
        "fact",
        "owner_agent_id",
        "owner_messages_json",
    }
    with queue_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("blind-review queue has missing required columns")
        rows = list(reader)
    if len(rows) != 144:
        raise ValueError(f"expected 144 blinded review rows, found {len(rows)}")

    normalized: list[dict[str, Any]] = []
    blind_ids: set[str] = set()
    for row in rows:
        blind_id = row["blind_id"].strip()
        if not blind_id or blind_id in blind_ids:
            raise ValueError("blind-review queue requires unique nonempty blind IDs")
        blind_ids.add(blind_id)
        try:
            owner_messages = json.loads(row["owner_messages_json"])
        except json.JSONDecodeError as error:
            raise ValueError(f"{blind_id} has invalid owner_messages_json") from error
        if not isinstance(owner_messages, list):
            raise ValueError(f"{blind_id} owner_messages_json must be a list")
        normalized.append(
            {
                "blind_id": blind_id,
                "fact": row["fact"].strip(),
                "owner_agent_id": row["owner_agent_id"].strip(),
                "owner_messages": owner_messages,
            }
        )
    return normalized


def _ordered_rows(rows: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    ordered = list(rows)
    random.Random(seed).shuffle(ordered)
    return ordered


def _artifact_runtime() -> tuple[Path, Path]:
    node = Path(os.environ.get("CODEX_BUNDLED_NODE", DEFAULT_NODE))
    module = Path(
        os.environ.get("CODEX_ARTIFACT_TOOL_MODULE", DEFAULT_ARTIFACT_MODULE)
    )
    if not node.exists():
        raise FileNotFoundError(f"bundled Node runtime not found: {node}")
    if not module.exists():
        raise FileNotFoundError(f"artifact-tool module not found: {module}")
    return node, module


def _build_workbook(
    *,
    reviewer_label: str,
    rows: list[dict[str, Any]],
    output: Path,
) -> None:
    if not ARTIFACT_BUILDER.exists():
        raise FileNotFoundError(ARTIFACT_BUILDER)
    node, module = _artifact_runtime()
    payload = {
        "schema_version": "hiddenbench-human-dual-blind-pack-v1",
        "reviewer_label": reviewer_label,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maf-dual-blind-pack-") as temp_dir:
        payload_path = Path(temp_dir) / "pack.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["CODEX_ARTIFACT_TOOL_MODULE"] = module.resolve().as_uri()
        result = subprocess.run(
            [str(node), str(ARTIFACT_BUILDER), str(payload_path), str(output)],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if result.returncode != 0:
        raise RuntimeError(
            "artifact-tool workbook generation failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"artifact-tool did not create {output}")


def build_dual_blind_review_pack(root: Path, output_dir: Path) -> dict[str, Path]:
    """Create reviewer A/B workbooks from the frozen 144-item blind queue."""
    root = root.resolve()
    output_dir = output_dir.resolve()
    queue_path = root / QUEUE_RELATIVE_PATH
    rows = _load_queue(queue_path)
    reviewer_a = output_dir / REVIEWER_A_NAME
    reviewer_b = output_dir / REVIEWER_B_NAME
    ordered_a = _ordered_rows(rows, seed=ORDER_SEED_A)
    ordered_b = _ordered_rows(rows, seed=ORDER_SEED_B)
    if [row["blind_id"] for row in ordered_a] == [row["blind_id"] for row in ordered_b]:
        raise ValueError("reviewer orders unexpectedly match")

    _build_workbook(
        reviewer_label="审阅者 A",
        rows=ordered_a,
        output=reviewer_a,
    )
    _build_workbook(
        reviewer_label="审阅者 B",
        rows=ordered_b,
        output=reviewer_b,
    )
    manifest = output_dir / "data" / MANIFEST_NAME
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "hiddenbench-human-dual-blind-pack-v1",
                "source_queue": str(QUEUE_RELATIVE_PATH).replace("\\", "/"),
                "source_queue_sha256": _sha256(queue_path),
                "case_count": len(rows),
                "reviewer_a": {
                    "path": reviewer_a.name,
                    "order_seed": ORDER_SEED_A,
                    "blind_ids_sha256": hashlib.sha256(
                        "\n".join(row["blind_id"] for row in ordered_a).encode("utf-8")
                    ).hexdigest(),
                },
                "reviewer_b": {
                    "path": reviewer_b.name,
                    "order_seed": ORDER_SEED_B,
                    "blind_ids_sha256": hashlib.sha256(
                        "\n".join(row["blind_id"] for row in ordered_b).encode("utf-8")
                    ).hexdigest(),
                },
                "blindness_boundary": (
                    "Neither workbook contains AI disclosure labels, rule labels, "
                    "or prior reviewer labels."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "reviewer_a": reviewer_a,
        "reviewer_b": reviewer_b,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create independently ordered human blind-review workbooks."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = args.output_dir or root / "reports"
    pack = build_dual_blind_review_pack(root, output_dir)
    print(json.dumps({key: str(value) for key, value in pack.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
