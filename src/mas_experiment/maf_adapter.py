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

from mas_experiment.beliefs import (
    normalize_probabilities,
    validate_answer_matches_probabilities,
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


_DEEPSEEK_OPTIONS = {
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "extra_body": {"thinking": {"type": "disabled"}},
}


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "to_dict"):
        dumped = value.to_dict()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _sum_usage(
    usage_records: list[dict[str, Any]],
) -> dict[str, int | float]:
    totals: dict[str, int | float] = {}
    for usage in usage_records:
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return totals


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
        context_sections = [
            section
            for section in (
                question.public_context,
                question.private_context_for(role.agent_id),
            )
            if section
        ]
        context = "\n".join(context_sections) or "(none)"
        prompt = (
            f"Task context:\n{context}\n\n"
            f"Question: {question.prompt}\n{options}\n\n"
            f"Public discussion:\n{history or '(none)'}\n\n"
            "Return only a JSON object with answer, probabilities for every "
            "option summing to 1, and concise reasoning."
        )
        agent = self._agents_by_id[role.agent_id]
        request_prompt = prompt
        usage_records: list[dict[str, Any]] = []
        request_ids: list[str] = []
        raw_text = ""
        answer = ""
        probabilities: dict[str, float] = {}
        answer_tie_break = False
        reasoning = ""
        repair_requests = 0
        result: Any = None
        for attempt in range(2):
            result = await agent.run(
                request_prompt,
                options=dict(_DEEPSEEK_OPTIONS),
            )
            raw_text = _extract_text(result)
            usage_records.append(
                _plain_mapping(getattr(result, "usage_details", None))
            )
            response_id = getattr(result, "response_id", None)
            if response_id:
                request_ids.append(str(response_id))
            try:
                payload = _parse_json_object(raw_text)
                answer = str(payload["answer"]).strip().upper()
                probabilities = normalize_probabilities(
                    question,
                    payload["probabilities"],
                )
                _, answer_tie_break = (
                    validate_answer_matches_probabilities(
                        question,
                        answer,
                        probabilities,
                    )
                )
                reasoning = str(payload["reasoning"]).strip()
                break
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                if attempt == 1:
                    raise ValueError(
                        "model response invalid after one repair request"
                    ) from error
                repair_requests = 1
                request_prompt = (
                    "Repair the following invalid JSON response. Return only "
                    "one JSON object with answer, probabilities for every "
                    f"option {tuple(question.options)} summing to 1, and "
                    "concise reasoning. The answer must be the first "
                    "highest-probability option in the stated option order.\n\n"
                    f"Invalid response:\n{raw_text}"
                )

        response_key = (
            f"{role.agent_id}|{round_index}|{raw_text}"
        ).encode("utf-8")
        additional = _plain_mapping(
            getattr(result, "additional_properties", None)
        )
        return AgentResponse(
            response_id=hashlib.sha256(response_key).hexdigest()[:16],
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            probabilities=probabilities,
            reasoning=reasoning,
            raw_text=raw_text,
            changed_from_previous=False,
            answer_tie_break=answer_tie_break,
            provider_metadata={
                "provider": "deepseek",
                "model": additional.get(
                    "model",
                    "deepseek-v4-flash",
                ),
                "thinking": "disabled",
                "temperature": 0,
                "repair_requests": repair_requests,
                "api_requests": 1 + repair_requests,
                "usage": _sum_usage(usage_records),
                "request_id": request_ids[-1] if request_ids else None,
                "request_ids": request_ids,
            },
        )
