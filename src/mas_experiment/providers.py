from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, SecretStr

from mas_experiment.domain import (
    AgentResponse,
    AgentRole,
    Message,
    Question,
)


class ConfigurationError(ValueError):
    """Raised when a real-model provider is not fully configured."""


class OpenAICompatibleSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> OpenAICompatibleSettings:
        names = (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_CHAT_COMPLETION_MODEL",
        )
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ConfigurationError(
                "missing required environment variables: " + ", ".join(missing)
            )
        return cls(
            api_key=SecretStr(os.environ["OPENAI_API_KEY"]),
            base_url=os.environ["OPENAI_BASE_URL"],
            model=os.environ["OPENAI_CHAT_COMPLETION_MODEL"],
        )


class DeterministicProvider:
    """Offline provider for validating mechanics, never model quality."""

    async def generate(
        self,
        *,
        question: Question,
        role: AgentRole,
        round_index: int,
        visible_messages: tuple[Message, ...],
        seed: int,
    ) -> AgentResponse:
        visible_ids = ",".join(message.message_id for message in visible_messages)
        payload = (
            f"{seed}|{question.question_id}|{role.agent_id}|"
            f"{round_index}|{visible_ids}"
        )
        digest = hashlib.sha256(payload.encode("utf-8")).digest()
        options = tuple(question.options)
        weights = [digest[index] + 1 for index in range(len(options))]
        total = sum(weights)
        probabilities = {
            option: weight / total
            for option, weight in zip(options, weights, strict=True)
        }
        maximum = max(probabilities.values())
        answer = next(
            option
            for option in options
            if probabilities[option] == maximum
        )
        raw_payload = {
            "answer": answer,
            "probabilities": probabilities,
            "reasoning": (
                f"Offline deterministic response for {question.question_id} "
                f"from {role.agent_id}."
            ),
        }
        timestamp_offset = int.from_bytes(digest[2:6], "big") % (365 * 24 * 3600)
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds=timestamp_offset
        )
        return AgentResponse(
            response_id=digest.hex()[:16],
            agent_id=role.agent_id,
            round_index=round_index,
            answer=answer,
            probabilities=probabilities,
            reasoning=raw_payload["reasoning"],
            raw_text=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
            changed_from_previous=False,
            timestamp=timestamp,
        )
