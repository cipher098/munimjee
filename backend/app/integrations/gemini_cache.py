"""Explicit context caching for Gemini (native generateContent API).

The decide/reply *system* prompts are a large static prefix that is
byte-identical across every seller and conversation. Gemini's IMPLICIT caching
does not fire for our traffic (verified empirically on both the OpenAI-compat
and native endpoints), so we cache that prefix EXPLICITLY: create one
CachedContent handle per distinct prefix, reference it on every call, and let
Google bill the prefix at the cache_read rate ($0.01/M vs $0.10/M input).

Only the native `:generateContent` endpoint supports `cachedContent`, so this
module speaks that wire format directly (no SDK needed). Each worker process
keeps its own handle dict — a few duplicate caches across processes, which is
negligible storage cost. Any failure raises so the caller can fall back to the
normal (uncached) OpenAI-compat path; caching must never break the bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import httpx

from app.integrations import llm_logging

logger = logging.getLogger(__name__)

# sha256(system_text) -> (cache_name, expiry_monotonic)
_handles: dict[str, tuple[str, float]] = {}
_lock = asyncio.Lock()

_TTL_SECONDS = 3600       # how long Google keeps the cache alive
_REFRESH_BEFORE = 600     # recreate when within 10 min of expiry
_MIN_CACHE_TOKENS = 1024  # Flash-Lite explicit-cache minimum


def _key(system_text: str) -> str:
    return hashlib.sha256(system_text.encode("utf-8")).hexdigest()


async def _create_cache(client: httpx.AsyncClient, native_base: str, api_key: str,
                        model: str, system_text: str) -> str:
    payload = {
        "model": f"models/{model}",
        "systemInstruction": {"parts": [{"text": system_text}]},
        "ttl": f"{_TTL_SECONDS}s",
    }
    r = await client.post(f"{native_base}/cachedContents?key={api_key}", json=payload)
    r.raise_for_status()
    name = r.json()["name"]
    logger.info("gemini cache created %s for %s (%d-char prefix)", name, model, len(system_text))
    return name


async def _get_or_create(client: httpx.AsyncClient, native_base: str, api_key: str,
                         model: str, system_text: str) -> str:
    k = _key(system_text)
    entry = _handles.get(k)
    if entry and entry[1] - time.monotonic() > _REFRESH_BEFORE:
        return entry[0]
    async with _lock:
        entry = _handles.get(k)
        if entry and entry[1] - time.monotonic() > _REFRESH_BEFORE:
            return entry[0]
        name = await _create_cache(client, native_base, api_key, model, system_text)
        _handles[k] = (name, time.monotonic() + _TTL_SECONDS)
        return name


async def cached_generate(*, native_base: str, api_key: str, model: str,
                          system_text: str, user_text: str, max_tokens: int,
                          temperature: float, log_method: str | None) -> str:
    """generateContent with an explicit cached system prefix.

    Logs the call (cache_read_input_tokens = cachedContentTokenCount) and
    returns the response text. Raises on any failure so the caller falls back
    to the uncached path.
    """
    if len(system_text) // 4 < _MIN_CACHE_TOKENS:
        raise RuntimeError("system prefix below explicit-cache minimum")

    gen_url = f"{native_base}/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=45) as client:
        name = await _get_or_create(client, native_base, api_key, model, system_text)
        payload["cachedContent"] = name
        r = await client.post(gen_url, json=payload)
        if r.status_code in (403, 404):
            # cache likely expired server-side — drop our handle and recreate once
            _handles.pop(_key(system_text), None)
            payload["cachedContent"] = await _get_or_create(
                client, native_base, api_key, model, system_text)
            r = await client.post(gen_url, json=payload)
        r.raise_for_status()
        data = r.json()

    um = data.get("usageMetadata") or {}
    cached = um.get("cachedContentTokenCount") or 0
    prompt_toks = um.get("promptTokenCount")
    billable_input = prompt_toks - cached if prompt_toks is not None else None

    candidates = data.get("candidates") or []
    text = ""
    if candidates:
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        finish = candidates[0].get("finishReason") if candidates else None
        msg = f"gemini cached generate returned empty content (finish_reason={finish})"
        llm_logging.record(
            "gemini", model, log_method, status="error",
            input_tokens=billable_input, output_tokens=um.get("candidatesTokenCount"),
            cache_read_input_tokens=cached or None, request=payload, error=msg,
        )
        raise RuntimeError(msg)

    llm_logging.record(
        "gemini", model, log_method,
        input_tokens=billable_input, output_tokens=um.get("candidatesTokenCount"),
        cache_read_input_tokens=cached or None,
        request=payload, response=text,
    )
    return text
