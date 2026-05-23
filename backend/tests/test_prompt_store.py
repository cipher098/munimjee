"""Tests for the DB-backed prompt store fallback path.

These tests run without a live Postgres — they exercise the fallback to the
in-process Python constants when the DB lookup fails (which is what
happens during tests, since the test container has no DB connection).

The DB-write path is exercised via VCR/integration tests separately.
"""
import pytest

from app.bot import prompt_store


@pytest.fixture(autouse=True)
def clear_cache_before_each_test():
    prompt_store.clear_cache()
    yield
    prompt_store.clear_cache()


@pytest.mark.asyncio
async def test_get_falls_back_to_decision_prompt():
    """When DB is unreachable, prompt_store must return the in-file DECISION_PROMPT."""
    content = await prompt_store.get("decide")
    assert content
    assert "NEGOTIATION STRATEGY" in content, "decide should fall back to DECISION_PROMPT"


@pytest.mark.asyncio
async def test_get_falls_back_to_reply_prompt():
    content = await prompt_store.get("generate_reply")
    assert content
    assert "HARD CONSTRAINTS" in content


@pytest.mark.asyncio
async def test_get_falls_back_for_each_subagent():
    """Every sub-agent name resolves to a non-empty string via fallback."""
    for name in [
        "image_describe",
        "catalog_match",
        "generate_product_description",
        "suggest_category",
        "suggest_tags_for_category",
        "extract_feature_query",
        "extract_persona",
        "intent_classifier",
    ]:
        content = await prompt_store.get(name)
        assert content, f"empty fallback for prompt name {name!r}"


@pytest.mark.asyncio
async def test_get_unknown_name_raises_key_error():
    with pytest.raises(KeyError):
        await prompt_store.get("definitely_not_a_real_prompt_name_xyz")


@pytest.mark.asyncio
async def test_cache_returns_same_content_on_second_call():
    """Second call within TTL should be served from cache (not re-fetched).
    We can't directly observe that here, but we verify identity stability."""
    first = await prompt_store.get("decide")
    second = await prompt_store.get("decide")
    assert first == second


@pytest.mark.asyncio
async def test_clear_cache_drops_specific_name():
    await prompt_store.get("decide")  # populate cache
    prompt_store.clear_cache("decide")
    # Second get re-resolves via fallback (no DB) — must still succeed.
    content = await prompt_store.get("decide")
    assert content
