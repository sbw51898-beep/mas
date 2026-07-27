from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Mapping
from typing import Any

from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from agent_framework.orchestrations import (
    ConcurrentBuilder,
    GroupChatBuilder,
    GroupChatState,
)

from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    Message,
    Question,
)
from mas_experiment.providers import OpenAICompatibleSettings


def maf_runtime_info() -> dict[str, str]:
    return {
        "agent_framework": importlib.metadata.version("agent-framework-core"),
        "orchestrations": importlib.metadata.version(
            "agent-framework-orchestrations"
        ),
        "openai_provider": importlib.metadata.version(
            "agent-framework-openai"
        ),
        "concurrent_builder": ConcurrentBuilder.__name__,
        "group_chat_builder": GroupChatBuilder.__name__,
    }


def create_maf_agents(
    settings: OpenAICompatibleSettings,
    roles: tuple[AgentRole, ...],
) -> tuple[Agent, ...]:
    client = OpenAIChatCompletionClient(
        model=settings.model,
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
    )
    return tuple(
        Agent(
            client,
            instructions=role.system_prompt,
            name=role.agent_id,
            description=role.name,
        )
        for role in roles
    )


def build_maf_concurrent(agents: tuple[Agent, ...]):
    return ConcurrentBuilder(participants=agents).build()


def _round_robin_selector(state: GroupChatState) -> str:
    names = list(state.participants)
    if not names:
        raise ValueError("group chat requires at least one participant")
    return names[state.current_round % len(names)]


def build_maf_group_chat(
    agents: tuple[Agent, ...],
    *,
    mode: str,
    max_turns: int,
):
    if mode != "round_robin":
        raise ValueError("MAF smoke group chat currently supports round_robin")
    return GroupChatBuilder(
        participants=agents,
        selection_func=_round_robin_selector,
        max_rounds=max_turns,
    ).build()


def _extract_text(result: Any) -> str:
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    messages = getattr(result, "messages", None)
    if messages:
        message_text = getattr(messages[-1], "text", None)
        if isinstance(message_text, str):
            return message_text
    return str(result)


def _parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


class MAFModelProvider:
    def __init__(self, agents_by_id: Mapping[str, Any]) -> None:
        self._agents_by_id = dict(agents_by_id)

    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        del seed
        options = "\n".join(
            f"{label}. {text}" for label, text in question.options.items()
        )
        history = "\n".join(
            f"{message.speaker}: {message.content}"
            for message in visible_messages
        )
        prompt = (
            f"Question: {question.prompt}\n{options}\n\n"
            f"Public discussion:\n{history or '(none)'}\n\n"
            "Return only a JSON object with answer, confidence from 0 to 1, "
            "and concise reasoning."
        )
        agent = self._agents_by_id[role.agent_id]
        result = await agent.run(prompt)
        raw_text = _extract_text(result)
        payload = _parse_json_object(raw_text)
        answer = str(payload["answer"]).strip().upper()
        confidence = float(payload["confidence"])
        reasoning = str(payload["reasoning"]).strip()
        response_key = (
            f"{role.agent_id}|{round_index}|{raw_text}"
        ).encode("utf-8")
        return AgentResponse(
            response_id=hashlib.sha256(response_key).hexdigest()[:16],
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            confidence=confidence,
            reasoning=reasoning,
            raw_text=raw_text,
            changed_from_previous=False,
        )
