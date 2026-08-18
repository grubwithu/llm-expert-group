import json

import httpx
import pytest

from app.adapters import AnthropicMessagesAdapter, OpenAIResponsesAdapter
from app.config import ModelConfig


@pytest.mark.asyncio
async def test_openai_responses_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "ok"}]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="openai_responses", model="model-x",
        api_url="https://gateway.example/v1", api_key="secret", params={"store": False},
    )
    text = await OpenAIResponsesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert text == "ok"
    assert seen["url"] == "https://gateway.example/v1/responses"
    assert seen["auth"] == "Bearer secret"
    assert seen["json"] == {"model": "model-x", "instructions": "sys", "input": "hello", "store": False}


@pytest.mark.asyncio
async def test_anthropic_messages_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="anthropic_messages", model="claude-x",
        api_url="https://anthropic-gateway.example/v1", api_key="secret", params={"max_tokens": 777},
    )
    text = await AnthropicMessagesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert text == "ok"
    assert seen["url"] == "https://anthropic-gateway.example/v1/messages"
    assert seen["key"] == "secret"
    assert seen["version"] == "2023-06-01"
    assert seen["json"]["system"] == "sys"
    assert seen["json"]["messages"] == [{"role": "user", "content": "hello"}]
    assert seen["json"]["max_tokens"] == 777
