"""Six frozen context episodes: real algorithms, scripted raw repository rows.

No database, provider, LLM, queue/persistence or SQL-predicate proof is claimed.
The scripts do not replace context selection, decision, facts validation or render.
"""
from tests.safety import install_test_safety

install_test_safety()  # Before application imports, including direct collection.

from collections import deque
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.config import settings
from app.services import sku_fact_replies as facts
from app.services import whatsapp_context as context
from app.services.channel_readiness import CatalogueAuthorityHandoff
from app.services.instagram_ingress import normalize_message


TENANT = UUID("10000000-0000-4000-8000-000000000101")
A = UUID("20000000-0000-4000-8000-000000000101")
B = UUID("20000000-0000-4000-8000-000000000102")
CONTACT = UUID("30000000-0000-4000-8000-000000000101")
A_URL = "https://www.instagram.com/reel/Approved_A/"
B_URL = "https://www.instagram.com/reel/Approved_B/"
UNKNOWN_URL = "https://www.instagram.com/reel/Unknown_C/"
UNSUPPORTED_URL = "https://www.instagram.com/share/reel/opaque/"
STAMP = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)


class RawRows:
    """Strict script of scalar/projection results, never an in-memory SQL engine.

    Rows are supplied as though a repository returned them. We do not evaluate
    SQL tenant, activation, lock, publication or current-state predicates.
    Unexpected query types/counts fail instead of returning permissive defaults.
    """

    def __init__(self, *, scalars=(), scalar=(), execute=()):
        self.pending = {key: deque(values) for key, values in
                        {"scalars": scalars, "scalar": scalar, "execute": execute}.items()}
        self.calls = []
        self.no_autoflush = nullcontext()

    def take(self, method, statement):
        self.calls.append(method)
        assert self.pending[method], f"Unexpected {method} query"
        step = self.pending[method].popleft()
        assert tuple(c.key for c in statement.selected_columns) == step["columns"]
        values = list(statement.compile().params.values())
        flattened = [item for value in values for item in
                     (value if isinstance(value, (list, tuple)) else [value])]
        assert TENANT in flattened, "Repository request lost its tenant binding"
        assert {v for v in flattened if isinstance(v, UUID) and v != TENANT} == step["products"]
        if step["code"]:
            assert any(isinstance(v, str) and "/" + step["code"] + "/?" in v for v in values), "Wrong explicit reel requested"
        return step["rows"]

    async def scalars(self, statement):
        rows = self.take("scalars", statement)
        return SimpleNamespace(all=lambda: rows)

    async def scalar(self, statement):
        return self.take("scalar", statement)

    async def execute(self, statement):
        rows = self.take("execute", statement)
        result = SimpleNamespace(all=lambda: rows)
        result.mappings = lambda: result
        return result

    def exhausted(self):
        assert not any(self.pending.values()), "Expected real algorithm queries were not exercised"


def raw(rows, *, code=None, products=(), columns=("id",)):
    return {"rows": rows, "code": code, "products": set(products), "columns": columns}


def mapped(product_id, name):
    return raw([(product_id, name)], products=[product_id], columns=("id", "name"))


def activated(product_id):
    return raw(product_id, products=[product_id], columns=("product_id",))


def projected(product_id, name, price):
    return raw(observation(product_id, name, price), products=[product_id],
               columns=("id", "name", "revision", "sku_id", "options", "price_minor", "currency", "stock_available", "observed_at"))


@pytest.fixture(autouse=True)
def sku_rollout(monkeypatch):
    # Synthetic trusted rollout configuration, not provider/account enablement.
    monkeypatch.setattr(settings, "V1_SKU_FACT_REPLIES_ENABLED", True)


def observation(product_id, name, price):
    return [{"id": product_id, "name": name, "revision": 7,
             "sku_id": UUID("40000000-0000-4000-8000-000000000101"),
             "options": {"Size": "M"}, "price_minor": price, "currency": "INR",
             "stock_available": 2, "observed_at": STAMP}]


def event(mid, *, quote=None):
    result = {"id": mid, "type": "text", "timestamp": str(int(STAMP.timestamp()))}
    if quote:
        result["context"] = {"id": quote}
    return result


async def inbound(db, text, *, mid="new-turn", quote="old-A"):
    return await context.inbound_context(db, SimpleNamespace(seller_id=TENANT),
                                         SimpleNamespace(id=CONTACT), event(mid, quote=quote), text)


@pytest.mark.asyncio
async def test_c01_explicit_b_replaces_approved_a_quote_and_renders_only_b():
    """Sequential actual context/reply assembly; no persisted conversation claim."""
    db = RawRows(scalars=[raw([A], code="Approved_A"), raw([A], code="Approved_A"),
                         raw([B], code="Approved_B"), raw([B], code="Approved_B")],
                 scalar=[activated(A), activated(B)], execute=[
        mapped(A, "Approved A"), projected(A, "Approved A", 11111),
        mapped(B, "Approved B"), projected(B, "Approved B", 22222)])
    first = await inbound(db, A_URL + " price?", mid="old-A", quote=None)
    first_reply = await context.reel_reply_decision(db, TENANT, first["reel_context"], A_URL + " price?")
    assert first_reply.reply == (
        "Current catalogue: Approved A.\n"
        "• Size: M — ₹111.11; recorded available: 2.\n"
        "Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.")
    switched = await inbound(db, B_URL + " price?")
    assert switched["reply_to_message_id"] == "old-A"
    assert switched["reel_context"]["source"] == "message_link"
    assert switched["reel_context"]["references"] == [{"shortcode": "Approved_B", "url": B_URL,
        "products": [{"id": str(B), "name": "Approved B"}], "status": "matched"}]
    reply = await context.reel_reply_decision(db, TENANT, switched["reel_context"], B_URL + " price?")
    assert reply.reply == (
        "Current catalogue: Approved B.\n"
        "• Size: M — ₹222.22; recorded available: 2.\n"
        "Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.")
    assert reply.review_reason is None
    assert "Approved A" not in reply.reply and "111.11" not in reply.reply
    db.exhausted()


@pytest.mark.asyncio
async def test_c02_two_distinct_explicit_reels_never_choose_first_or_last_or_quote():
    db = RawRows(scalars=[raw([A], code="Approved_A"), raw([B], code="Approved_B")],
                 execute=[mapped(A, "Approved A"), mapped(B, "Approved B")])
    text = A_URL + " " + B_URL + " price?"
    parsed = await inbound(db, text)
    refs = parsed["reel_context"]["references"]
    assert [r["shortcode"] for r in refs] == ["Approved_A", "Approved_B"]
    assert all(r["status"] == "matched" for r in refs)
    decision = await context.reel_reply_decision(db, TENANT, parsed["reel_context"], text)
    assert decision.reply is None and decision.review_reason is None
    assert db.calls == ["scalars", "execute", "scalars", "execute"]
    db.exhausted()  # No quote lookup, activation/read-facts or first/last reply.


@pytest.mark.asyncio
async def test_c03_multi_product_reel_overrides_old_quote_without_unrelated_reply():
    db = RawRows(scalars=[raw([A, B], code="Approved_B")], execute=[
        raw([(A, "Approved A"), (B, "Approved B")], products=[A, B], columns=("id", "name"))])
    parsed = await inbound(db, B_URL + " price?")
    ref = parsed["reel_context"]["references"][0]
    assert ref["shortcode"] == "Approved_B" and ref["status"] == "ambiguous"
    assert {p["id"] for p in ref["products"]} == {str(A), str(B)}
    decision = await context.reel_reply_decision(db, TENANT, parsed["reel_context"], B_URL + " price?")
    assert decision.reply is None and decision.review_reason is None
    assert db.calls == ["scalars", "execute"]
    db.exhausted()


@pytest.mark.asyncio
async def test_c04_unknown_new_reel_overrides_old_quote_without_a_fallback():
    db = RawRows(scalars=[raw([], code="Unknown_C")])
    parsed = await inbound(db, UNKNOWN_URL + " price?")
    assert parsed["reel_context"]["source"] == "message_link"
    assert parsed["reel_context"]["references"] == [{"shortcode": "Unknown_C", "url": UNKNOWN_URL,
                                                        "products": [], "status": "unlinked"}]
    decision = await context.reel_reply_decision(db, TENANT, parsed["reel_context"], UNKNOWN_URL + " price?")
    assert decision.reply is None and decision.review_reason is None
    assert db.calls == ["scalars"]
    db.exhausted()


def ig_event(text):
    return {"sender": {"id": "synthetic-customer"}, "recipient": {"id": "synthetic-account"},
            "timestamp": int(STAMP.timestamp() * 1000),
            "message": {"mid": "new-ig-turn", "text": text, "reply_to": {"mid": "old-A"}}}


def old_focus():
    return SimpleNamespace(product_id=A, messages=[{"role": "bot", "mid": "old-A",
                            "product_id": str(A), "content": "Obsolete A description"}])


@pytest.mark.asyncio
async def test_c05_single_ig_text_new_b_and_reply_to_a_requires_explicit_clarification():
    events = normalize_message(ig_event(B_URL + " price?"))
    assert events == [{"type": "text", "text": B_URL + " price?", "reply_to_mid": "old-A", "mid": "new-ig-turn"}]
    db = RawRows(scalars=[raw([B], code="Approved_B"),
                         raw([A, B], products=[A, B], columns=("product_id",)),
                         raw([A, B], products=[A, B])])
    conversation = old_focus()
    with pytest.raises(CatalogueAuthorityHandoff, match="explicit clarification"):
        await facts.freeze_instagram_batch(db, TENANT, conversation, events)
    assert conversation.product_id == A  # No persistent/focus mutation by freeze.
    assert not hasattr(conversation, "_sku_batch_facts_allowed")
    db.exhausted()


@pytest.mark.asyncio
async def test_c06_unsupported_new_ig_share_url_cannot_inherit_valid_old_a_reply():
    events = normalize_message(ig_event(UNSUPPORTED_URL + " price?"))
    assert events[0]["reply_to_mid"] == "old-A" and UNSUPPORTED_URL in events[0]["text"]
    db = RawRows(scalars=[raw([A], products=[A], columns=("product_id",)), raw([A], products=[A])])
    conversation = old_focus()
    with pytest.raises(CatalogueAuthorityHandoff, match="explicit clarification"):
        await facts.freeze_instagram_batch(db, TENANT, conversation, events)
    assert conversation.product_id == A
    assert not hasattr(conversation, "_sku_batch_facts_allowed")
    db.exhausted()
