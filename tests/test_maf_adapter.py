from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from mas_experiment.datasets import (
    AGENT_ROLES,
    FORMAL_PILOT_QUESTION,
    FORMAL_PILOT_ROLES,
    QUESTIONS,
)
from mas_experiment.maf_adapter import (
    MAFModelProvider,
    build_maf_concurrent,
    build_maf_group_chat,
    create_maf_agents,
    maf_runtime_info,
)
from mas_experiment.providers import OpenAICompatibleSettings


def test_maf_builds_concurrent_and_group_chat_without_network_call() -> None:
    settings = OpenAICompatibleSettings(
        api_key=SecretStr("test-key"),
        base_url="https://example.test/v1",
        model="test-model",
    )

    agents = create_maf_agents(settings, AGENT_ROLES)
    concurrent = build_maf_concurrent(agents)
    group_chat = build_maf_group_chat(
        agents,
        mode="round_robin",
        max_turns=3,
    )

    assert len(agents) == 3
    assert concurrent is not None
    assert group_chat is not None


def test_maf_runtime_info_reports_installed_version() -> None:
    info = maf_runtime_info()

    assert info["agent_framework"] != "not-installed"
    assert info["concurrent_builder"] == "ConcurrentBuilder"
    assert info["group_chat_builder"] == "GroupChatBuilder"


@pytest.mark.asyncio
async def test_maf_model_provider_parses_structured_agent_response() -> None:
    class FakeAgent:
        async def run(
            self,
            prompt: str,
            *,
            options: dict | None = None,
        ) -> SimpleNamespace:
            assert "What is 7 multiplied by 8?" in prompt
            return SimpleNamespace(
                text=(
                    '{"answer":"B","probabilities":'
                    '{"A":0.03,"B":0.9,"C":0.04,"D":0.03},'
                    '"reasoning":"7 x 8 = 56"}'
                )
            )

    provider = MAFModelProvider({"agent-a": FakeAgent()})

    response = await provider.generate(
        question=QUESTIONS[0],
        role=AGENT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )

    assert response.answer == "B"
    assert response.confidence == pytest.approx(0.9)
    assert response.probabilities["B"] == pytest.approx(0.9)
    assert response.reasoning == "7 x 8 = 56"


@pytest.mark.asyncio
async def test_prompt_contains_only_the_selected_agents_private_context() -> None:
    class CapturingAgent:
        prompt = ""

        async def run(
            self,
            prompt: str,
            *,
            options: dict | None = None,
        ) -> SimpleNamespace:
            self.prompt = prompt
            return SimpleNamespace(
                text=(
                    '{"answer":"A","probabilities":'
                    '{"A":0.7,"B":0.1,"C":0.1,"D":0.1},'
                    '"reasoning":"Reliability favors A."}'
                )
            )

    agent = CapturingAgent()
    provider = MAFModelProvider({"agent-a": agent})

    await provider.generate(
        question=FORMAL_PILOT_QUESTION,
        role=FORMAL_PILOT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )

    assert "Reliability scores: A=95, B=75, C=85, D=65" in agent.prompt
    assert "Security scores:" not in agent.prompt
    assert "Cost advantage scores:" not in agent.prompt
    assert "correct answer" not in agent.prompt.lower()


@pytest.mark.asyncio
async def test_deepseek_request_disables_thinking_and_temperature_is_zero() -> None:
    class CapturingAgent:
        options: dict = {}

        async def run(
            self,
            prompt: str,
            *,
            options: dict | None = None,
        ) -> SimpleNamespace:
            self.options = options or {}
            return SimpleNamespace(
                text=(
                    '{"answer":"C","probabilities":'
                    '{"A":0.1,"B":0.2,"C":0.6,"D":0.1},'
                    '"reasoning":"Combined evidence favors C."}'
                ),
                response_id="request-1",
                usage_details={"input_token_count": 10, "output_token_count": 5},
                additional_properties={"model": "deepseek-v4-flash"},
            )

    agent = CapturingAgent()
    provider = MAFModelProvider({"agent-a": agent})

    response = await provider.generate(
        question=FORMAL_PILOT_QUESTION,
        role=FORMAL_PILOT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )

    assert agent.options["temperature"] == 0
    assert agent.options["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert agent.options["response_format"] == {"type": "json_object"}
    assert response.provider_metadata["request_id"] == "request-1"
    assert response.provider_metadata["usage"]["input_token_count"] == 10


@pytest.mark.asyncio
async def test_invalid_payload_gets_one_repair_request() -> None:
    class SequencedAgent:
        def __init__(self) -> None:
            self.outputs = [
                "not json",
                (
                    '{"answer":"C","probabilities":'
                    '{"A":0.1,"B":0.2,"C":0.6,"D":0.1},'
                    '"reasoning":"Repaired output."}'
                ),
            ]
            self.prompts: list[str] = []

        async def run(
            self,
            prompt: str,
            *,
            options: dict | None = None,
        ) -> SimpleNamespace:
            self.prompts.append(prompt)
            return SimpleNamespace(
                text=self.outputs[len(self.prompts) - 1],
                response_id=f"request-{len(self.prompts)}",
                usage_details=None,
                additional_properties={},
            )

    agent = SequencedAgent()
    provider = MAFModelProvider({"agent-a": agent})

    response = await provider.generate(
        question=FORMAL_PILOT_QUESTION,
        role=FORMAL_PILOT_ROLES[0],
        round_index=0,
        visible_messages=(),
        seed=20260727,
    )

    assert len(agent.prompts) == 2
    assert "Repair the following invalid JSON response" in agent.prompts[1]
    assert response.provider_metadata["repair_requests"] == 1
