from __future__ import annotations

import pytest

from mas_experiment.datasets import AGENT_ROLES, QUESTIONS
from mas_experiment.providers import (
    ConfigurationError,
    DeterministicProvider,
    OpenAICompatibleSettings,
)


@pytest.mark.asyncio
async def test_offline_provider_is_deterministic() -> None:
    provider = DeterministicProvider()

    first = await provider.generate(
        question=QUESTIONS[0],
        role=AGENT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )
    second = await provider.generate(
        question=QUESTIONS[0],
        role=AGENT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )

    assert first == second
    assert first.answer in QUESTIONS[0].options
    assert set(first.probabilities) == set(QUESTIONS[0].options)
    assert sum(first.probabilities.values()) == pytest.approx(1.0)
    assert first.confidence == max(first.probabilities.values())


def test_settings_load_only_required_openai_compatible_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "key-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_CHAT_COMPLETION_MODEL", "example-model")

    settings = OpenAICompatibleSettings.from_env()

    assert settings.model == "example-model"
    assert settings.base_url == "https://example.test/v1"
    assert settings.api_key.get_secret_value() == "key-value"


def test_settings_fail_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_CHAT_COMPLETION_MODEL", "example-model")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        OpenAICompatibleSettings.from_env()
