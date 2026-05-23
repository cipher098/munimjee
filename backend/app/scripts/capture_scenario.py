"""Export a real conversation from the DB as a scenario YAML stub.

Usage:
    docker compose run --rm api python -m app.scripts.capture_scenario <conversation_id>

Writes to backend/tests/scenarios/captured_<short>.yaml. The stub has:
  - seller persona + policies copied verbatim
  - every product the conversation referenced (current product + any other
    inquiry products tracked via ConversationProduct)
  - one `turns` entry per customer message in the conversation, with the
    bot's reply stripped (it will be regenerated during the test) and an
    empty `expect` block for the human to fill in based on what the bot
    actually did

Workflow:
  1. Find an interesting conversation:
       SELECT id, LENGTH(messages::text) FROM conversations
       ORDER BY updated_at DESC LIMIT 10;
  2. Run this script with that conversation id.
  3. Edit the YAML stub: fill in the `expect:` blocks based on the worker
     log lines or production behaviour.
  4. Record cassettes: VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... just test-scenarios
  5. Commit the YAML + cassettes.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid as uuid_lib
from typing import Any

import yaml
from sqlalchemy import select

from app.database import worker_session
from app.models.conversation import Conversation
from app.models.conversation_product import ConversationProduct
from app.models.product import Product
from app.models.seller import Seller


SCENARIOS_DIR = pathlib.Path(__file__).resolve().parents[2] / "tests" / "scenarios"


async def _load(conversation_id: str) -> tuple[Conversation, Seller, list[Product]]:
    cid = uuid_lib.UUID(conversation_id)
    async with worker_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == cid))
        conv = result.scalar_one_or_none()
        if conv is None:
            raise SystemExit(f"No conversation found with id={conversation_id}")

        seller = (await session.execute(select(Seller).where(Seller.id == conv.seller_id))).scalar_one()

        # Pull current product + any others the conversation touched via ConversationProduct.
        cp_rows = (await session.execute(
            select(ConversationProduct.product_id).where(ConversationProduct.conversation_id == cid)
        )).scalars().all()
        product_ids = {pid for pid in cp_rows}
        if conv.product_id:
            product_ids.add(conv.product_id)
        if not product_ids:
            products = []
        else:
            products = (await session.execute(
                select(Product).where(Product.id.in_(product_ids))
            )).scalars().all()

    return conv, seller, products


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")[:40]


def _to_scenario_dict(conv: Conversation, seller: Seller, products: list[Product]) -> dict[str, Any]:
    customer_messages = [
        m for m in (conv.messages or []) if m.get("role") == "customer" and (m.get("content") or "").strip()
    ]
    turns = [
        {"customer": m["content"], "expect": {}}
        for m in customer_messages
    ]

    return {
        "id": f"captured_{str(conv.id)[:8]}",
        "description": (
            f"Captured from conversation {conv.id}.\n"
            f"FILL IN THE expect: BLOCKS BEFORE RECORDING CASSETTES.\n"
            f"See worker logs for the original bot behaviour per turn."
        ),
        "seller": {
            "persona": seller.persona or {},
            "policies": seller.policies or {},
        },
        "products": [
            {
                "slug": _slugify(p.name) or f"product_{i}",
                "name": p.name,
                "listed_price_paise": p.listed_price,
                "floor_price_paise": p.floor_price,
                "description": p.description,
                "warranty_months": p.warranty_months,
                "stock_quantity": p.stock_quantity,
            }
            for i, p in enumerate(products)
        ],
        "turns": turns,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.scripts.capture_scenario <conversation_id>", file=sys.stderr)
        raise SystemExit(2)

    conversation_id = sys.argv[1]
    conv, seller, products = asyncio.run(_load(conversation_id))
    scenario = _to_scenario_dict(conv, seller, products)

    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCENARIOS_DIR / f"{scenario['id']}.yaml"
    out_path.write_text(yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  seller={seller.id} products={len(products)} customer_turns={len(scenario['turns'])}")
    print(f"\nNext steps:")
    print(f"  1. Edit {out_path} to fill in `expect:` blocks per turn")
    print(f"  2. VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... just test-scenarios")
    print(f"  3. git add tests/scenarios/{out_path.name} tests/cassettes/scenarios/{scenario['id']}/")


if __name__ == "__main__":
    main()
