import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "reports" / "data" / "hiddenbench-paper-references-20260805.json"


def test_reference_registry_is_academic_and_complete() -> None:
    references = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    assert len(references) >= 15
    assert len({item["key"] for item in references}) == len(references)
    expected_fields = {
        "key",
        "authors",
        "title",
        "venue",
        "year",
        "identifier",
        "url",
        "used_in",
    }
    for item in references:
        assert set(item) == expected_fields
        assert item["authors"].strip()
        assert item["title"].strip()
        assert item["venue"].strip()
        assert isinstance(item["year"], int)
        assert item["identifier"].strip()
        assert item["url"].startswith("https://")
        assert item["used_in"]


def test_reference_registry_covers_required_topics() -> None:
    references = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    keys = {item["key"] for item in references}

    assert {
        "hiddenbench",
        "mast",
        "multiagent_debate",
        "autogen",
        "llm_mas_survey",
        "metagpt",
        "chatdev",
        "agentverse",
    } <= keys
