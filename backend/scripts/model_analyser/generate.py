"""Generate golden conversations via opus-4.8 self-play.

For each persona, opus-4.8 plays the CUSTOMER while the real bot pipeline
(`advance_conversation`) runs with every method forced to opus-4.8. A recording
wrapper captures each turn's method calls (decide/reply/subagents) with their
exact inputs + opus outputs. The whole run happens in a DB transaction that is
ROLLED BACK at the end — the golden data is persisted to JSON, not the DB — and
Instagram sends are stubbed, so nothing leaves the process.

Usage (from backend/, inside the api container):
    python -m scripts.model_analyser.cli generate [--n N] [--max-turns 12]
"""
from __future__ import annotations

import json
import pathlib

import yaml
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.conversation import Conversation
from app.models.seller import Seller

from .recorder import recording
from .runtime import OPUS_MODEL, force_opus
from .schema import GoldenConversation, GoldenTurn, MethodCall

HERE = pathlib.Path(__file__).parent
GOLDEN_DIR = HERE / "golden"
SELLER_ID = "ac2303e0-00f3-4470-98ca-36a8f4ae5866"
DEFAULT_MAX_TURNS = 12
# Decision actions that end a conversation (plus conversation.status == closed).
END_ACTIONS = {"accept", "acknowledge_and_close", "not_interested"}

_CUSTOMER_SYSTEM = (
    "You are role-playing a CUSTOMER chatting with an Indian Instagram seller in a DM. "
    "Stay fully in character.\n"
    "Persona goal: {goal}\n"
    "Style: {style}\n"
    "You are interested in: {product_hint}.\n\n"
    "Rules:\n"
    "- Write ONE short message in natural Hinglish (Roman script), like a real IG buyer.\n"
    "- Pursue your goal across turns; react to what the seller just said.\n"
    "- Do NOT narrate or explain; output only the message text.\n"
    "- When your goal is satisfied (bought, or you decide to leave), output exactly: <END>"
)


def _render_history(messages: list[dict]) -> str:
    if not messages:
        return "(no messages yet — you start)"
    lines = []
    for m in messages:
        role = "Seller" if m.get("role") in ("bot", "seller") else "You"
        text = m.get("text") or m.get("content") or ""
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


async def _opus_customer(client: AsyncAnthropic, persona: dict, messages: list[dict]) -> str:
    """One customer turn from opus-4.8 (direct SDK call — NOT through the bot
    registry, so it is never captured into the golden record)."""
    resp = await client.messages.create(
        model=OPUS_MODEL,
        max_tokens=120,
        system=_CUSTOMER_SYSTEM.format(
            goal=persona["goal"], style=persona["style"],
            product_hint=persona.get("product_hint", "the product"),
        ),
        messages=[{
            "role": "user",
            "content": f"Conversation so far:\n{_render_history(messages)}\n\nYour next message:",
        }],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _to_calls(records: list[dict]) -> list[MethodCall]:
    calls = []
    for r in records:
        calls.append(MethodCall(
            method=r["method"],
            context=r.get("context") if "context" in r else {"_inputs": r.get("inputs")},
            golden_output=r["output"],
            golden_model=r.get("model", OPUS_MODEL),
        ))
    return calls


def _decide_action(calls: list[MethodCall]) -> str | None:
    for c in calls:
        if c.method == "decide" and isinstance(c.golden_output, dict):
            return c.golden_output.get("action")
    return None


async def _generate_one(persona: dict, seller: Seller, db: AsyncSession,
                        anthropic_client: AsyncAnthropic, max_turns: int) -> GoldenConversation:
    conv = Conversation(
        seller_id=seller.id,
        customer_instagram_id=f"analyser_{persona['id']}",
        customer_name="Test Buyer",
        customer_gender="female",   # preset so the pipeline skips gender-guess LLM call
        status="active",
        messages=[],
    )
    db.add(conv)
    await db.flush()

    from app.bot.conversation import advance_conversation

    turns: list[GoldenTurn] = []
    last_product_id = None
    with recording() as sink, force_opus():
        for i in range(max_turns):
            customer_msg = await _opus_customer(anthropic_client, persona, conv.messages or [])
            if not customer_msg or "<END>" in customer_msg:
                break
            before = len(sink)
            try:
                await advance_conversation(conv, seller, customer_msg, db, send_reply=False)
            except Exception as exc:
                # A bad model output (e.g. a hallucinated product_id) can crash a
                # turn — keep the turns captured so far and end this conversation.
                print(f"      · turn {i} aborted ({type(exc).__name__}); salvaging {len(turns)} turns")
                break
            calls = _to_calls(sink[before:])
            turns.append(GoldenTurn(index=i, customer_message=customer_msg, calls=calls))
            if conv.product_id:
                last_product_id = conv.product_id
            if conv.status == "closed" or _decide_action(calls) in END_ACTIONS:
                break

    return GoldenConversation(
        conv_id=persona["id"], persona=persona, seller_id=str(seller.id),
        product_ids=[str(last_product_id)] if last_product_id else [],
        turns=turns,
    )


async def run(n: int | None = None, max_turns: int = DEFAULT_MAX_TURNS) -> None:
    personas = yaml.safe_load((HERE / "personas.yaml").read_text())["personas"]
    if n:
        personas = personas[:n]
    GOLDEN_DIR.mkdir(exist_ok=True)

    # Stub Instagram sends so generation never touches the network.
    from app.integrations.instagram import InstagramClient

    async def _noop(*a, **k):
        return {}

    InstagramClient.send_message = _noop      # type: ignore[assignment]
    InstagramClient.send_image = _noop        # type: ignore[assignment]

    anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Own engine/session so we can run everything in ONE transaction and roll it
    # back — the DB is never mutated; golden data lives in JSON files.
    # Each persona runs in its OWN session so a bad turn (e.g. a model returning
    # a malformed product_id, which the responder feeds into a DB query) can only
    # fail that persona — the rest continue. Already-generated personas are
    # skipped so a re-run resumes.
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    done = 0
    try:
        for persona in personas:
            out = GOLDEN_DIR / f"conv_{persona['id']}.json"
            if out.exists():
                print(f"  • {persona['id']:<18} already exists — skipping")
                done += 1
                continue
            try:
                async with factory() as db:
                    seller = (await db.execute(
                        select(Seller).where(Seller.id == SELLER_ID))).scalar_one()
                    gc = await _generate_one(persona, seller, db, anthropic_client, max_turns)
                    await db.rollback()   # discard this persona's DB writes
                out.write_text(json.dumps(gc.to_dict(), indent=2, ensure_ascii=False, default=str))
                n_calls = sum(len(t.calls) for t in gc.turns)
                print(f"  ✓ {persona['id']:<18} {len(gc.turns):>2} turns, {n_calls:>3} calls → {out.name}")
                done += 1
            except Exception as exc:
                print(f"  ✗ {persona['id']:<18} failed: {type(exc).__name__}: {exc}")
    finally:
        await eng.dispose()
    print(f"\nWrote {done}/{len(personas)} golden conversations to {GOLDEN_DIR}/ (DB rolled back).")
