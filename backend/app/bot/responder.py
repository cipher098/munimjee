"""
Hybrid AI response generation.
  Step 1 — Claude decides WHAT to do (action + price).
  Step 2 — Sarvam generates reply in seller's Hinglish style.
  Fallback — Claude generates reply if Sarvam fails.
"""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.product import Product
from app.models.seller import Seller

logger = logging.getLogger(__name__)

DEFAULT_PERSONA = {
    "greeting_style": "Haan ji, kya chahiye?",
    "negotiation_firmness": "medium",
    "closing_phrases": ["Done ho gaya", "Pakka"],
    "common_expressions": ["bhai", "yaar", "theek hai"],
    "hindi_english_ratio": "60% Hindi 40% English",
    "emoji_usage": "light",
    "response_length": "short",
    "tone": "casual",
    "sample_responses": {
        "greeting": "Haan ji! Kya chahiye aapko? 😊",
        "price_rejection": "Bhai itna kam nahi hoga, last price hai ye",
        "deal_accepted": "Done! Payment kar do jaldi",
        "payment_request": "Bhai payment kar do, UPI hai — details bhej raha hoon",
        "dispatched": "Dispatch ho gaya aapka order, tracking bhejta hoon"
    }
}


async def generate_bot_reply(
    conversation: Conversation,
    customer_message: str,
    seller: Seller,
    db: AsyncSession,
) -> tuple[str, str | None, dict[str, Any]]:
    """
    Returns (reply_text, new_state, extra_dict).
    extra_dict may contain: agreed_price, negotiation_round, product_id.
    """
    product: Product | None = None
    if conversation.product_id:
        result = await db.execute(select(Product).where(Product.id == conversation.product_id))
        product = result.scalar_one_or_none()

    # At greeting state, load all seller products so Claude can identify what the customer wants
    products_list: list[dict] = []
    if not product:
        result = await db.execute(
            select(Product).where(Product.seller_id == seller.id, Product.active == True)
        )
        all_products = result.scalars().all()
        products_list = [
            {"id": str(p.id), "name": p.name, "listed_price_paise": p.listed_price}
            for p in all_products
        ]

    from app.integrations.claude import ClaudeClient
    from app.integrations.sarvam import SarvamClient

    claude = ClaudeClient()
    sarvam = SarvamClient()

    # Step 1: Claude decides action
    decision = await claude.decide({
        "state": conversation.state,
        "customer_message": customer_message,
        "negotiation_round": conversation.negotiation_round,
        "listed_price": product.listed_price if product else None,
        "floor_price": product.floor_price if product else None,   # never forwarded to customer
        "message_history": (conversation.messages or [])[-10:],
        "available_products": products_list,
    })

    new_state, extra = _derive_state_from_decision(decision, conversation, product)

    persona = seller.persona or DEFAULT_PERSONA

    # Step 2: Sarvam generates the actual message text
    try:
        reply = await sarvam.generate_reply({
            "decision": decision,
            "persona": persona,
            "product_name": product.name if product else "the product",
            "listed_price_rupees": product.listed_price // 100 if product else None,
            "bulk_quantity": decision.get("bulk_quantity"),
            "message_history": (conversation.messages or [])[-10:],
        })
    except Exception as exc:
        logger.warning("Sarvam failed (%s), falling back to Claude for reply", exc)
        reply = await claude.generate_reply({
            "decision": decision,
            "persona": persona,
            "product_name": product.name if product else "the product",
            "listed_price_rupees": product.listed_price // 100 if product else None,
            "bulk_quantity": decision.get("bulk_quantity"),
            "message_history": (conversation.messages or [])[-10:],
        })

    return reply, new_state, extra


def _derive_state_from_decision(
    decision: dict,
    conversation: Conversation,
    product: Product | None,
) -> tuple[str | None, dict]:
    """Maps Claude's action to a state transition and extra data."""
    action = decision.get("action", "")
    floor_price = product.floor_price if product else None
    extra: dict[str, Any] = {}

    if action == "accept":
        price = decision.get("price")
        # Hard clamp — never accept below floor price
        if floor_price and price and price < floor_price:
            logger.warning(
                "Claude tried to accept at %d below floor %d — overriding to hold_firm",
                price, floor_price,
            )
            action = "hold_firm"
            decision["action"] = "hold_firm"
        else:
            extra["agreed_price"] = price
            return "awaiting_payment", extra

    if action == "counter":
        price = decision.get("price")
        # Hard clamp — counter price can never go below floor
        if floor_price and price and price < floor_price:
            logger.warning(
                "Claude countered at %d below floor %d — clamping to floor",
                price, floor_price,
            )
            decision["price"] = floor_price
        extra["negotiation_round"] = conversation.negotiation_round + 1
        return "negotiating", extra

    if action == "hold_firm":
        extra["negotiation_round"] = conversation.negotiation_round + 1
        return "negotiating", extra

    if action == "bulk_discount":
        price = decision.get("price")
        if floor_price and price and price < floor_price:
            decision["price"] = floor_price
        extra["agreed_price"] = decision.get("price")
        extra["bulk_quantity"] = decision.get("bulk_quantity")
        return "awaiting_payment", extra

    if action == "request_payment":
        return "awaiting_payment", extra

    if action == "escalate":
        return "manual_review", extra

    if action == "show_product":
        product_id = decision.get("product_id")
        if product_id:
            extra["product_id"] = product_id
        elif product:
            extra["product_id"] = product.id
        return "product_inquiry", extra

    return None, extra


async def send_manual_verification_ping(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
) -> None:
    """Level 5: send WhatsApp ping to seller for manual payment confirmation."""
    from app.integrations.instagram import InstagramClient

    # Notify customer we're verifying
    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    await client.send_message(
        conversation.customer_instagram_id,
        "Ek second — payment verify kar rahe hain 🔍",
    )

    if not seller.whatsapp_number:
        logger.warning(
            "Seller %s has no WhatsApp number — cannot send manual verification ping",
            seller.id,
        )
        conversation.state = "manual_review"
        await db.flush()
        return

    amount_rupees = (conversation.agreed_price or 0) // 100

    ping_text = (
        f"💰 Payment screenshot received!\n"
        f"Amount: ₹{amount_rupees}\n"
        f"Customer: {conversation.customer_instagram_id}\n"
        f"Screenshot: {image_url}\n\n"
        f"Reply *1* to confirm, *0* to reject."
    )

    try:
        from app.integrations.whatsapp import WhatsAppClient
        wa = WhatsAppClient()
        await wa.send_message(seller.whatsapp_number, ping_text)
    except Exception as exc:
        logger.error("Failed to send WhatsApp ping to seller %s: %s", seller.id, exc)

    conversation.state = "manual_review"
    await db.flush()
