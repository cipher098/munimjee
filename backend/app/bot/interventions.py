"""Intervention rule engine.

Loads rules from intervention_rules.yaml, evaluates simple conditions against
a context dict, and returns the fired rules. Callers render their `reminder`
text into a `<system_reminder>` block and prepend it to the LLM call.

Why this exists: the monolithic DECISION_PROMPT/REPLY_PROMPT encode many
implicit rules ("don't discount on round 0", "fixed-price product → never
counter") that are only relevant on a fraction of turns. Pulling those out
into rules with explicit `when` conditions:

  - shrinks the static prompt over time (rules can be removed from the prompt
    once the intervention is proven to cover them)
  - makes behavior tunable without touching prompt text
  - lets us add per-seller / per-segment overrides later

The engine is deliberately tiny. No regex, no Python eval, no LLM-driven
matching — just substring tests and structural comparisons. Adding more
operators is fine as long as they stay declarative and side-effect free.
"""
from __future__ import annotations

import functools
import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

logger = logging.getLogger(__name__)

RULES_PATH = pathlib.Path(__file__).parent.parent / "intervention_rules.yaml"


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    priority: int
    when: dict
    reminder: str


@functools.lru_cache(maxsize=1)
def load_rules(path: pathlib.Path = RULES_PATH) -> list[Rule]:
    """Load rules from YAML. Cached so disk is hit once per process.

    Returns rules sorted by priority descending so callers iterating get the
    highest-impact rules first when applying limits.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("intervention_rules.yaml not found at %s — running with no rules", path)
        return []
    except yaml.YAMLError as exc:
        logger.error("intervention_rules.yaml failed to parse: %s — running with no rules", exc)
        return []

    rules: list[Rule] = []
    for entry in (raw or {}).get("rules", []) or []:
        try:
            rules.append(Rule(
                id=entry["id"],
                description=entry.get("description", ""),
                priority=int(entry.get("priority", 0)),
                when=dict(entry.get("when", {}) or {}),
                reminder=str(entry.get("reminder", "")).strip(),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Skipping malformed intervention rule %r: %s", entry, exc)
    rules.sort(key=lambda r: r.priority, reverse=True)
    return rules


def _match(when: dict, ctx: dict) -> bool:
    """Evaluate a rule's `when` clause against the context dict.

    Every condition must match (logical AND). Supported operators:
      - customer_message_contains_any: list[str], case-insensitive substring match
      - negotiation_round_eq: int
      - negotiation_round_gte: int
      - state_in: list[str]
      - floor_eq_listed: bool — true if floor_price == listed_price
      - bundle_pitched_eq: bool

    Unknown operators cause the rule to be skipped (logged once at module load
    would be cleaner; here we just return False to be safe).
    """
    msg = (ctx.get("customer_message") or "").lower()

    for op, expected in when.items():
        if op == "customer_message_contains_any":
            if not any(needle.lower() in msg for needle in expected or []):
                return False
        elif op == "negotiation_round_eq":
            if int(ctx.get("negotiation_round", 0)) != int(expected):
                return False
        elif op == "negotiation_round_gte":
            if int(ctx.get("negotiation_round", 0)) < int(expected):
                return False
        elif op == "state_in":
            if ctx.get("state") not in (expected or []):
                return False
        elif op == "floor_eq_listed":
            floor = ctx.get("floor_price")
            listed = ctx.get("listed_price")
            if floor is None or listed is None:
                return False
            if (floor == listed) is not bool(expected):
                return False
        elif op == "bundle_pitched_eq":
            if bool(ctx.get("bundle_pitched", False)) is not bool(expected):
                return False
        elif op == "intent_label_in":
            cls = ctx.get("intent_classification") or {}
            if cls.get("intent_label") not in (expected or []):
                return False
        elif op == "sentiment_in":
            cls = ctx.get("intent_classification") or {}
            if cls.get("sentiment") not in (expected or []):
                return False
        elif op == "is_repeated_dissatisfaction_eq":
            cls = ctx.get("intent_classification") or {}
            if bool(cls.get("is_repeated_dissatisfaction", False)) is not bool(expected):
                return False
        else:
            logger.warning("Unknown intervention operator %r — skipping rule", op)
            return False
    return True


def evaluate(ctx: dict, *, rules: list[Rule] | None = None) -> list[Rule]:
    """Return all rules whose `when` clause matches the context, sorted by priority desc.

    Sorting happens here (not just in load_rules) so callers passing custom rule
    lists in tests get the same ordering contract.
    """
    if rules is None:
        rules = load_rules()
    fired = [r for r in rules if _match(r.when, ctx)]
    fired.sort(key=lambda r: r.priority, reverse=True)
    return fired


def render_reminders(fired: list[Rule]) -> str:
    """Render fired rules as a single <system_reminder> block, or '' if none fired.

    The model treats system_reminder as elevated priority guidance. Keeping
    them tight (one paragraph per rule) avoids token bloat.
    """
    if not fired:
        return ""
    body_lines = []
    for r in fired:
        body_lines.append(f"- [{r.id}] {r.reminder}")
    return "<system_reminder>\n" + "\n".join(body_lines) + "\n</system_reminder>"
