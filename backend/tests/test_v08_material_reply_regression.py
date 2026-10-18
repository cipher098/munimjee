"""Frozen M01–M06: real reply composition, synthetic raw observation boundary.

Only the reviewed read-only adapter is reused; expected replies, fixture rows,
the real parser/context/decision invocation and uncertainty oracle are owned here.
No SQL, persistence, model/provider request or outbound send is exercised.
"""
from tests.safety import install_test_safety

install_test_safety()

from datetime import datetime, timezone
import json
import re
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.config import settings
from app.services.whatsapp_context import inbound_context, reel_reply_decision
from tests.test_v08_semantics_acceptance import ReadOnlyProjection


BUSINESS = UUID(int=1001)
PRODUCT = UUID(int=2001)
CONTACT = UUID(int=3001)
REEL = "https://www.instagram.com/reel/SemanticsOnly/"
OBSERVED = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
HANDOFF = "Our team will confirm the current options, price and availability for this product."
EXPECTED_MIXED_REPLY = (
    "Current catalogue: Semantic kurta.\n"
    "• Color: Indigo; Size: M — ₹0.00; recorded available: 2.\n"
    "• Color: Indigo; Size: L — ₹145.67; recorded out of stock.\n"
    "• Color: Indigo; Size: XL — ₹167.89; availability untracked; please confirm with our team.\n"
    "Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.")


def raw_observations():
    return [dict(id=PRODUCT, name="Semantic kurta", revision=3, sku_id=UUID(int=4001 + index),
                 options={"Size": size, "Color": "Indigo"}, price_minor=price,
                 currency="INR", stock_available=stock, observed_at=OBSERVED)
            for index, (size, price, stock) in enumerate([
                ("M", 12345, 2), ("L", 14567, 0), ("XL", 16789, None)])]


@pytest.fixture(autouse=True)
def controlled_rollout(monkeypatch):
    monkeypatch.setattr(settings, "V1_SKU_FACT_REPLIES_ENABLED", True)


async def compose(question, rows, record_property):
    projection = ReadOnlyProjection(rows)
    text = REEL + " " + question
    event = {"id": "synthetic-material-inbound", "type": "text", "timestamp": str(int(OBSERVED.timestamp()))}
    parsed = await inbound_context(projection, SimpleNamespace(seller_id=BUSINESS),
                                   SimpleNamespace(id=CONTACT), event, text)
    assert parsed["reel_context"] == {"source": "message_link", "shared_at": OBSERVED.isoformat(),
        "references": [{"shortcode": "SemanticsOnly", "url": REEL,
                        "products": [{"id": str(PRODUCT), "name": "Semantic kurta"}], "status": "matched"}]}
    decision = await reel_reply_decision(projection, BUSINESS, parsed["reel_context"], text)
    assert projection.calls == ["exact_reel_products", "inbound_context_product_names",
                                "exact_reel_products", "is_activated", "read_facts"]
    assert decision.review_reason is None
    record_property("question", question)
    record_property("reply", decision.reply if decision.reply is not None else "<withheld>")
    record_property("raw_projection_calls", json.dumps(projection.calls))
    return decision.reply


def assert_material_uncertainty(reply):
    # A future truthful explicit-unknown answer is allowed; generic preferred-
    # option confirmation alone cannot answer a missing material question.
    if reply == HANDOFF:
        return
    relevant = [line for line in (reply or "").splitlines()
                if re.search(r"\b(material|materials|fabric|composition)\b", line, re.I)]
    assert any(re.search(r"unknown|unrecorded|not (?:recorded|listed|confirmed|available)|need[s]? confirmation|please confirm|confirm with", line, re.I)
               for line in relevant), "Missing material needs specific uncertainty or human handoff; observed: " + repr(reply)


MATERIAL_CASES = [
    ("M01-plural", "What materials are available?"),
    ("M02-price-material", "What price and material is this?"),
    ("M03-sizes-stock-materials", "What sizes stock and materials are available?"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,question", MATERIAL_CASES, ids=[row[0] for row in MATERIAL_CASES])
async def test_missing_material_requires_handoff_or_specific_uncertainty(case_id, question, record_property):
    record_property("scenario_id", case_id)
    reply = await compose(question, raw_observations(), record_property)
    assert_material_uncertainty(reply)


@pytest.mark.asyncio
async def test_m04_supported_mixed_request_preserves_zero_price_zero_and_unknown_stock(record_property):
    record_property("scenario_id", "M04-supported-mixed-zero-price")
    rows = raw_observations()
    rows[0]["price_minor"] = 0  # Approved zero is distinct from absent/null price.
    reply = await compose("What prices sizes and stock are available?", rows, record_property)
    assert reply == EXPECTED_MIXED_REPLY


@pytest.mark.asyncio
async def test_m05_empty_material_observation_still_withholds_authority(record_property):
    record_property("scenario_id", "M05-empty-material-observation")
    reply = await compose("What material is this?", [], record_property)
    assert reply is None, "Missing SKU authority must withhold before any material handoff response"


@pytest.mark.asyncio
async def test_m06_null_required_price_still_withholds_mixed_material_reply(record_property):
    record_property("scenario_id", "M06-null-price-material")
    rows = raw_observations()
    rows[0]["price_minor"] = None
    reply = await compose("What price and material is this?", rows, record_property)
    assert reply is None, "Invalid public facts cannot acquire authority through unsupported-intent handling"
