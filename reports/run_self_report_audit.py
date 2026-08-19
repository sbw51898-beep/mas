"""Run a supplementary AI-self-reported disclosure audit on frozen runs.

This is deliberately separate from the frozen atomic audit.  The frozen audit
keeps the model from calculating a percentage; this supplementary audit asks
the same model to return both the fact-level labels and its own count/rate so
the two can be compared explicitly.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mas_experiment.hiddenbench_atomic_disclosure import (  # noqa: E402
    decompose_private_facts,
    validate_atomic_evidence,
)
from mas_experiment.hiddenbench_domain import HiddenBenchRawRun  # noqa: E402


INPUT = ROOT / "artifacts" / "hiddenbench-confirmatory-20260804.jsonl"
OUTPUT = ROOT / "artifacts" / "hiddenbench-confirmatory-20260804.self-report-audits.jsonl"
MODEL = os.environ.get("OPENAI_CHAT_COMPLETION_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/")
API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _load_runs() -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    with INPUT.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            condition = record["key"]["condition"]
            if condition not in {"fixed-60", "dynamic-60"}:
                continue
            selected.append(record)
    selected.sort(
        key=lambda r: (
            r["key"]["condition"],
            int(r["key"]["task_id"]),
            int(r["key"]["repetition"]),
        )
    )
    if len(selected) != 60:
        raise RuntimeError(f"expected 60 ordinary runs, found {len(selected)}")
    return selected


def _prompt(record: dict[str, Any]) -> str:
    run = record["run"]
    facts = decompose_private_facts(_assignment_proxy(record))
    facts_text = "\n".join(
        f"- {fact.fact_id} | owner={fact.owner_agent_id} | claim={json.dumps(fact.text, ensure_ascii=False)}"
        for fact in facts
    )
    messages_text = "\n".join(
        f"{message['message_id']} | {message['agent_id']} | {message['content']}"
        for message in run["discussion_messages"]
    )
    shape = {
        "facts": [
            {
                "fact_id": "atomic-fact:example",
                "owner_agent_id": "agent-a",
                "disclosed": True,
                "evidence_message_ids": ["message-id"],
                "evidence_quote": "exact substring",
                "reason": "short reason",
                "confidence": 0.95,
            }
        ],
        "reported_disclosure_count": 1,
        "reported_disclosure_denominator": len(facts),
        "reported_disclosure_rate": 0.25,
    }
    return (
        "Determine whether every atomic private claim was disclosed in the public discussion.\n\n"
        "Rules:\n"
        "1. Only an owner-authored message can disclose that owner's fact.\n"
        "2. A faithful paraphrase counts; a polarity reversal, contradiction, or decision-relevant omission does not.\n"
        "3. For disclosed=true, cite at least one owner-authored message ID and copy one exact non-empty substring from it.\n"
        "4. For disclosed=false, return an empty message-ID list and quote.\n"
        "5. Return exactly one judgment for every fact ID.\n"
        "6. After judging all facts, independently count how many are disclosed and calculate your own rate as count/denominator.\n"
        "7. Do not infer a rate from any precomputed field; calculate it from your own fact judgments.\n\n"
        f"ATOMIC PRIVATE FACTS:\n{facts_text}\n\n"
        f"PUBLIC MESSAGES:\n{messages_text}\n\n"
        "Return strict JSON only in this shape (the example values are placeholders):\n"
        f"{json.dumps(shape, ensure_ascii=False)}"
    )


class _Assignment:
    """Small object exposing the fields required by decompose_private_facts."""

    def __init__(self, task_id: int, private_information: dict[str, str]) -> None:
        self.task_id = task_id
        self.private_information = private_information


def _assignment_proxy(record: dict[str, Any]) -> _Assignment:
    run = record["run"]
    assignment = run["assignment"]
    return _Assignment(
        int(record["key"]["task_id"]),
        dict(assignment["private_information"]),
    )


def _call(prompt: str) -> tuple[str, dict[str, Any]]:
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    payload = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You are a strict evidence auditor. Return JSON only and never invent evidence.",
            },
            {"role": "user", "content": prompt},
        ],
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    request = Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        raise RuntimeError(str(error)) from error
    content = body["choices"][0]["message"]["content"]
    return content, body.get("usage", {})


def _parse(content: str, record: dict[str, Any]) -> dict[str, Any]:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("self-report response is not JSON")
    payload = json.loads(content[start : end + 1])
    facts = decompose_private_facts(_assignment_proxy(record))
    expected_ids = {fact.fact_id for fact in facts}
    judgments = tuple(
        _judgment_model(item)
        for item in payload.get("facts", [])
    )
    validate_atomic_evidence(
        HiddenBenchRawRun.model_validate(record["run"]),
        facts,
        judgments,
    )
    if {item.fact_id for item in judgments} != expected_ids:
        raise ValueError("self-report fact IDs do not match frozen facts")
    count = sum(bool(item.disclosed) for item in judgments)
    denominator = len(judgments)
    reported_count = int(payload["reported_disclosure_count"])
    reported_denominator = int(payload["reported_disclosure_denominator"])
    reported_rate = float(payload["reported_disclosure_rate"])
    return {
        "facts": [item.model_dump(mode="json") for item in judgments],
        "program_count": count,
        "program_denominator": denominator,
        "program_rate": count / denominator,
        "reported_count": reported_count,
        "reported_denominator": reported_denominator,
        "reported_rate": reported_rate,
        "count_match": reported_count == count,
        "denominator_match": reported_denominator == denominator,
        "rate_difference": reported_rate - (count / denominator),
    }


def _judgment_model(item: dict[str, Any]):
    from mas_experiment.hiddenbench_atomic_disclosure import AtomicDisclosureJudgment

    return AtomicDisclosureJudgment.model_validate(item)


def _one(record: dict[str, Any]) -> dict[str, Any]:
    content, usage = _call(_prompt(record))
    parsed = _parse(content, record)
    return {
        "key": record["key"],
        "run_id": record["run"]["run_id"],
        "judge_model": MODEL,
        "judge_prompt_version": "hiddenbench-self-report-disclosure-v1",
        "raw_response": content,
        "usage": usage,
        **parsed,
    }


def main() -> None:
    runs = _load_runs()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_one, record): record for record in runs}
        for index, future in enumerate(as_completed(futures), start=1):
            record = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"[{index}/60] ok {record['key']}", flush=True)
            except Exception as error:  # pragma: no cover - live API failures
                failure = {"key": record["key"], "error": repr(error)}
                failures.append(failure)
                print(f"[{index}/60] failed {failure}", flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} self-report audits failed: {failures[:3]}")
    results.sort(key=lambda item: (item["key"]["condition"], item["key"]["task_id"], item["key"]["repetition"]))
    OUTPUT.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in results) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
