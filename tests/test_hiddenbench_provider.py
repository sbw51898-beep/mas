from __future__ import annotations

import pytest

from mas_experiment.providers import ScriptedPromptProvider


@pytest.mark.asyncio
async def test_scripted_provider_returns_each_output_once_and_records_calls() -> None:
    provider = ScriptedPromptProvider(("first", "second"))

    first = await provider.complete(
        agent_id="agent-a",
        system_prompt="system-a",
        user_prompt="user-a",
        seed=1,
        json_response=False,
    )
    second = await provider.complete(
        agent_id="agent-b",
        system_prompt="system-b",
        user_prompt="user-b",
        seed=2,
        json_response=True,
    )

    assert first.text == "first"
    assert second.text == "second"
    assert first.provider_metadata["provider"] == "scripted-offline"
    assert first.provider_metadata["api_requests"] == 0
    assert provider.calls[0]["agent_id"] == "agent-a"
    assert provider.calls[1]["json_response"] is True


@pytest.mark.asyncio
async def test_scripted_provider_fails_when_script_is_exhausted() -> None:
    provider = ScriptedPromptProvider(("only",))
    request = {
        "agent_id": "agent-a",
        "system_prompt": "system",
        "user_prompt": "user",
        "seed": 1,
        "json_response": False,
    }
    await provider.complete(**request)

    with pytest.raises(RuntimeError, match="script exhausted after 1 calls"):
        await provider.complete(**request)
