"""Loader for per-method LLM specs defined in agents.yaml.

Keeps model choice, token budget, and fallback wiring out of code so we can
A/B routes (e.g. switch the catalog matcher to haiku, bump persona max_tokens)
without redeploying Python.

Resilient by design — every callsite gets a usable AgentSpec back even if
the YAML is missing, malformed, or has no entry for that method. Defaults
fall through from the YAML's top-level `defaults:` block, then to module
constants if the file is unreadable.
"""
from __future__ import annotations

import functools
import logging
import pathlib
from dataclasses import dataclass
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

SPECS_PATH = pathlib.Path(__file__).parent.parent / "agents.yaml"

# Last-resort defaults if agents.yaml is unreadable. Kept in sync with the
# "defaults" block at the top of agents.yaml.
_BUILTIN_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_BUILTIN_DEFAULT_MAX_TOKENS = 1024
_BUILTIN_DEFAULT_FALLBACK = "claude-3-5-sonnet-20241022"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    model: str
    max_tokens: int
    fallback_model: Optional[str] = None
    description: str = ""


@functools.lru_cache(maxsize=1)
def _load_raw() -> dict:
    try:
        return yaml.safe_load(SPECS_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.warning("agents.yaml not found at %s — using builtin defaults", SPECS_PATH)
        return {}
    except yaml.YAMLError as exc:
        logger.error("agents.yaml failed to parse: %s — using builtin defaults", exc)
        return {}


def _defaults() -> dict:
    raw = _load_raw()
    block = raw.get("defaults") or {}
    return {
        "model": block.get("model", _BUILTIN_DEFAULT_MODEL),
        "max_tokens": int(block.get("max_tokens", _BUILTIN_DEFAULT_MAX_TOKENS)),
        "fallback_model": block.get("fallback_model", _BUILTIN_DEFAULT_FALLBACK),
    }


def get(name: str) -> AgentSpec:
    """Return the spec for `name`, layered defaults → method-specific → safe values.

    Never raises — unknown names get the defaults block so new callsites work
    without YAML updates (with a debug log so we notice the drift).
    """
    raw = _load_raw()
    defaults = _defaults()
    agents = raw.get("agents") or {}
    entry = agents.get(name)
    if entry is None:
        logger.debug("agents.yaml has no entry for %r — using defaults", name)
        return AgentSpec(
            name=name,
            model=defaults["model"],
            max_tokens=defaults["max_tokens"],
            fallback_model=defaults["fallback_model"],
        )
    return AgentSpec(
        name=name,
        model=entry.get("model", defaults["model"]),
        max_tokens=int(entry.get("max_tokens", defaults["max_tokens"])),
        fallback_model=entry.get("fallback_model", defaults["fallback_model"]),
        description=entry.get("description", ""),
    )


def reload() -> None:
    """Drop the cached YAML — for tests and future hot-reload work."""
    _load_raw.cache_clear()
