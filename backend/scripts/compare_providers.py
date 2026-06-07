"""Candidate-vs-reference reply/decide parity eval.

Runs fixed conversation situations through a REFERENCE provider/model (default
the current prod model, Claude Haiku) and a CANDIDATE provider/model (default
gemini/gemini-2.5-flash-lite), prints replies side-by-side with
latency/tokens/cost, asks Claude to judge the candidate reply against the
reference, checks the candidate's decide JSON, and reports a parity score + cost
delta so "at par + cheaper" is measurable.

Configure via env: EVAL_REF_PROVIDER/EVAL_REF_MODEL,
EVAL_CANDIDATE_PROVIDER/EVAL_CANDIDATE_MODEL, EVAL_JUDGE_MODEL.

Run in-container (hits live APIs for both providers):
    docker compose run --rm -e PYTHONPATH=/app api python scripts/compare_providers.py

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
from app.integrations import llm_provider
from app.integrations.llm_pricing import compute_cost_usd

# Reference = current production model; candidate = the cheaper model under test.
REF_PROVIDER = os.environ.get("EVAL_REF_PROVIDER", "anthropic")
REF_MODEL = os.environ.get("EVAL_REF_MODEL", "claude-haiku-4-5-20251001")
CAND_PROVIDER = os.environ.get("EVAL_CANDIDATE_PROVIDER", "gemini")
CAND_MODEL = os.environ.get("EVAL_CANDIDATE_MODEL", "gemini-2.5-flash-lite")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "claude-sonnet-4-20250514")
REPLY_MAX_TOKENS = 200
DECIDE_MAX_TOKENS = 350


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

REPLY A (reference):
{reply_claude}

REPLY B (candidate):
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
        model=JUDGE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"overall": None, "note": f"judge parse failed: {text[:120]}"}


async def main():
    llm_provider._ensure_providers_registered()
    ref = llm_provider.get_provider(REF_PROVIDER)
    cand = llm_provider.get_provider(CAND_PROVIDER)
    judge_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    overalls = []
    decide_match = decide_valid = decide_total = 0
    ref_cost = cand_cost = 0.0
    print(f"\n{'='*100}\nCANDIDATE {CAND_PROVIDER}/{CAND_MODEL}  vs  REFERENCE {REF_PROVIDER}/{REF_MODEL}"
          f"\nreply parity (judge 1-5) + decide JSON check + cost\n{'='*100}")

    for sc in SCENARIOS:
        ctx = sc["ctx"]
        # --- generate_reply ---
        rr, tr, ir, orr, cr = await _capture(ref.generate_reply(ctx, model=REF_MODEL, max_tokens=REPLY_MAX_TOKENS))
        rk, tk, ik, ok, ck = await _capture(cand.generate_reply(ctx, model=CAND_MODEL, max_tokens=REPLY_MAX_TOKENS))
        ref_cost += cr
        cand_cost += ck
        verdict = await _judge(judge_client, sc, rr, rk)
        if isinstance(verdict.get("overall"), (int, float)):
            overalls.append(verdict["overall"])

        # --- decide (JSON validity + action agreement) ---
        decide_total += 1
        d_ref, *_ = await _capture(ref.decide(ctx, model=REF_MODEL, max_tokens=DECIDE_MAX_TOKENS))
        d_cand, *_ = await _capture(cand.decide(ctx, model=CAND_MODEL, max_tokens=DECIDE_MAX_TOKENS))
        ref_action = d_ref.get("action") if isinstance(d_ref, dict) else None
        cand_action = d_cand.get("action") if isinstance(d_cand, dict) else None
        if isinstance(d_cand, dict):
            decide_valid += 1
        if ref_action and ref_action == cand_action:
            decide_match += 1

        print(f"\n── {sc['name']} ──  customer: {ctx['customer_message']!r}")
        print(f"   facts: {sc['facts']}")
        print(f"   REF  ({tr:.1f}s, {ir}+{orr}tok, ${cr:.5f}): {rr}")
        print(f"   CAND ({tk:.1f}s, {ik}+{ok}tok, ${ck:.5f}): {rk}")
        print(f"   JUDGE candidate: tone={verdict.get('hinglish_tone')} "
              f"correct={verdict.get('factual_correctness')} price={verdict.get('price_accuracy')} "
              f"brevity={verdict.get('brevity')} overall={verdict.get('overall')} — {verdict.get('note')}")
        print(f"   DECIDE action: ref={ref_action} cand={cand_action} "
              f"{'(JSON OK)' if isinstance(d_cand, dict) else '(CAND JSON FAILED)'}")

    print(f"\n{'='*100}")
    if overalls:
        print(f"Mean candidate reply parity (overall 1-5): {sum(overalls)/len(overalls):.2f} over {len(overalls)}")
    print(f"Decide JSON valid: {decide_valid}/{decide_total}   action matches ref: {decide_match}/{decide_total}")
    if ref_cost:
        print(f"Reply cost over {len(SCENARIOS)} turns: ref ${ref_cost:.5f}  cand ${cand_cost:.5f}  "
              f"({ref_cost/cand_cost:.1f}x cheaper)" if cand_cost else "")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    asyncio.run(main())
