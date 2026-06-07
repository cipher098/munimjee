"""Shared JSON-parsing helpers used by every LLM provider.

LLMs (Claude, Sarvam, …) frequently wrap JSON in code fences or prose. This
single parser strips both shapes and extracts the first balanced {...} block.
Any provider that needs structured output should call `parse_json_relaxed`
rather than `json.loads` directly so the bot doesn't fall over on a stray
prefix.
"""
from __future__ import annotations

import json


class LLMOutputParseError(ValueError):
    """Raised when a provider returns content we can't parse into the
    expected shape. Caught by the factory to drive fallback to another
    provider."""


def parse_json_relaxed(text: str) -> dict:
    """Parse JSON tolerating markdown code fences and prose wrappers.

    Raises LLMOutputParseError on any failure (not json.JSONDecodeError —
    the factory catches the typed exception for fallback dispatch).
    """
    if not text:
        raise LLMOutputParseError("empty LLM output")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMOutputParseError(f"could not parse JSON: {exc}; raw={text[:300]!r}") from exc
