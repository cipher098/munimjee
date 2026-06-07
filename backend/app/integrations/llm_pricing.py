"""Per-token LLM cost computation, driven by app/pricing.yaml.

Rates in the YAML are USD per 1,000,000 tokens. `compute_cost_usd` turns a
call's token counts into a Decimal USD cost, or None when the model (or a
used sub-rate) isn't priced — so unpriced models simply store cost_usd=NULL
rather than a wrong number.

The file is cached after first load; call `reload_pricing()` after editing
pricing.yaml (the /llm-costs/recompute endpoint does this) to pick up edits
without a restart.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_PRICING_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pricing.yaml")
_PER_MILLION = Decimal(1_000_000)

_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_PRICING_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        _cache = data.get("models", {}) or {}
    except FileNotFoundError:
        logger.warning("pricing.yaml not found at %s — all costs will be NULL", _PRICING_PATH)
        _cache = {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to parse pricing.yaml (%s) — all costs will be NULL", exc)
        _cache = {}
    return _cache


def reload_pricing() -> None:
    """Drop the cached pricing so the next call re-reads pricing.yaml."""
    global _cache
    _cache = None


def _rate(rates: dict, key: str) -> Optional[Decimal]:
    val = rates.get(key)
    if val is None:
        return None
    return Decimal(str(val))


def compute_cost_usd(
    model: str,
    input_tokens: Optional[int] = 0,
    output_tokens: Optional[int] = 0,
    cache_read_input_tokens: Optional[int] = 0,
    cache_creation_input_tokens: Optional[int] = 0,
) -> Optional[Decimal]:
    """Return total USD cost for a call, or None if the model isn't priced.

    If a token bucket has a positive count but its sub-rate is null, the
    whole cost is None — partial pricing would understate the real cost.
    """
    rates = _load().get(model)
    if not rates:
        return None

    buckets = (
        (input_tokens or 0, _rate(rates, "input")),
        (output_tokens or 0, _rate(rates, "output")),
        (cache_read_input_tokens or 0, _rate(rates, "cache_read")),
        (cache_creation_input_tokens or 0, _rate(rates, "cache_write")),
    )

    total = Decimal(0)
    for tokens, rate in buckets:
        if tokens and rate is None:
            return None  # a used bucket has no price — cannot compute honestly
        if tokens and rate is not None:
            total += (Decimal(tokens) / _PER_MILLION) * rate
    return total
