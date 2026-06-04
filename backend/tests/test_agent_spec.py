"""Tests for the agent spec loader.

Validates:
  - shipped agents.yaml loads and contains every method ClaudeClient calls
  - missing methods fall back to the defaults block
  - reload() drops the cache (so future YAML edits take effect)
"""
import pathlib

import pytest
import yaml

from app.bot import agent_spec


REQUIRED_METHODS = {
    "decide",
    "generate_reply",
    "intent_classifier",
    "generate_product_description",
    "describe_product_image",
    "match_product_by_description",
    "suggest_category",
    "suggest_tags_for_category",
    "extract_feature_query",
    "extract_persona",
}


def test_shipped_yaml_covers_every_caller():
    """Every method ClaudeClient/intent_classifier consults must have an explicit
    YAML entry — defaults are a fallback, not the intended source of truth."""
    raw = yaml.safe_load(agent_spec.SPECS_PATH.read_text(encoding="utf-8"))
    declared = set((raw or {}).get("agents", {}) or {})
    missing = REQUIRED_METHODS - declared
    assert not missing, f"agents.yaml missing entries: {missing}"


def test_get_known_method_returns_yaml_values():
    spec = agent_spec.get("decide")
    assert spec.name == "decide"
    assert spec.provider == "gemini"
    assert spec.model.startswith("gemini-")
    assert spec.max_tokens > 0
    assert spec.fallback_model.startswith("claude-")  # decide falls back to Claude


def test_get_unknown_method_falls_back_to_defaults():
    """A method not present in YAML returns the defaults block — no crash."""
    spec = agent_spec.get("definitely_not_a_real_method_xyz")
    assert spec.name == "definitely_not_a_real_method_xyz"
    # Default model should still be a claude id (driven by defaults block).
    assert spec.model.startswith("claude-")
    assert spec.max_tokens > 0


def test_intent_classifier_uses_cheap_model_with_fallback():
    """Intent classifier is hot-path — runs on the cheap model (Gemini Flash-Lite)
    with a Claude fallback so a provider blip never blocks the pipeline."""
    spec = agent_spec.get("intent_classifier")
    assert spec.provider == "gemini"
    assert spec.model == "gemini-2.5-flash-lite"
    assert spec.fallback_provider == "anthropic"


def test_reload_clears_cache(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """reload() must let subsequent get() see edits made to the YAML on disk."""
    custom = tmp_path / "agents.yaml"
    custom.write_text(
        "defaults:\n  model: claude-x\n  max_tokens: 999\nagents:\n  foo:\n    model: claude-y\n    max_tokens: 42\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_spec, "SPECS_PATH", custom)
    agent_spec.reload()
    spec = agent_spec.get("foo")
    assert spec.model == "claude-y"
    assert spec.max_tokens == 42
    # Restore for the rest of the suite.
    agent_spec.reload()
