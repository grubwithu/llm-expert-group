from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import ModelConfig, ReasoningConfig


class ModelAdapter(ABC):
    def __init__(self, config: ModelConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client

    @abstractmethod
    async def generate(self, *, system: str, prompt: str) -> str:
        raise NotImplementedError

    def _client(self) -> httpx.AsyncClient:
        return self.client or httpx.AsyncClient(timeout=self.config.timeout_seconds)

    async def _post(self, endpoint: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self.client is None
        client = self._client()
        try:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        finally:
            if owns_client:
                await client.aclose()



def _openai_reasoning_payload(reasoning: ReasoningConfig | None) -> dict[str, Any]:
    if reasoning is None:
        return {}
    if reasoning.mode in {"adaptive", "budget"} or reasoning.budget_tokens is not None:
        raise ValueError("OpenAI protocols do not support reasoning.mode=adaptive/budget or budget_tokens")
    effort = "none" if reasoning.mode == "disabled" else reasoning.effort
    return {"reasoning": {"effort": effort}} if effort else {}


def _openai_chat_reasoning_payload(reasoning: ReasoningConfig | None) -> dict[str, Any]:
    if reasoning is None:
        return {}
    if reasoning.mode in {"adaptive", "budget"} or reasoning.budget_tokens is not None:
        raise ValueError("OpenAI Chat Completions does not support reasoning.mode=adaptive/budget or budget_tokens")
    effort = "none" if reasoning.mode == "disabled" else reasoning.effort
    return {"reasoning_effort": effort} if effort else {}


def _anthropic_reasoning_payload(reasoning: ReasoningConfig | None) -> dict[str, Any]:
    if reasoning is None:
        return {}

    mode = reasoning.mode
    if mode == "auto":
        if reasoning.budget_tokens is not None:
            mode = "budget"
        elif reasoning.effort is not None:
            mode = "adaptive"
        else:
            return {}

    if mode == "budget":
        if reasoning.budget_tokens is None:
            raise ValueError("Anthropic reasoning.mode=budget requires budget_tokens")
        return {"thinking": {"type": "enabled", "budget_tokens": reasoning.budget_tokens}}
    if mode == "adaptive":
        payload: dict[str, Any] = {"thinking": {"type": "adaptive"}}
        if reasoning.effort:
            payload["output_config"] = {"effort": reasoning.effort}
        return payload
    if mode == "disabled":
        return {"thinking": {"type": "disabled"}}
    raise ValueError(f"unsupported Anthropic reasoning mode: {mode}")

def _endpoint(base: str, suffix: str) -> str:
    value = base.rstrip("/")
    path = urlparse(value).path.rstrip("/")
    if path.endswith(suffix):
        return value
    if path.endswith("/v1"):
        return value + suffix
    return value + "/v1" + suffix


class OpenAIResponsesAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "instructions": system,
            "input": prompt,
        }
        payload.update(_openai_reasoning_payload(self.config.reasoning))
        payload.update(self.config.params)
        headers = {
            "Authorization": f"Bearer {self.config.resolved_api_key()}",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        data = await self._post(_endpoint(self.config.api_url, "/responses"), headers, payload)
        return parse_openai_responses_text(data)


class AnthropicMessagesAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        payload.update(_anthropic_reasoning_payload(self.config.reasoning))
        payload.update(self.config.params)
        thinking = payload.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type") in {"enabled", "adaptive"}:
            if "temperature" in payload and payload["temperature"] != 1:
                raise ValueError("Anthropic thinking requires temperature=1 or an omitted temperature")
            budget = thinking.get("budget_tokens")
            max_tokens = payload.get("max_tokens")
            if isinstance(budget, int) and isinstance(max_tokens, int) and budget >= max_tokens:
                raise ValueError("Anthropic budget_tokens must be less than max_tokens")
        headers = {
            "x-api-key": self.config.resolved_api_key(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        data = await self._post(_endpoint(self.config.api_url, "/messages"), headers, payload)
        return parse_anthropic_messages_text(data)


class OpenAIChatCompletionsAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        payload.update(_openai_chat_reasoning_payload(self.config.reasoning))
        payload.update(self.config.params)
        headers = {
            "Authorization": f"Bearer {self.config.resolved_api_key()}",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        data = await self._post(_endpoint(self.config.api_url, "/chat/completions"), headers, payload)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI-compatible chat response did not contain choices")
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("text"))
        raise RuntimeError("unable to extract text from OpenAI-compatible chat response")


def parse_openai_responses_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    if chunks:
        return "\n".join(chunks)
    raise RuntimeError("unable to extract text from OpenAI Responses payload")


def parse_anthropic_messages_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for part in data.get("content", []) or []:
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    if chunks:
        return "\n".join(chunks)
    raise RuntimeError("unable to extract text from Anthropic Messages payload")


def build_adapter(config: ModelConfig) -> ModelAdapter:
    if config.protocol == "openai_responses":
        return OpenAIResponsesAdapter(config)
    if config.protocol == "anthropic_messages":
        return AnthropicMessagesAdapter(config)
    if config.protocol == "openai_chat_completions":
        return OpenAIChatCompletionsAdapter(config)
    raise ValueError(f"unsupported protocol: {config.protocol}")
