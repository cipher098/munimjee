"""Multi-provider LLM routing — keeps the responder pipeline vendor-agnostic.

Two concrete providers ship today:
  - "anthropic" → wraps ClaudeClient
  - "sarvam"    → wraps SarvamClient

Both implement the `LLMProvider` ABC's two customer-facing methods,
`decide()` and `generate_reply()`. The factory `resolve_and_call()` picks
the right provider+model for a (method, seller) pair using:

  1. seller.llm_preferences[method] if set (only for `decide` and
     `generate_reply` — subagent calls ignore seller overrides)
  2. otherwise the app default from agents.yaml

If the primary call raises (LLMOutputParseError on bad JSON, HTTP error,
or any vendor exception), the factory falls back to the
`fallback_provider`/`fallback_model` from the AgentSpec — and logs
exactly which path was taken on every call so we can see in production
which provider produced each turn.

Adding a third provider is one file: a new subclass + one
`register("name", instance)` call. No changes to responder.py.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.bot import agent_spec
from app.integrations._json_utils import LLMOutputParseError  # noqa: F401  (re-export)

logger = logging.getLogger(__name__)


# Customer-facing methods that sellers can override on their own row.
# Subagent calls (intent_classifier, vision, catalog, etc.) are excluded
# on purpose — those run on whatever agents.yaml says, full stop.
_SELLER_OVERRIDABLE = {"decide", "generate_reply"}

# Friendly seller-side method names map to internal method names — the UI
# uses "decide"/"reply" because those are what the seller thinks about,
# but the rest of the codebase calls the second method "generate_reply".
_SELLER_KEY_TO_METHOD = {
    "decide": "decide",
    "reply": "generate_reply",
}


class LLMProvider(ABC):
    """Abstract base every concrete provider satisfies. Methods receive
    the resolved model + max_tokens from the factory so the provider
    body never reads agents.yaml itself — keeps the abstraction one-way."""

    name: str  # e.g. "anthropic" | "sarvam" — set on the subclass

    @abstractmethod
    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        """Return the decision JSON. Must raise LLMOutputParseError on
        malformed output so the factory can fall back cleanly."""

    @abstractmethod
    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        """Return the customer-facing reply text. Raise on any error so
        the factory can drive fallback."""


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, LLMProvider] = {}


def register(name: str, provider: LLMProvider) -> None:
    """Register a provider instance under a stable name. Idempotent — calling
    twice with the same name replaces the previous instance (handy for tests)."""
    _PROVIDERS[name] = provider


def get_provider(name: str) -> LLMProvider:
    """Return the registered provider for `name`, or raise if unknown."""
    if name not in _PROVIDERS:
        raise KeyError(f"no LLM provider registered for name={name!r}; known={list(_PROVIDERS)}")
    return _PROVIDERS[name]


def _ensure_providers_registered() -> None:
    """Lazy-register concrete providers on first factory call. Avoids
    circular imports at module load time (claude.py / sarvam.py import
    settings + anthropic SDK which we don't want at app-spec load)."""
    if all(p in _PROVIDERS for p in ("anthropic", "sarvam", "gemini")):
        return
    # Local imports to dodge circular import — concrete providers depend on
    # this module too (LLMProvider, LLMOutputParseError).
    from app.config import settings
    from app.integrations.claude import ClaudeProvider
    from app.integrations.openai_compat import OpenAICompatProvider
    from app.integrations.sarvam import SarvamProvider
    register("anthropic", ClaudeProvider())
    register("sarvam", SarvamProvider())
    register("gemini", OpenAICompatProvider("gemini", settings.GEMINI_BASE_URL, settings.GEMINI_API_KEY))


# ---------------------------------------------------------------------------
# Per-(method, seller) resolution
# ---------------------------------------------------------------------------

def resolve_choice(method: str, seller: Any | None) -> tuple[str, str, int]:
    """Return (provider_name, model, max_tokens) for this method+seller.

    - Looks up agents.yaml first (always provides max_tokens).
    - For overridable methods (decide / generate_reply) checks
      seller.llm_preferences for a {provider, model} override and uses
      it if present.
    """
    spec = agent_spec.get(method)
    provider_name = spec.provider
    model = spec.model

    if seller is not None and method in _SELLER_OVERRIDABLE:
        prefs = getattr(seller, "llm_preferences", None) or {}
        # The UI uses "decide" / "reply" as keys; map back to method name.
        seller_key = "reply" if method == "generate_reply" else "decide"
        override = (prefs.get(seller_key) or {}) if isinstance(prefs, dict) else {}
        ovr_provider = override.get("provider")
        ovr_model = override.get("model")
        if ovr_provider:
            provider_name = ovr_provider
        if ovr_model:
            model = ovr_model

    return provider_name, model, spec.max_tokens


async def resolve_and_call(method: str, seller: Any | None, context: dict) -> Any:
    """Run `method` (decide or generate_reply) on the resolved provider.

    On failure, falls back to (spec.fallback_provider, spec.fallback_model)
    from agents.yaml. Logs the chosen path on every call so we can see
    which provider produced each turn in production.
    """
    if method not in {"decide", "generate_reply"}:
        raise ValueError(f"resolve_and_call only supports decide / generate_reply, got {method!r}")

    _ensure_providers_registered()
    spec = agent_spec.get(method)
    provider_name, model, max_tokens = resolve_choice(method, seller)

    try:
        provider = get_provider(provider_name)
        logger.info(
            "resolve_and_call %s → %s/%s (max_tokens=%d)",
            method, provider_name, model, max_tokens,
        )
        return await _dispatch(provider, method, context, model=model, max_tokens=max_tokens)
    except Exception as primary_exc:
        if not spec.fallback_provider or not spec.fallback_model:
            logger.exception(
                "resolve_and_call %s: %s/%s failed and no fallback configured",
                method, provider_name, model,
            )
            raise
        if (spec.fallback_provider, spec.fallback_model) == (provider_name, model):
            logger.exception(
                "resolve_and_call %s: %s/%s failed and fallback is the same — re-raising",
                method, provider_name, model,
            )
            raise
        logger.warning(
            "resolve_and_call %s: %s/%s raised %s — falling back to %s/%s",
            method, provider_name, model, type(primary_exc).__name__,
            spec.fallback_provider, spec.fallback_model,
        )
        fb = get_provider(spec.fallback_provider)
        return await _dispatch(
            fb, method, context,
            model=spec.fallback_model, max_tokens=spec.max_tokens,
        )


async def _dispatch(
    provider: LLMProvider, method: str, context: dict,
    *, model: str, max_tokens: int,
) -> Any:
    if method == "decide":
        return await provider.decide(context, model=model, max_tokens=max_tokens)
    if method == "generate_reply":
        return await provider.generate_reply(context, model=model, max_tokens=max_tokens)
    raise ValueError(f"unsupported method {method!r}")
