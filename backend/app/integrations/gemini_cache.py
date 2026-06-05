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

from app.config import settings
from app.integrations import llm_logging

logger = logging.getLogger(__name__)

# L1 (per-process): sha256(system_text) -> (cache_name, expiry_monotonic).
# L2 (shared via Redis): the same name keyed under _REDIS_PREFIX, so every
# worker/api process reuses ONE handle per prefix instead of each creating its
# own (storage cost would otherwise scale with process count).
_handles: dict[str, tuple[str, float]] = {}
_lock = asyncio.Lock()

_TTL_SECONDS = 3600       # how long Google keeps the cache alive
_REFRESH_BEFORE = 600     # recreate when within 10 min of expiry
_MIN_CACHE_TOKENS = 1024  # Flash-Lite explicit-cache minimum
_SHARED_TTL = _TTL_SECONDS - _REFRESH_BEFORE  # Redis/L1 entries expire before the cache does
_REDIS_PREFIX = "gemini:cache:"

_redis_client = None  # None=untried, False=unavailable, else an async client


def _key(system_text: str) -> str:
    return hashlib.sha256(system_text.encode("utf-8")).hexdigest()


def _get_redis():
    """Lazily build a shared async Redis client; cache failure so we don't retry
    on every call. Returns the client or None (→ per-process fallback)."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("gemini_cache: Redis unavailable (%s) — per-process handles", exc)
            _redis_client = False
    return _redis_client or None


async def _redis_get_name(k: str) -> str | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        return await r.get(f"{_REDIS_PREFIX}{k}")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("gemini_cache: Redis get failed (%s)", exc)
        return None


async def _redis_put_name(k: str, name: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        await r.set(f"{_REDIS_PREFIX}{k}", name, ex=_SHARED_TTL)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("gemini_cache: Redis set failed (%s)", exc)


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


async def _create_shared(client: httpx.AsyncClient, native_base: str, api_key: str,
                         model: str, system_text: str, k: str) -> str:
    """Create a cache, coordinating across processes via a Redis lock so only one
    process creates the handle; the rest read the name it publishes. Falls back
    to an uncoordinated create if Redis is unavailable or the lock wait drains."""
    r = _get_redis()
    if r is None:  # no Redis — plain per-process create
        return await _create_cache(client, native_base, api_key, model, system_text)
    lock_key = f"{_REDIS_PREFIX}lock:{k}"
    try:
        got_lock = await r.set(lock_key, "1", nx=True, ex=30)
    except Exception:  # pragma: no cover - defensive
        got_lock = True
    if got_lock:
        try:
            name = await _create_cache(client, native_base, api_key, model, system_text)
            await _redis_put_name(k, name)
            return name
        finally:
            try:
                await r.delete(lock_key)
            except Exception:  # pragma: no cover - defensive
                pass
    # Another process is creating it — wait briefly for the published name.
    for _ in range(20):
        await asyncio.sleep(0.25)
        name = await _redis_get_name(k)
        if name:
            return name
    name = await _create_cache(client, native_base, api_key, model, system_text)
    await _redis_put_name(k, name)
    return name


async def _get_or_create(client: httpx.AsyncClient, native_base: str, api_key: str,
                         model: str, system_text: str) -> str:
    k = _key(system_text)
    # L1: this process already has a live handle.
    entry = _handles.get(k)
    if entry and entry[1] > time.monotonic():
        return entry[0]
    async with _lock:
        entry = _handles.get(k)
        if entry and entry[1] > time.monotonic():
            return entry[0]
        # L2: another process already published one to Redis.
        name = await _redis_get_name(k)
        if not name:
            name = await _create_shared(client, native_base, api_key, model, system_text, k)
        _handles[k] = (name, time.monotonic() + _SHARED_TTL)
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
