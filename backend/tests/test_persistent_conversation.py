"""Tests for the persistent-conversation + multi-purchase architecture.

Covers:
- _derive_state_from_decision: save_address action, prior-price honoring.
- _get_or_create_conv_product: get-active-or-create (repeat buy → new cycle row).
- _get_or_create_conversation: one permanent row per (seller, customer).
"""
from types import SimpleNamespace

import pytest

from app.bot.responder import _derive_state_from_decision

from tests.conftest_db import db_session  # noqa: F401


def _product(listed=1200_00, floor=1100_00):
    return SimpleNamespace(id="p1", name="clock", listed_price=listed, floor_price=floor)


def _conv():
    return SimpleNamespace(id="c1", product_id="p1")


# ---------------------------------------------------------------------------
# derive — save_address
# ---------------------------------------------------------------------------

def test_append_message_dedups_by_mid():
    from app.bot.conversation import _append_message
    conv = SimpleNamespace(messages=[])
    _append_message(conv, "customer", "hi", mid="m1")
    _append_message(conv, "customer", "hi", mid="m1")  # retry — must not duplicate
    assert [m["mid"] for m in conv.messages] == ["m1"]
    # No-mid messages are not deduped (synthetic/media markers).
    _append_message(conv, "bot", "[product photo]")
    _append_message(conv, "bot", "[product photo]")
    assert len(conv.messages) == 3


def test_record_customer_entries_dedups_by_mid():
    from app.workers.message_batch import _record_customer_entries
    conv = SimpleNamespace(messages=[{"role": "customer", "content": "hi", "mid": "m1"}])
    events = [
        {"type": "text", "text": "hi", "mid": "m1"},   # already in history
        {"type": "text", "text": "antique watch", "mid": "m2"},  # new
    ]
    _record_customer_entries(conv, events)
    assert [m.get("mid") for m in conv.messages] == ["m1", "m2"]


def test_per_product_unit_price_rejects_polluted_bundle_total():
    from app.bot.responder import _per_product_unit_price
    prod = SimpleNamespace(listed_price=999_00, floor_price=800_00)
    # last_counter/last_shown polluted with the bundle total (₹3249) → use listed.
    cp = SimpleNamespace(agreed_price=None, last_counter_price=3249_00, last_shown_price=3249_00)
    assert _per_product_unit_price(cp, prod) == 999_00
    # agreed_price polluted with a bundle total (₹3100 on a ₹999 product) → rejected.
    cp_a = SimpleNamespace(agreed_price=3100_00, last_counter_price=None, last_shown_price=None)
    assert _per_product_unit_price(cp_a, prod) == 999_00
    # A legit per-product discount (≤ listed) is honored.
    cp2 = SimpleNamespace(agreed_price=750_00, last_counter_price=750_00, last_shown_price=750_00)
    prod2 = SimpleNamespace(listed_price=800_00, floor_price=600_00)
    assert _per_product_unit_price(cp2, prod2) == 750_00
    # Below floor is clamped up to floor.
    cp3 = SimpleNamespace(agreed_price=500_00, last_counter_price=None, last_shown_price=None)
    assert _per_product_unit_price(cp3, prod2) == 600_00


def test_save_address_returns_payment_confirmed_with_flag():
    decision = {"action": "save_address", "customer_intent": "warm"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(), current_state="awaiting_address",
    )
    assert new_state == "payment_confirmed"
    assert extra.get("save_address") is True


# ---------------------------------------------------------------------------
# derive — prior-price honoring
# ---------------------------------------------------------------------------

def test_accept_honors_prior_price_below_floor():
    """A returning customer's recorded prior price (below current floor) is honored."""
    decision = {"action": "accept", "price": 1000_00, "customer_intent": "hot"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1100_00),
        previous_price_paise=1000_00,
    )
    assert new_state == "awaiting_payment"
    assert extra["agreed_price"] == 1000_00  # honored, not clamped up to floor


def test_accept_does_not_honor_fabricated_lower_price():
    """A figure below the recorded prior price is NOT honored — it clamps to the
    floor, so a fabricated "last time it was ₹500" can't beat the floor."""
    decision = {"action": "accept", "price": 500_00, "customer_intent": "hot"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1100_00),
        previous_price_paise=1000_00,
    )
    assert new_state == "awaiting_payment"
    # Clamped up to floor (1100), NOT the fabricated 500 nor the prior 1000.
    assert extra["agreed_price"] == 1100_00


# ---------------------------------------------------------------------------
# DB — get-active-or-create CP cycle
# ---------------------------------------------------------------------------

def _make_seller():
    import uuid
    from app.models.seller import Seller
    return Seller(
        instagram_id=f"ig-{uuid.uuid4().hex[:8]}",
        instagram_token="fake-token",
        instagram_page_id=f"pg-{uuid.uuid4().hex[:8]}",
        fb_page_id="fake-fb-page",
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
    )


async def _seed_seller_product_conv(db):
    import uuid
    from app.models.product import Product
    from app.models.conversation import Conversation

    seller = _make_seller()
    db.add(seller)
    await db.flush()
    product = Product(
        seller_id=seller.id, name="Clock", listed_price=1200_00, floor_price=1100_00, active=True,
    )
    db.add(product)
    await db.flush()
    conv = Conversation(
        seller_id=seller.id, customer_instagram_id=f"cust-{uuid.uuid4().hex[:8]}",
        product_id=product.id, messages=[],
    )
    db.add(conv)
    await db.flush()
    return seller, product, conv


@pytest.mark.asyncio
async def test_conv_product_repeat_buy_creates_new_cycle(db_session):  # noqa: F811
    from app.bot.conversation import _get_or_create_conv_product

    _, product, conv = await _seed_seller_product_conv(db_session)

    cp1 = await _get_or_create_conv_product(conv.id, product.id, db_session)
    # Same active cycle returned while not terminal.
    cp1b = await _get_or_create_conv_product(conv.id, product.id, db_session)
    assert cp1.id == cp1b.id

    # Finish the cycle → next call starts a NEW cycle row.
    cp1.state = "payment_confirmed"
    await db_session.flush()
    cp2 = await _get_or_create_conv_product(conv.id, product.id, db_session)
    assert cp2.id != cp1.id
    assert cp2.state == "product_inquiry"


@pytest.mark.asyncio
async def test_get_or_create_conversation_is_permanent(db_session):  # noqa: F811
    import uuid
    from app.api.webhooks.instagram import _get_or_create_conversation

    seller = _make_seller()
    db_session.add(seller)
    await db_session.flush()

    cust = f"cust-{uuid.uuid4().hex[:8]}"
    c1 = await _get_or_create_conversation(seller, cust, db_session)
    c1.messages = [{"role": "customer", "content": "hi"}]
    await db_session.flush()
    # Even after a "purchase" the same row is returned (no status, never closed).
    c2 = await _get_or_create_conversation(seller, cust, db_session)
    assert c1.id == c2.id
    assert c2.messages == [{"role": "customer", "content": "hi"}]


# ---------------------------------------------------------------------------
# DB — bundle deal order (multi-line, per-product, with quantities)
# ---------------------------------------------------------------------------

async def _seed_two_products(db):
    import uuid
    from app.models.product import Product
    from app.models.conversation import Conversation
    seller = _make_seller()
    db.add(seller)
    await db.flush()
    led = Product(seller_id=seller.id, name="LED clock", listed_price=2000_00, floor_price=1500_00, active=True)
    jho = Product(seller_id=seller.id, name="Small jhoomar", listed_price=999_00, floor_price=800_00, active=True)
    db.add_all([led, jho])
    await db.flush()
    conv = Conversation(
        seller_id=seller.id, customer_instagram_id=f"cust-{uuid.uuid4().hex[:8]}",
        product_id=jho.id, messages=[],
    )
    db.add(conv)
    await db.flush()
    return seller, led, jho, conv


@pytest.mark.asyncio
async def test_build_deal_order_creates_per_product_line_items(db_session):  # noqa: F811
    from app.bot.conversation import _build_deal_order, _get_or_create_conv_product
    from app.models.order import Order, OrderItem
    from sqlalchemy import select

    seller, led, jho, conv = await _seed_two_products(db_session)
    focused = await _get_or_create_conv_product(conv.id, jho.id, db_session)

    deal_lines = [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 2},
        {"product_id": str(jho.id), "unit_price_paise": 999_00, "quantity": 1},
    ]
    order = await _build_deal_order(conv, seller, focused, deal_lines, db_session)

    assert order.amount == 2 * 1900_00 + 999_00  # 4799_00
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert len(items) == 2
    by_unit = {oi.unit_price: oi.quantity for oi in items}
    assert by_unit[1900_00] == 2
    assert by_unit[999_00] == 1
    # Only one order exists for the conversation (no duplicates/stranded).
    orders = (await db_session.execute(
        select(Order).where(Order.conversation_id == conv.id)
    )).scalars().all()
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_build_deal_order_consolidates_prior_unpaid_order(db_session):  # noqa: F811
    """A product that hit payment alone (stranded awaiting_payment order) is absorbed
    into the bundle order — not left dangling."""
    from app.bot.conversation import _build_deal_order, _ensure_cycle_order, _get_or_create_conv_product
    from app.models.order import Order
    from sqlalchemy import select

    seller, led, jho, conv = await _seed_two_products(db_session)

    # LED clock hit payment alone first → its own awaiting_payment order.
    led_cp = await _get_or_create_conv_product(conv.id, led.id, db_session)
    led_cp.agreed_price = 1900_00
    led_cp.quantity = 2
    await _ensure_cycle_order(conv, seller, led_cp, None, db_session)

    # Then the jhoomar is added and the bundle is accepted.
    focused = await _get_or_create_conv_product(conv.id, jho.id, db_session)
    deal_lines = [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 2},
        {"product_id": str(jho.id), "unit_price_paise": 999_00, "quantity": 1},
    ]
    await _build_deal_order(conv, seller, focused, deal_lines, db_session)

    orders = (await db_session.execute(
        select(Order).where(Order.conversation_id == conv.id)
    )).scalars().all()
    assert len(orders) == 1  # stranded LED order consolidated away
    assert orders[0].amount == 2 * 1900_00 + 999_00


@pytest.mark.asyncio
async def test_mutating_deal_rebuilds_one_order_with_updated_quantities(db_session):  # noqa: F811
    """The combo changes across turns (led×2 → led×1 + jho×2). Each accept rebuilds
    ONE order from the current combo, consolidating the prior one and updating qty."""
    from app.bot.conversation import _build_deal_order, _get_or_create_conv_product
    from app.models.order import Order, OrderItem
    from sqlalchemy import select

    seller, led, jho, conv = await _seed_two_products(db_session)
    led_cp = await _get_or_create_conv_product(conv.id, led.id, db_session)

    # Turn 1: customer wants led ×2.
    await _build_deal_order(conv, seller, led_cp, [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 2},
    ], db_session)

    # Turn 2: combo changes to led ×1 + jho ×2.
    await _build_deal_order(conv, seller, led_cp, [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 1},
        {"product_id": str(jho.id), "unit_price_paise": 999_00, "quantity": 2},
    ], db_session)

    orders = (await db_session.execute(
        select(Order).where(Order.conversation_id == conv.id)
    )).scalars().all()
    assert len(orders) == 1  # prior led×2 order consolidated, not stranded
    order = orders[0]
    assert order.amount == 1 * 1900_00 + 2 * 999_00
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert {(oi.unit_price, oi.quantity) for oi in items} == {(1900_00, 1), (999_00, 2)}
    # led CP quantity updated from 2 → 1 by the rebuild.
    await db_session.refresh(led_cp)
    assert led_cp.quantity == 1
