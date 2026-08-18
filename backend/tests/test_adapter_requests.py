import json

import httpx
import pytest

from app.adapters import AnthropicMessagesAdapter, OpenAIChatCompletionsAdapter, OpenAIResponsesAdapter
from app.config import ModelConfig, ReasoningConfig


@pytest.mark.asyncio
async def test_openai_responses_streams_output_text_deltas():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=(
                b'data: {"type":"response.output_text.delta","delta":"hel"}\n\n'
                b'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
                b'data: [DONE]\n\n'
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(id="x", display_name="X", protocol="openai_responses", model="model-x", api_url="https://gateway.example/v1", api_key="secret")
    adapter = OpenAIResponsesAdapter(cfg, client=client)
    chunks = [chunk async for chunk in adapter.stream(system="sys", prompt="hello")]
    await client.aclose()

    assert chunks == ["hel", "lo"]
    assert seen["json"]["stream"] is True


@pytest.mark.asyncio
async def test_openai_responses_uses_completed_event_when_gateway_omits_deltas():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            content=b'data: {"type":"response.completed","response":{"output_text":"complete text"}}\n\n',
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(id="x", display_name="X", protocol="openai_responses", model="model-x", api_url="https://gateway.example/v1", api_key="secret")
    chunks = [chunk async for chunk in OpenAIResponsesAdapter(cfg, client=client).stream(system="sys", prompt="hello")]
    await client.aclose()

    assert chunks == ["complete text"]


@pytest.mark.asyncio
async def test_anthropic_stream_falls_back_to_non_streaming_when_gateway_has_no_deltas():
    calls: list[dict] = []

    async def handler(request: httpx.Request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get("stream"):
            return httpx.Response(200, content=b"data: [DONE]\n\n")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "fallback text"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(id="x", display_name="X", protocol="anthropic_messages", model="claude-x", api_url="https://gateway.example/v1", api_key="secret")
    chunks = [chunk async for chunk in AnthropicMessagesAdapter(cfg, client=client).stream(system="sys", prompt="hello")]
    await client.aclose()

    assert chunks == ["fallback text"]
    assert [payload.get("stream") for payload in calls] == [True, None]


@pytest.mark.asyncio
async def test_openai_chat_stream_falls_back_to_non_streaming_when_gateway_has_no_deltas():
    calls: list[dict] = []

    async def handler(request: httpx.Request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get("stream"):
            return httpx.Response(200, content=b"data: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": "fallback text"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(id="x", display_name="X", protocol="openai_chat_completions", model="model-x", api_url="https://gateway.example/v1", api_key="secret")
    chunks = [chunk async for chunk in OpenAIChatCompletionsAdapter(cfg, client=client).stream(system="sys", prompt="hello")]
    await client.aclose()

    assert chunks == ["fallback text"]
    assert [payload.get("stream") for payload in calls] == [True, None]


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


@pytest.mark.asyncio
async def test_openai_responses_reasoning_effort_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "ok"}]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="openai_responses", model="model-x",
        api_url="https://gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(effort="xhigh"),
    )
    await OpenAIResponsesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert seen["json"]["reasoning"] == {"effort": "xhigh"}


@pytest.mark.asyncio
async def test_anthropic_legacy_reasoning_budget_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="anthropic_messages", model="claude-x",
        api_url="https://anthropic-gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(mode="budget", budget_tokens=6000),
        params={"max_tokens": 8192},
    )
    await AnthropicMessagesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert seen["json"]["thinking"] == {"type": "enabled", "budget_tokens": 6000}


@pytest.mark.asyncio
async def test_anthropic_adaptive_reasoning_effort_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="anthropic_messages", model="claude-x",
        api_url="https://anthropic-gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(mode="adaptive", effort="high"),
    )
    await AnthropicMessagesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert seen["json"]["thinking"] == {"type": "adaptive"}
    assert seen["json"]["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_openai_chat_reasoning_effort_wire_format():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="openai_chat_completions", model="model-x",
        api_url="https://gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(effort="high"),
    )
    await OpenAIChatCompletionsAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert seen["json"]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_raw_params_override_normalized_reasoning():
    seen = {}

    async def handler(request: httpx.Request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "ok"}]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="openai_responses", model="model-x",
        api_url="https://gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(effort="low"),
        params={"reasoning": {"effort": "high"}},
    )
    await OpenAIResponsesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert seen["json"]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_anthropic_reasoning_rejects_non_default_temperature_before_request():
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="anthropic_messages", model="claude-x",
        api_url="https://anthropic-gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(mode="adaptive", effort="high"),
        params={"temperature": 0.3},
    )
    with pytest.raises(ValueError, match="temperature=1"):
        await AnthropicMessagesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert calls == 0


@pytest.mark.asyncio
async def test_anthropic_reasoning_budget_must_fit_max_tokens():
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = ModelConfig(
        id="x", display_name="X", protocol="anthropic_messages", model="claude-x",
        api_url="https://anthropic-gateway.example/v1", api_key="secret",
        reasoning=ReasoningConfig(mode="budget", budget_tokens=4096),
    )
    with pytest.raises(ValueError, match="less than max_tokens"):
        await AnthropicMessagesAdapter(cfg, client=client).generate(system="sys", prompt="hello")
    await client.aclose()
    assert calls == 0
