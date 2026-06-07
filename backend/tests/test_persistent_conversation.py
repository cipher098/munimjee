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


def test_clean_reply_strips_photo_markers():
    """The model sometimes echoes internal [product photo] markers into its reply text;
    these must be stripped (photos are sent separately) and blank lines collapsed."""
    from app.bot.responder import _clean_reply
    out = _clean_reply("[product photo]\n[product photo]\n[product photo]\n\nHaan madam! Ye sab hai 😊")
    assert "[product photo]" not in out and "photo]" not in out
    assert out.startswith("Haan madam!")
    # [photo] variant and em-dash also handled.
    assert _clean_reply("[photo] price ₹500 — final") == "price ₹500  final"


def test_tag_last_bot_message_mid_preserves_existing_product_id():
    """A photo message already tagged with ITS OWN product id must keep it — the mid
    tag must not clobber it with the focused conversation.product_id (the multi-product
    photo mis-attribution bug)."""
    from app.bot.conversation import _tag_last_bot_message_mid
    conv = SimpleNamespace(
        product_id="focused-deal-product",
        messages=[{"role": "bot", "content": "[product photo]", "product_id": "deer-light-id"}],
    )
    _tag_last_bot_message_mid(conv, "mid-123")
    assert conv.messages[-1]["product_id"] == "deer-light-id"  # NOT clobbered
    assert conv.messages[-1]["mid"] == "mid-123"


def test_tag_last_bot_message_mid_sets_product_id_when_absent():
    """A text reply with no product_id still gets tagged with the focused product so
    reply_to on it resolves correctly."""
    from app.bot.conversation import _tag_last_bot_message_mid
    conv = SimpleNamespace(
        product_id="focused-product",
        messages=[{"role": "bot", "content": "Ye clock hai madam"}],
    )
    _tag_last_bot_message_mid(conv, "mid-456")
    assert conv.messages[-1]["product_id"] == "focused-product"
    assert conv.messages[-1]["mid"] == "mid-456"


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
# multi-product basket combo discount
# ---------------------------------------------------------------------------

def test_split_combo_total_clamps_to_sum_of_floors():
    """A combo total below the sum of per-product floors is clamped UP; each
    returned unit price stays at/above that product's floor."""
    from app.bot.responder import _split_combo_total
    lines = [
        {"floor_paise": 900_00, "listed_paise": 1200_00, "quantity": 1},   # clock
        {"floor_paise": 600_00, "listed_paise": 800_00, "quantity": 1},    # lamp
        {"floor_paise": 1100_00, "listed_paise": 1500_00, "quantity": 1},  # watch
    ]
    # Ask for ₹2000 — below sum-of-floors (₹2600). Must clamp to floors.
    units = _split_combo_total(lines, 2000_00)
    assert units == [900_00, 600_00, 1100_00]
    assert sum(units) == 2600_00


def test_split_combo_total_distributes_surplus_proportionally():
    """A combo total above sum-of-floors splits the surplus by listed value and
    sums (within rounding) to the requested total."""
    from app.bot.responder import _split_combo_total
    lines = [
        {"floor_paise": 900_00, "listed_paise": 1200_00, "quantity": 1},
        {"floor_paise": 600_00, "listed_paise": 800_00, "quantity": 1},
        {"floor_paise": 1100_00, "listed_paise": 1500_00, "quantity": 1},
    ]
    units = _split_combo_total(lines, 3100_00)
    # Each line >= its floor, and the total is within a rupee of the ask (int split).
    assert units[0] >= 900_00 and units[1] >= 600_00 and units[2] >= 1100_00
    assert abs(sum(units) - 3100_00) <= 100  # <= ₹1 rounding drift across 3 lines


def test_split_combo_total_respects_quantity():
    """Per-unit prices honor floors even when quantities are involved."""
    from app.bot.responder import _split_combo_total
    lines = [
        {"floor_paise": 900_00, "listed_paise": 1200_00, "quantity": 2},
        {"floor_paise": 600_00, "listed_paise": 800_00, "quantity": 1},
    ]
    # sum-of-floors = 900*2 + 600 = 2400. Ask ₹3000 → surplus ₹600.
    units = _split_combo_total(lines, 3000_00)
    assert units[0] >= 900_00 and units[1] >= 600_00
    total = units[0] * 2 + units[1] * 1
    assert total >= 2400_00 and abs(total - 3000_00) <= 200


def test_multi_product_bulk_discount_does_not_single_floor_clamp():
    """A basket bulk_discount returns awaiting_payment WITHOUT stamping the total as a
    per-product agreed_price (the caller distributes it across lines instead)."""
    decision = {
        "action": "bulk_discount",
        "price": 3100_00,  # basket total, far above any single floor
        "customer_intent": "bulk",
        "deal_items": [
            {"product_id": "p1", "quantity": 1},
            {"product_id": "p2", "quantity": 1},
        ],
    }
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1100_00),
    )
    assert new_state == "awaiting_payment"
    assert "agreed_price" not in extra  # NOT stamped as a single-product price


def test_single_product_bulk_discount_floor_clamps_per_piece():
    """A single-product bulk_discount still floor-clamps the per-piece price."""
    decision = {
        "action": "bulk_discount",
        "price": 800_00,  # below floor
        "customer_intent": "bulk",
        "deal_items": [{"product_id": "p1", "quantity": 5}],
    }
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1100_00),
    )
    assert new_state == "awaiting_payment"
    assert extra["agreed_price"] == 1100_00  # clamped up to floor


# ---------------------------------------------------------------------------
# final price guard — enforce_unit_price
# ---------------------------------------------------------------------------

def test_enforce_unit_price_clamps_below_floor_up():
    from app.bot.responder import enforce_unit_price
    # ₹500 below floor ₹900 → clamps UP to 900.
    assert enforce_unit_price(500_00, 900_00, 1200_00) == 900_00


def test_enforce_unit_price_clamps_above_ceiling_down():
    from app.bot.responder import enforce_unit_price
    # ₹1300 above last-offered ceiling ₹1000 → clamps DOWN to 1000.
    assert enforce_unit_price(1300_00, 900_00, 1000_00) == 1000_00


def test_enforce_unit_price_within_bounds_unchanged():
    from app.bot.responder import enforce_unit_price
    assert enforce_unit_price(1000_00, 900_00, 1200_00) == 1000_00


def test_enforce_unit_price_floor_wins_over_ceiling_on_misconfig():
    from app.bot.responder import enforce_unit_price
    # Misconfig: floor (1000) > ceiling (800). Cost protection wins → 1000.
    assert enforce_unit_price(900_00, 1000_00, 800_00) == 1000_00


def test_enforce_unit_price_tolerates_missing_bounds():
    from app.bot.responder import enforce_unit_price
    assert enforce_unit_price(1000_00, None, None) == 1000_00
    assert enforce_unit_price(0, 900_00, 1200_00) == 900_00  # zero/None unit → floor


def test_price_ceiling_prefers_last_shown_then_counter_then_listed():
    from app.bot.responder import _price_ceiling
    prod = SimpleNamespace(listed_price=1200_00)
    assert _price_ceiling(SimpleNamespace(last_shown_price=1000_00, last_counter_price=1050_00), prod) == 1000_00
    assert _price_ceiling(SimpleNamespace(last_shown_price=None, last_counter_price=1050_00), prod) == 1050_00
    assert _price_ceiling(SimpleNamespace(last_shown_price=None, last_counter_price=None), prod) == 1200_00
    assert _price_ceiling(None, prod) == 1200_00


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
async def test_persist_bundle_lines_ratchets_down_only(db_session):  # noqa: F811
    """A bundle counter's per-product split is written to each member's CP, and a later
    bundle quote can only lower it — never raise it (the bundle can't be re-quoted higher)."""
    from app.bot.conversation import _persist_bundle_lines, _get_or_create_conv_product

    seller, led, jho, conv = await _seed_two_products(db_session)
    led_cp = await _get_or_create_conv_product(conv.id, led.id, db_session)
    jho_cp = await _get_or_create_conv_product(conv.id, jho.id, db_session)

    # First bundle quote: led ₹1900, jho ₹950 → persisted to each CP.
    await _persist_bundle_lines(conv, [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 1},
        {"product_id": str(jho.id), "unit_price_paise": 950_00, "quantity": 1},
    ], db_session)
    await db_session.flush()
    assert led_cp.last_shown_price == 1900_00 and led_cp.last_counter_price == 1900_00
    assert jho_cp.last_shown_price == 950_00

    # A HIGHER re-quote must be ignored (ratchet down-only) — bundle can't rise.
    await _persist_bundle_lines(conv, [
        {"product_id": str(led.id), "unit_price_paise": 1950_00, "quantity": 1},
        {"product_id": str(jho.id), "unit_price_paise": 980_00, "quantity": 1},
    ], db_session)
    await db_session.flush()
    assert led_cp.last_shown_price == 1900_00  # unchanged
    assert jho_cp.last_shown_price == 950_00   # unchanged

    # A LOWER re-quote wins (further discount).
    await _persist_bundle_lines(conv, [
        {"product_id": str(led.id), "unit_price_paise": 1850_00, "quantity": 1},
    ], db_session)
    await db_session.flush()
    assert led_cp.last_shown_price == 1850_00 and led_cp.last_counter_price == 1850_00


@pytest.mark.asyncio
async def test_build_deal_order_consolidates_prior_unpaid_cart(db_session):  # noqa: F811
    """Finalizing a 2nd product while a 1st is finalized-but-unpaid must produce ONE
    combined order covering BOTH — not a separate order per product."""
    from app.bot.conversation import _build_deal_order, _get_or_create_conv_product
    from app.models.order import Order, OrderItem
    from sqlalchemy import select

    seller, led, jho, conv = await _seed_two_products(db_session)

    # First: finalize 4 LED clocks (its own awaiting_payment order).
    led_cp = await _get_or_create_conv_product(conv.id, led.id, db_session)
    led_cp.agreed_price = 1900_00
    led_cp.quantity = 4
    await _build_deal_order(conv, seller, led_cp, [
        {"product_id": str(led.id), "unit_price_paise": 1900_00, "quantity": 4},
    ], db_session)

    # Then: finalize 1 jhoomar — focus is now jhoomar, deal_lines only has jhoomar.
    jho_cp = await _get_or_create_conv_product(conv.id, jho.id, db_session)
    conv.product_id = jho.id
    order = await _build_deal_order(conv, seller, jho_cp, [
        {"product_id": str(jho.id), "unit_price_paise": 999_00, "quantity": 1},
    ], db_session)

    # ONE order, covering BOTH products (4×1900 + 1×999).
    orders = (await db_session.execute(
        select(Order).where(Order.conversation_id == conv.id, Order.status == "awaiting_payment")
    )).scalars().all()
    assert len(orders) == 1
    assert order.amount == 4 * 1900_00 + 999_00  # 7600_00 + 999_00
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert {oi.unit_price: oi.quantity for oi in items} == {1900_00: 4, 999_00: 1}


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
