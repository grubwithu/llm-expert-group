from __future__ import annotations

import json
import re
from typing import Any


def _decode_object(candidate: str) -> dict[str, Any] | None:
    for strict in (True, False):
        try:
            value = json.loads(candidate, strict=strict)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _loose_final_action(text: str) -> dict[str, Any] | None:
    """Recover a final action when a provider emits almost-JSON content."""
    matches = list(re.finditer(r'"action"\s*:\s*"final"', text, flags=re.IGNORECASE))
    if not matches:
        return None
    tail = text[matches[-1].start():]
    content = re.search(r'"content"\s*:\s*"(.*)$', tail, flags=re.DOTALL)
    if content is None:
        return None
    value = re.sub(r'"\s*}\s*(?:```)?\s*$', "", content.group(1))
    value = re.sub(r'\n?```\s*$', "", value)
    try:
        decoded = json.loads(f'"{value}"', strict=False)
    except json.JSONDecodeError:
        decoded = value.replace(r"\n", "\n").replace(r'\"', '"').replace(r"\\", "\\")
    return {"action": "final", "content": decoded}


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the final complete JSON object in a model response.

    Some OpenAI-compatible gateways concatenate an intermediate action and a
    final action in one streamed response. The final action is authoritative;
    treating both as one invalid object leaks protocol JSON into the UI.
    """
    stripped = text.strip()
    candidates = [stripped]
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1))
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        value = _decode_object(candidate)
        if value is not None:
            return value

    cursor = 0
    last: dict[str, Any] | None = None
    while True:
        start = stripped.find("{", cursor)
        if start < 0:
            break
        try:
            value, offset = json.JSONDecoder(strict=False).raw_decode(stripped[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(value, dict):
            last = value
        cursor = start + max(offset, 1)
    return last or _loose_final_action(stripped)
