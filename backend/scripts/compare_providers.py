"""Sarvam-vs-Claude reply/decide parity eval.

Runs a set of fixed conversation situations through BOTH providers (directly,
bypassing the factory fallback), prints replies side-by-side with
latency/tokens/cost, and asks Claude to judge the Sarvam reply against the
Claude reply. Aggregates an overall parity score so "at par" is measurable and
regressions are visible.

Run in-container (hits live Anthropic + Sarvam APIs):
    docker compose run --rm api python scripts/compare_providers.py

It does NOT touch the DB — prompts resolve via prompt_store (DB→file fallback)
and token/cost come from the in-memory llm_logging capture, not persisted.
"""
import asyncio
import json
import os
import time

import anthropic

from app.config import settings
from app.integrations import llm_logging as L
from app.integrations.claude import ClaudeProvider
from app.integrations.llm_pricing import compute_cost_usd
from app.integrations.sarvam import SarvamProvider

CLAUDE_MODEL = os.environ.get("EVAL_CLAUDE_MODEL", "claude-sonnet-4-20250514")
SARVAM_MODEL = os.environ.get("EVAL_SARVAM_MODEL", "sarvam-30b")
REPLY_MAX_TOKENS = 200


def _base_ctx(**over) -> dict:
    ctx = {
        "decision": {"action": "engage", "customer_intent": "warm"},
        "persona": {"tone": "friendly Hinglish, warm, casual", "name": "Rahul"},
        "product_name": "Gold Wall Clock",
        "product_description": "Premium gold-finish wall clock with glass front and gear design",
        "product_tag_values": {"Material": "metal", "Color": "gold"},
        "listed_price_rupees": 1800,
        "display_price_rupees": 1800,
        "floor_price_rupees": 1400,
        "warranty_months": 12,
        "stock_quantity": 8,
        "policies": {"cod": True, "cod_charges": 0, "return_days": 7, "delivery_days": "3-5 days", "payment_modes": ["upi"]},
        "last_counter_price": None,
        "last_shown_price": None,
        "total_photos": 3,
        "address_term": "ji",
        "other_active_products": [],
        "other_inquiry_products": [],
        "multi_price_breakdown": None,
        "bundle_breakdown": None,
        "inquiry_floor_total_rupees": 0,
        "message_history": [],
        "customer_message": "",
    }
    ctx.update(over)
    return ctx


# Each scenario: a customer turn + the context the bot would have. The "facts"
# string tells the judge the ground truth to check Sarvam's reply against.
SCENARIOS = [
    {
        "name": "warranty_question",
        "facts": "Warranty is 12 months.",
        "ctx": _base_ctx(
            decision={"action": "engage", "customer_intent": "warm"},
            customer_message="iski warranty kitni hai?",
            message_history=[{"role": "customer", "content": "iski warranty kitni hai?"}],
        ),
    },
    {
        "name": "stock_question",
        "facts": "Stock is 8 units (in stock).",
        "ctx": _base_ctx(
            stock_quantity=8,
            customer_message="stock hai abhi?",
            message_history=[{"role": "customer", "content": "stock hai abhi?"}],
        ),
    },
    {
        "name": "cod_policy_question",
        "facts": "COD is available with no extra charge; 7-day returns; delivery 3-5 days; UPI accepted.",
        "ctx": _base_ctx(
            customer_message="COD chalega kya? aur return policy?",
            message_history=[{"role": "customer", "content": "COD chalega kya? aur return policy?"}],
        ),
    },
    {
        "name": "price_lock_after_discount",
        "facts": "Listed ₹1800 but customer was already shown ₹1600 (last_shown). Bot must NOT quote above ₹1600 — should quote ₹1600 or lower.",
        "ctx": _base_ctx(
            display_price_rupees=1600,
            last_counter_price=160000,
            last_shown_price=160000,
            decision={"action": "counter", "price": 160000, "customer_intent": "hot"},
            customer_message="final price batao",
            message_history=[
                {"role": "customer", "content": "kitne ka hai?"},
                {"role": "bot", "content": "₹1800 ji, par aapke liye ₹1600 kar dunga"},
                {"role": "customer", "content": "final price batao"},
            ],
        ),
    },
    {
        "name": "counter_offer",
        "facts": "Customer offered low; bot should counter at ₹1500 (the decision price). Floor is ₹1400 — never below.",
        "ctx": _base_ctx(
            decision={"action": "counter", "price": 150000, "customer_intent": "warm"},
            customer_message="1200 me dedo",
            message_history=[
                {"role": "customer", "content": "kitne ka?"},
                {"role": "bot", "content": "₹1800 ji"},
                {"role": "customer", "content": "1200 me dedo"},
            ],
        ),
    },
    {
        "name": "disengage_ack",
        "facts": "Customer is leaving ('rehne do'). Bot should warmly acknowledge, NOT push price, NOT hard-sell.",
        "ctx": _base_ctx(
            decision={"action": "acknowledge_and_close", "customer_intent": "cold"},
            customer_message="rehne do abhi",
            message_history=[
                {"role": "customer", "content": "kitne ka?"},
                {"role": "bot", "content": "₹1800 ji"},
                {"role": "customer", "content": "rehne do abhi"},
            ],
        ),
    },
]


async def _capture(coro):
    """Run a provider call inside an llm_logging capture; return
    (output, latency_s, in_tok, out_tok, cost_usd)."""
    token = L.begin(conversation_id=None)
    t0 = time.monotonic()
    try:
        out = await coro
    except Exception as exc:  # show failures inline rather than aborting the run
        out = f"<ERROR: {type(exc).__name__}: {exc}>"
    dt = time.monotonic() - t0
    recs = list(L.current().records) if L.current() else []
    L.end(token)
    in_tok = sum((r.input_tokens or 0) for r in recs)
    out_tok = sum((r.output_tokens or 0) for r in recs)
    cost = 0.0
    for r in recs:
        c = compute_cost_usd(r.model, r.input_tokens, r.output_tokens,
                             r.cache_read_input_tokens, r.cache_creation_input_tokens)
        if c is not None:
            cost += float(c)
    return out, dt, in_tok, out_tok, cost


async def _judge(client, scenario, reply_claude, reply_sarvam) -> dict:
    prompt = f"""You are evaluating two Hinglish Instagram sales-bot replies for the SAME situation.

SITUATION: {scenario['name']}
GROUND-TRUTH FACTS the reply must respect: {scenario['facts']}
CUSTOMER MESSAGE: {scenario['ctx']['customer_message']!r}

REPLY A (reference, Claude):
{reply_claude}

REPLY B (candidate, Sarvam):
{reply_sarvam}

Score REPLY B on a 1-5 scale (5=best) on each dimension, judged against the facts
and using REPLY A as a quality reference:
- hinglish_tone: natural, warm, DM-length Hinglish
- factual_correctness: consistent with the ground-truth facts, invents nothing
- price_accuracy: any price quoted is correct and never above an already-shown lower price
- brevity: short like a real DM
- overall: holistic parity with REPLY A

Return ONLY JSON:
{{"hinglish_tone":n,"factual_correctness":n,"price_accuracy":n,"brevity":n,"overall":n,"note":"one short sentence"}}"""
    resp = await client.messages.create(
        model=CLAUDE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"overall": None, "note": f"judge parse failed: {text[:120]}"}


async def main():
    claude = ClaudeProvider()
    sarvam = SarvamProvider()
    judge_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    overalls = []
    print(f"\n{'='*100}\nSarvam ({SARVAM_MODEL}) vs Claude ({CLAUDE_MODEL}) — reply parity eval"
          f"\nreasoning_effort={settings.SARVAM_REASONING_EFFORT} headroom={settings.SARVAM_REASONING_HEADROOM_TOKENS}\n{'='*100}")

    for sc in SCENARIOS:
        ctx = sc["ctx"]
        rc, tc, ic, oc, cc = await _capture(claude.generate_reply(ctx, model=CLAUDE_MODEL, max_tokens=REPLY_MAX_TOKENS))
        rs, ts, is_, os_, cs = await _capture(sarvam.generate_reply(ctx, model=SARVAM_MODEL, max_tokens=REPLY_MAX_TOKENS))
        verdict = await _judge(judge_client, sc, rc, rs)
        if isinstance(verdict.get("overall"), (int, float)):
            overalls.append(verdict["overall"])

        print(f"\n── {sc['name']} ──  customer: {ctx['customer_message']!r}")
        print(f"   facts: {sc['facts']}")
        print(f"   CLAUDE ({tc:.1f}s, {ic}+{oc}tok, ${cc:.5f}): {rc}")
        print(f"   SARVAM ({ts:.1f}s, {is_}+{os_}tok, ${cs:.5f}): {rs}")
        print(f"   JUDGE B(Sarvam): tone={verdict.get('hinglish_tone')} "
              f"correct={verdict.get('factual_correctness')} price={verdict.get('price_accuracy')} "
              f"brevity={verdict.get('brevity')} overall={verdict.get('overall')} — {verdict.get('note')}")

    if overalls:
        print(f"\n{'='*100}\nMean Sarvam parity (overall, 1-5): {sum(overalls)/len(overalls):.2f}  "
              f"over {len(overalls)} scenarios\n{'='*100}\n")


if __name__ == "__main__":
    asyncio.run(main())
