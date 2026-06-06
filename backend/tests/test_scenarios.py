"""Scenario-driven regression tests.

Each YAML file in `tests/scenarios/` describes:
  - the seller, products, optional tags to seed the DB with
  - a list of customer turns and the expected bot behaviour per turn

The runner replays each turn through the real `advance_conversation` entry
point (the same one celery uses) with the Anthropic API recorded via VCR
and Instagram/WhatsApp/Sarvam mocked. After each turn it reads the
`LAST_TURN` contextvar to pull out action/state/reply/intent/interventions
and asserts against the YAML `expect` block.

Skip behaviour: a scenario whose VCR cassettes don't exist yet gets
skipped with a clear "record with VCR_RECORD=1" message instead of
hard-failing. Drop in a scenario, record once, commit cassettes, done.
"""
from __future__ import annotations

import pathlib
import uuid
from typing import Any

import pytest
import yaml

from app.bot import test_hooks
from app.bot.conversation import advance_conversation
from app.models.conversation import Conversation
from app.models.product import Product
from app.models.seller import Seller

# Re-export fixtures from conftest_db so pytest can find them.
from tests.conftest_db import db_session, patched_clients, scenario_cassette  # noqa: F401

SCENARIOS_DIR = pathlib.Path(__file__).parent / "scenarios"
CASSETTES_DIR = pathlib.Path(__file__).parent / "cassettes" / "scenarios"


def _load_scenarios() -> list[dict]:
    files = sorted(SCENARIOS_DIR.glob("*.yaml"))
    out = []
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["_path"] = str(path)
        out.append(data)
    return out


def _scenario_id(scenario: dict) -> str:
    return scenario.get("id") or pathlib.Path(scenario["_path"]).stem


SCENARIOS = _load_scenarios()


@pytest.fixture
async def seeded(db_session, scenario: dict):
    """Seed Seller + Product rows for a scenario and create a fresh Conversation."""
    seller = Seller(
        instagram_id=f"test-ig-{uuid.uuid4().hex[:8]}",
        instagram_token="fake-token",
        instagram_page_id="fake-page-id",
        fb_page_id="fake-fb-page",
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        persona=scenario["seller"].get("persona"),
        policies=scenario["seller"].get("policies"),
    )
    db_session.add(seller)
    await db_session.flush()

    products: dict[str, Product] = {}
    first_product: Product | None = None
    for pdef in scenario.get("products") or []:
        product = Product(
            seller_id=seller.id,
            name=pdef["name"],
            description=pdef.get("description"),
            listed_price=pdef["listed_price_paise"],
            floor_price=pdef["floor_price_paise"],
            warranty_months=pdef.get("warranty_months"),
            stock_quantity=pdef.get("stock_quantity"),
            active=True,
        )
        db_session.add(product)
        await db_session.flush()
        products[pdef["slug"]] = product
        if first_product is None:
            first_product = product

    conversation = Conversation(
        seller_id=seller.id,
        customer_instagram_id=f"test-customer-{uuid.uuid4().hex[:8]}",
        customer_name="TestCustomer",
        customer_gender="male",  # avoid the gender-inference LLM call
        product_id=first_product.id if first_product else None,
        messages=[],
    )
    db_session.add(conversation)
    await db_session.flush()

    yield {"seller": seller, "conversation": conversation, "products": products}


def _assert_turn(expect: dict, record: dict, scenario_id: str, turn_idx: int) -> None:
    """Apply each optional key from `expect` to the actual `record` dict."""
    msg_prefix = f"[{scenario_id} turn {turn_idx}]"

    if "action" in expect:
        assert record.get("action") == expect["action"], (
            f"{msg_prefix} action: expected {expect['action']!r}, "
            f"got {record.get('action')!r} (decision={record.get('decision')})"
        )

    if "new_state" in expect:
        assert record.get("new_state") == expect["new_state"], (
            f"{msg_prefix} new_state: expected {expect['new_state']!r}, "
            f"got {record.get('new_state')!r}"
        )

    if "price_paise" in expect:
        assert record.get("price") == expect["price_paise"], (
            f"{msg_prefix} price (paise): expected {expect['price_paise']}, "
            f"got {record.get('price')}"
        )

    reply = (record.get("reply") or "").lower()
    for required in expect.get("reply_must_contain", []) or []:
        assert required.lower() in reply, (
            f"{msg_prefix} reply missing required substring {required!r}: reply={record.get('reply')!r}"
        )
    for forbidden in expect.get("reply_must_not_contain", []) or []:
        assert forbidden.lower() not in reply, (
            f"{msg_prefix} reply contains forbidden substring {forbidden!r}: reply={record.get('reply')!r}"
        )

    if "fired_interventions" in expect:
        actual = set(record.get("fired_interventions") or [])
        expected = set(expect["fired_interventions"])
        assert expected.issubset(actual), (
            f"{msg_prefix} expected interventions {expected - actual} did not fire (fired={sorted(actual)})"
        )

    if "fired_interventions_any_of" in expect:
        actual = set(record.get("fired_interventions") or [])
        any_of = set(expect["fired_interventions_any_of"])
        assert actual & any_of, (
            f"{msg_prefix} expected at least one of {any_of} to fire (fired={sorted(actual)})"
        )

    if "intent_classification" in expect:
        ic = record.get("intent_classification") or {}
        for key, val in (expect["intent_classification"] or {}).items():
            assert ic.get(key) == val, (
                f"{msg_prefix} intent_classification.{key}: expected {val!r}, got {ic.get(key)!r}"
            )


def _cassettes_exist(scenario_id: str, turn_count: int) -> bool:
    scenario_dir = CASSETTES_DIR / scenario_id
    if not scenario_dir.exists():
        return False
    return all((scenario_dir / f"turn_{i+1}.yaml").exists() for i in range(turn_count))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
@pytest.mark.asyncio
async def test_scenario(
    scenario: dict,
    db_session,
    patched_clients,
    scenario_cassette,
    seeded,
):
    scenario_id = scenario["id"]
    turns = scenario.get("turns") or []
    if not _cassettes_exist(scenario_id, len(turns)):
        import os
        if os.environ.get("VCR_RECORD") != "1":
            pytest.skip(
                f"No cassettes for scenario {scenario_id!r}. Record with "
                f"VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... pytest tests/test_scenarios.py"
            )

    conversation: Conversation = seeded["conversation"]
    seller: Seller = seeded["seller"]

    for idx, turn in enumerate(turns, start=1):
        # Seed the contextvar so test_hooks.record() captures this turn.
        record: dict[str, Any] = {}
        token = test_hooks.LAST_TURN.set(record)
        try:
            with scenario_cassette(scenario_id, turn=idx):
                await advance_conversation(
                    conversation=conversation,
                    seller=seller,
                    customer_message=turn["customer"],
                    db=db_session,
                    send_reply=True,
                )
            await db_session.commit()
        finally:
            test_hooks.LAST_TURN.reset(token)

        expect = turn.get("expect") or {}
        _assert_turn(expect, record, scenario_id, idx)
