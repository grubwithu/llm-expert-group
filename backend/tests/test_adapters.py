import pytest

from app.adapters import parse_anthropic_messages_text, parse_openai_responses_text, _endpoint


def test_openai_responses_parser_direct():
    assert parse_openai_responses_text({"output_text": "hello"}) == "hello"


def test_openai_responses_parser_nested():
    data = {"output": [{"content": [{"type": "output_text", "text": "a"}, {"type": "output_text", "text": "b"}]}]}
    assert parse_openai_responses_text(data) == "a\nb"


def test_anthropic_parser():
    data = {"content": [{"type": "text", "text": "a"}, {"type": "tool_use", "id": "x"}, {"type": "text", "text": "b"}]}
    assert parse_anthropic_messages_text(data) == "a\nb"


@pytest.mark.parametrize("base,suffix,expected", [
    ("https://api.openai.com/v1", "/responses", "https://api.openai.com/v1/responses"),
    ("https://example.com", "/responses", "https://example.com/v1/responses"),
    ("https://example.com/v1/messages", "/messages", "https://example.com/v1/messages"),
])
def test_endpoint(base, suffix, expected):
    assert _endpoint(base, suffix) == expected
