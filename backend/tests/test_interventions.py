"""Unit tests for the intervention rule engine."""
from app.bot.interventions import Rule, evaluate, render_reminders, _match


def _r(rule_id, when, priority=50, reminder="x"):
    return Rule(id=rule_id, description="", priority=priority, when=when, reminder=reminder)


def test_match_substring_case_insensitive():
    assert _match(
        {"customer_message_contains_any": ["walk", "leave"]},
        {"customer_message": "I'll WALK away"},
    )
    assert not _match(
        {"customer_message_contains_any": ["walk"]},
        {"customer_message": "happy customer"},
    )


def test_match_negotiation_round():
    assert _match({"negotiation_round_eq": 0}, {"negotiation_round": 0})
    assert not _match({"negotiation_round_eq": 0}, {"negotiation_round": 1})
    assert _match({"negotiation_round_gte": 2}, {"negotiation_round": 5})
    assert not _match({"negotiation_round_gte": 2}, {"negotiation_round": 1})


def test_match_state_in():
    assert _match({"state_in": ["awaiting_payment", "purchased"]}, {"state": "awaiting_payment"})
    assert not _match({"state_in": ["awaiting_payment"]}, {"state": "negotiating"})


def test_match_floor_eq_listed():
    assert _match({"floor_eq_listed": True}, {"floor_price": 1000, "listed_price": 1000})
    assert not _match({"floor_eq_listed": True}, {"floor_price": 800, "listed_price": 1000})
    # Missing values → not a match (defensive — would otherwise fire spuriously).
    assert not _match({"floor_eq_listed": True}, {"floor_price": None, "listed_price": 1000})


def test_match_requires_all_conditions():
    # Both conditions must hold.
    when = {"negotiation_round_eq": 0, "customer_message_contains_any": ["price"]}
    assert _match(when, {"negotiation_round": 0, "customer_message": "what price?"})
    assert not _match(when, {"negotiation_round": 1, "customer_message": "what price?"})
    assert not _match(when, {"negotiation_round": 0, "customer_message": "hello"})


def test_unknown_operator_does_not_fire():
    # Forward-compatibility: a rule referencing an unknown operator must not fire
    # rather than crashing or being treated as a wildcard match.
    assert not _match({"future_operator": True}, {"customer_message": "anything"})


def test_evaluate_returns_priority_descending():
    rules = [
        _r("low", {"negotiation_round_eq": 0}, priority=10),
        _r("high", {"negotiation_round_eq": 0}, priority=100),
        _r("mid", {"negotiation_round_eq": 0}, priority=50),
    ]
    fired = evaluate({"negotiation_round": 0}, rules=rules)
    assert [r.id for r in fired] == ["high", "mid", "low"]


def test_evaluate_filters_non_matching():
    rules = [
        _r("matches", {"negotiation_round_eq": 0}),
        _r("does_not_match", {"negotiation_round_eq": 5}),
    ]
    fired = evaluate({"negotiation_round": 0}, rules=rules)
    assert [r.id for r in fired] == ["matches"]


def test_render_reminders_empty_when_nothing_fires():
    assert render_reminders([]) == ""


def test_render_reminders_wraps_in_system_reminder():
    rules = [_r("a", {}, reminder="do A"), _r("b", {}, reminder="do B")]
    block = render_reminders(rules)
    assert block.startswith("<system_reminder>")
    assert block.endswith("</system_reminder>")
    assert "[a]" in block and "do A" in block
    assert "[b]" in block and "do B" in block


def test_loaded_rules_have_known_ids():
    """Smoke test: the shipped YAML loads cleanly and contains the rules we
    rely on elsewhere. Catches typos/structure breakage."""
    from app.bot.interventions import load_rules
    load_rules.cache_clear()  # ensure fresh read
    rule_ids = {r.id for r in load_rules()}
    expected = {
        "walkaway_threat",
        "round_zero_no_discount",
        "fixed_price_no_counter",
        "agreed_price_locked",
        "complaint_acknowledge",
        "repeated_dissatisfaction",
        "very_negative_sentiment_no_close",
    }
    missing = expected - rule_ids
    assert not missing, f"Expected intervention rules missing from YAML: {missing}"


def test_match_intent_label_in():
    ctx = {"intent_classification": {"intent_label": "complaint"}}
    assert _match({"intent_label_in": ["complaint", "walkaway"]}, ctx)
    assert not _match({"intent_label_in": ["greeting"]}, ctx)
    # Missing classification → not a match (defensive).
    assert not _match({"intent_label_in": ["complaint"]}, {})


def test_match_sentiment_in():
    ctx = {"intent_classification": {"sentiment": "very_negative"}}
    assert _match({"sentiment_in": ["very_negative", "negative"]}, ctx)
    assert not _match({"sentiment_in": ["positive"]}, ctx)


def test_match_is_repeated_dissatisfaction():
    ctx_yes = {"intent_classification": {"is_repeated_dissatisfaction": True}}
    ctx_no = {"intent_classification": {"is_repeated_dissatisfaction": False}}
    assert _match({"is_repeated_dissatisfaction_eq": True}, ctx_yes)
    assert not _match({"is_repeated_dissatisfaction_eq": True}, ctx_no)
