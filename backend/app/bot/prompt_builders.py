"""Shared prompt construction for the customer-facing LLM calls.

Both ClaudeClient and SarvamClient build the SAME `decide` / `generate_reply`
prompt from the SAME context here, so the two providers never drift. Claude
then splits the prompt for prompt-caching + native message history; Sarvam
(no caching, no native roles) sends the whole prompt as the system message
with a rendered transcript as the user message.

Before this module existed, Sarvam carried a hand-maintained copy of the reply
prompt that was missing ~8 context fields Claude had — the main reason Sarvam
replies read worse. Keeping one builder guarantees parity.
"""
import json
import logging

from app.bot import prompt_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation transcript
# ---------------------------------------------------------------------------

def render_transcript(history: list[dict] | None, limit: int = 12) -> str:
    """Render conversation.messages as a readable transcript for models that
    don't take native role messages (Sarvam).

    customer → "Customer", bot/seller_manual → "Seller". Returns
    "(no prior messages)" when empty.
    """
    if not history:
        return "(no prior messages)"
    role_map = {"customer": "Customer", "bot": "Seller", "seller_manual": "Seller"}
    lines = []
    for entry in history[-limit:]:
        raw = entry.get("role", "")
        role = role_map.get(raw, raw or "?")
        content = (entry.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no prior messages)"


# ---------------------------------------------------------------------------
# System / dynamic splits (used by Claude for prompt caching)
# ---------------------------------------------------------------------------

def split_reply_prompt(formatted_prompt: str) -> tuple[str, str]:
    """Split a formatted reply prompt into (static_system, dynamic_context) at
    the `--- DYNAMIC CONTEXT ---` marker. Static rules cache; per-call data
    goes below. Returns (whole, "") if the marker is missing."""
    marker = "--- DYNAMIC CONTEXT ---"
    if marker not in formatted_prompt:
        return formatted_prompt, ""
    before, _, after = formatted_prompt.partition(marker)
    return before.rstrip(), marker + after.rstrip()


def split_decide_prompt(formatted_prompt: str) -> tuple[str, str]:
    """Split a formatted decision prompt into (static_system, dynamic_user).

    Splits on `--- CONTEXT ---` (data start) and `--- NEGOTIATION STRATEGY`
    (rules that should stay cached). Returns (whole, "") if markers missing —
    caller detects empty user and skips caching.
    """
    ctx_marker = "--- CONTEXT ---"
    strategy_marker = "--- NEGOTIATION STRATEGY"
    if ctx_marker not in formatted_prompt or strategy_marker not in formatted_prompt:
        return formatted_prompt, ""
    before_ctx, _, after_ctx = formatted_prompt.partition(ctx_marker)
    if strategy_marker not in after_ctx:
        return formatted_prompt, ""
    context_block, _, strategy_block = after_ctx.partition(strategy_marker)
    static_system = (
        before_ctx.rstrip()
        + "\n\n"
        + strategy_marker
        + strategy_block.rstrip()
    )
    dynamic_user = ctx_marker + context_block.rstrip()
    return static_system, dynamic_user


# ---------------------------------------------------------------------------
# Interventions (decide only) — evaluated once per turn by whichever provider
# handles decide; records the test hook for the scenario harness.
# ---------------------------------------------------------------------------

def evaluate_interventions(context: dict) -> str:
    """Evaluate intervention rules, record the test hook, and return a
    reminder block to prepend to the dynamic context (or "")."""
    from app.bot import interventions as _interventions
    from app.bot.test_hooks import record as _record_turn

    fired = _interventions.evaluate(context)
    if fired:
        logger.info(
            "Interventions fired: %s",
            ", ".join(f"{r.id}(p={r.priority})" for r in fired),
        )
    _record_turn(fired_interventions=[r.id for r in fired])
    return _interventions.render_reminders(fired)


# ---------------------------------------------------------------------------
# decide prompt
# ---------------------------------------------------------------------------

async def build_decide_prompt(context: dict) -> str:
    """Format the `decide` prompt from `prompt_store.get("decide")`.

    `customer_message` / `message_history` are formatted empty — callers send
    the latest turn + history separately (Claude as native messages, Sarvam as
    a rendered transcript in the user block)."""
    last_counter = context.get("last_counter_price")
    last_counter_str = f"{last_counter} paise (₹{last_counter // 100})" if last_counter else "none yet"
    last_shown = context.get("last_shown_price")
    last_shown_str = f"{last_shown} paise (₹{last_shown // 100})" if last_shown else "none yet"

    prev_price = context.get("previous_price_paise")
    prev_price_str = f"₹{prev_price // 100}" if prev_price else "none"

    decision_template = await prompt_store.get("decide")
    return decision_template.format(
        state=context.get("state", ""),
        customer_message="",
        listed_price=context.get("listed_price", "unknown"),
        floor_price=context.get("floor_price", "unknown"),
        last_counter_price=last_counter_str,
        last_shown_price=last_shown_str,
        round_number=context.get("negotiation_round", 0),
        message_history="",
        available_products=json.dumps(context.get("available_products", []), ensure_ascii=False),
        other_inquiry_products=json.dumps(context.get("other_inquiry_products", []), ensure_ascii=False),
        bundle_pitched=context.get("bundle_pitched", False),
        seller_channels=json.dumps(context.get("seller_channels", []), ensure_ascii=False),
        product_variants=json.dumps(context.get("product_variants", []), ensure_ascii=False),
        active_variant_label=context.get("active_variant_label") or "none",
        past_orders=context.get("past_orders_summary") or "none",
        previous_price=prev_price_str,
    )


# ---------------------------------------------------------------------------
# generate_reply prompt
# ---------------------------------------------------------------------------

async def build_reply_prompt(context: dict) -> str:
    """Format the `generate_reply` prompt from `prompt_store.get("generate_reply")`
    with the full customer-facing context (price, warranty, stock, policies,
    bundle/multi-price, etc.). `customer_message` / `message_history` are empty
    — callers attach the latest turn + history separately."""
    decision = context.get("decision", {})
    price = decision.get("price")
    price_context = f"YOUR COUNTER OFFER IS ₹{price // 100} — quote this exact number" if price else "No price change"
    last_counter = context.get("last_counter_price")
    last_counter_reply_str = f"₹{last_counter // 100}" if last_counter else "none"
    last_shown = context.get("last_shown_price")
    last_shown_reply_str = f"₹{last_shown // 100}" if last_shown else "none"
    display_price_rupees = context.get("display_price_rupees")
    display_price_str = f"₹{display_price_rupees}" if display_price_rupees is not None else "N/A"

    warranty = context.get("warranty_months")
    warranty_str = f"{warranty} months" if warranty else "No warranty"

    stock = context.get("stock_quantity")
    if stock is None:
        stock_str = "Not tracked"
    elif stock == 0:
        stock_str = "Out of stock"
    elif stock <= 3:
        stock_str = f"Only {stock} left"
    else:
        stock_str = f"{stock} in stock"

    policies = context.get("policies") or {}
    cod = policies.get("cod")
    cod_charges = policies.get("cod_charges", 0)
    return_days = policies.get("return_days")
    exchange_days = policies.get("exchange_days")
    delivery_days = policies.get("delivery_days")
    payment_modes = policies.get("payment_modes") or []

    _mode_labels = {"upi": "UPI", "bank_transfer": "Bank Transfer/NEFT", "card": "Card"}
    mode_str = " / ".join(_mode_labels.get(m, m) for m in payment_modes) if payment_modes else None

    policy_lines = []
    if mode_str:
        policy_lines.append(f"Accepted payment: {mode_str}")
    if cod is True:
        if cod_charges:
            policy_lines.append(f"COD available with ₹{cod_charges} extra charge")
        else:
            policy_lines.append("COD available, no extra charge")
    elif cod is False:
        policy_lines.append("No COD — prepaid only")
    if return_days:
        policy_lines.append(f"{return_days}-day returns accepted")
    elif return_days == 0 and "return_days" in policies:
        policy_lines.append("No returns")
    if exchange_days:
        policy_lines.append(f"{exchange_days}-day exchange accepted")
    elif exchange_days == 0 and "exchange_days" in policies:
        policy_lines.append("No exchange")
    if delivery_days:
        policy_lines.append(f"Delivery in {delivery_days}")
    policy_str = ", ".join(policy_lines) if policy_lines else "Not configured — do not mention or invent any policy; say you'll check and confirm"

    total_photos = context.get("total_photos", 1)
    has_more_photos = total_photos > 1

    product_description = context.get("product_description") or "No description available"
    logger.debug("build_reply_prompt: product=%r description=%r", context.get("product_name"), product_description)

    tag_values = context.get("product_tag_values") or {}
    tag_values_str = (
        ", ".join(f"{k}: {v}" for k, v in tag_values.items()) if tag_values else "None available"
    )

    other_active = context.get("other_active_products") or []
    other_active_str = (
        ", ".join(p["name"] for p in other_active) if other_active else "none"
    )

    other_inquiry = context.get("other_inquiry_products") or []

    def _fmt_inquiry(p: dict) -> str:
        base = f"{p['name']} listed=₹{p['listed_price_rupees']} floor=₹{p['floor_price_rupees']}"
        if p.get("last_shown_price_rupees"):
            base += f" last_shown=₹{p['last_shown_price_rupees']} (NEVER quote higher than this)"
        return base

    other_inquiry_str = (
        ", ".join(_fmt_inquiry(p) for p in other_inquiry) if other_inquiry else "none"
    )

    prev_price = context.get("previous_price_paise")
    prev_price_str = f"₹{prev_price // 100}" if prev_price else "none"

    avail = context.get("available_products") or []
    available_products_str = (
        ", ".join(
            f"{p['name']} (₹{p['listed_price_paise'] // 100})"
            for p in avail if p.get("name")
        )
        if avail else "none"
    )

    reply_template = await prompt_store.get("generate_reply")
    return reply_template.format(
        persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
        product_name=context.get("product_name", "the product"),
        product_description=product_description,
        product_tag_values=tag_values_str,
        listed_price_rupees=context.get("listed_price_rupees", "N/A"),
        display_price_rupees=display_price_str,
        floor_price_rupees=context.get("floor_price_rupees", "N/A"),
        warranty_info=warranty_str,
        stock_info=stock_str,
        policy_info=policy_str,
        action=decision.get("action", "clarify"),
        price_context=price_context,
        last_counter_price=last_counter_reply_str,
        last_shown_price=last_shown_reply_str,
        customer_intent=decision.get("customer_intent", "warm"),
        customer_message="",
        has_more_photos=has_more_photos,
        message_history="",
        address_term=context.get("address_term", "ji"),
        shareable_business_info=context.get("shareable_business_info") or "N/A",
        seller_gender=context.get("seller_gender") or "male",
        other_active_products=other_active_str,
        other_inquiry_products_str=other_inquiry_str,
        multi_price_breakdown=context.get("multi_price_breakdown") or "N/A",
        shown_products=context.get("shown_products") or "N/A",
        quote_breakdown=context.get("quote_breakdown") or "N/A",
        finalized_total_rupees=context.get("finalized_total_rupees") if context.get("finalized_total_rupees") is not None else "N/A",
        amount_due_rupees=context.get("amount_due_rupees") if context.get("amount_due_rupees") is not None else "N/A",
        other_pending_items=context.get("other_pending_items") or "N/A",
        address_needs=context.get("address_needs") or "",
        bundle_breakdown=context.get("bundle_breakdown") or "N/A",
        inquiry_floor_total_rupees=context.get("inquiry_floor_total_rupees") or 0,
        past_orders=context.get("past_orders_summary") or "none",
        previous_price=prev_price_str,
        available_products_str=available_products_str,
    )
