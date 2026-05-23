"""DB-backed prompt store with file fallback.

Loads prompt content from the `prompts` table on first access (per prompt
name) and caches it in-process for `_CACHE_TTL_SECONDS` so we don't issue
a DB query on every LLM call. If the DB lookup misses or fails, falls back
to the value compiled into prompts.py / subagent_prompts.py so the bot
keeps working during outages or before the first seed.

Why a DB at all: training dashboard rewrites prompts based on seller
feedback. Today it edits prompts.py on disk and relies on uvicorn reload.
That breaks for worker / celery / non-reload deploys. Moving the source of
truth to Postgres makes prompt updates take effect immediately across all
processes without restarts.

The cache is cleared on `upsert()` so writes are visible to the same
process instantly. Other processes pick up the new content on the next
TTL expiry (≤ 60s).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import worker_session
from app.models.prompt import Prompt

logger = logging.getLogger(__name__)

# Cache TTL — 60s is short enough that prompt edits feel instant across the
# api/worker/beat processes, long enough that we don't hammer Postgres.
_CACHE_TTL_SECONDS = 60

# {name: (content, fetched_at_monotonic)}
_cache: dict[str, tuple[str, float]] = {}


def _fallback_from_modules(name: str) -> Optional[str]:
    """Look up `name` in the in-process Python modules.

    Names map to constants by uppercase + _PROMPT suffix:
      decide                       -> prompts.DECISION_PROMPT
      generate_reply               -> prompts.REPLY_PROMPT
      catalog_match                -> prompts.CATALOG_MATCH_PROMPT
      image_describe               -> prompts.IMAGE_DESCRIBE_PROMPT
      generate_product_description -> subagent_prompts.GENERATE_PRODUCT_DESCRIPTION_PROMPT
      suggest_category             -> subagent_prompts.SUGGEST_CATEGORY_PROMPT
      suggest_tags_for_category    -> subagent_prompts.SUGGEST_TAGS_FOR_CATEGORY_PROMPT
      extract_feature_query        -> subagent_prompts.EXTRACT_FEATURE_QUERY_PROMPT
      extract_persona              -> subagent_prompts.EXTRACT_PERSONA_PROMPT
      intent_classifier            -> subagent_prompts.INTENT_CLASSIFIER_PROMPT
    """
    from app import prompts as _prompts
    from app import subagent_prompts as _sub

    explicit_aliases = {
        "decide": "DECISION_PROMPT",
        "generate_reply": "REPLY_PROMPT",
        "catalog_match": "CATALOG_MATCH_PROMPT",
        "image_describe": "IMAGE_DESCRIBE_PROMPT",
        "generate_product_description": "GENERATE_PRODUCT_DESCRIPTION_PROMPT",
        "suggest_category": "SUGGEST_CATEGORY_PROMPT",
        "suggest_tags_for_category": "SUGGEST_TAGS_FOR_CATEGORY_PROMPT",
        "extract_feature_query": "EXTRACT_FEATURE_QUERY_PROMPT",
        "extract_persona": "EXTRACT_PERSONA_PROMPT",
        "intent_classifier": "INTENT_CLASSIFIER_PROMPT",
    }
    const_name = explicit_aliases.get(name)
    if not const_name:
        return None
    for module in (_prompts, _sub):
        value = getattr(module, const_name, None)
        if isinstance(value, str):
            return value
    return None


async def get(name: str) -> str:
    """Return the latest prompt content for `name`.

    Lookup order:
      1. process cache (if entry not expired)
      2. prompts table in Postgres
      3. in-process Python constant fallback

    Always returns a non-empty string or raises KeyError if the name is
    completely unknown. Errors in DB lookups are swallowed and demoted
    to fallback so the LLM call path never breaks on this layer.
    """
    cached = _cache.get(name)
    if cached and time.monotonic() - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        async with worker_session() as session:
            result = await session.execute(select(Prompt).where(Prompt.name == name))
            row = result.scalar_one_or_none()
        if row is not None and row.content:
            _cache[name] = (row.content, time.monotonic())
            return row.content
    except Exception as exc:
        logger.warning("prompt_store.get(%r) DB lookup failed (%s) — falling back to file", name, exc)

    fallback = _fallback_from_modules(name)
    if fallback is None:
        raise KeyError(f"Unknown prompt name: {name}")
    # Cache the fallback too so we don't re-import on every call when DB is empty.
    _cache[name] = (fallback, time.monotonic())
    return fallback


async def upsert(name: str, content: str) -> int:
    """Insert or update a prompt by name. Returns the new version number.

    Uses Postgres ON CONFLICT DO UPDATE so version increments atomically.
    Bypasses cache after write so subsequent get() calls see the update.
    """
    async with worker_session() as session:
        stmt = pg_insert(Prompt).values(name=name, content=content, version=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Prompt.name],
            set_={
                "content": content,
                "version": Prompt.version + 1,
            },
        ).returning(Prompt.version)
        result = await session.execute(stmt)
        version = result.scalar_one()
    _cache.pop(name, None)
    logger.info("prompt_store.upsert(%r) → version=%s, %d chars", name, version, len(content))
    return version


def clear_cache(name: Optional[str] = None) -> None:
    """Drop a single entry, or the whole cache if `name` is None. Test helper."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)
