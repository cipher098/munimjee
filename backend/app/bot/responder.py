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
    })

    new_state, extra = _derive_state_from_decision(decision, conversation, product)

    # Step 2: Sarvam generates the actual message text
    try:
        reply = await sarvam.generate_reply({
            "decision": decision,
            "persona": seller.persona or {},
            "product_name": product.name if product else "the product",
            "message_history": (conversation.messages or [])[-10:],
        })
    except Exception as exc:
        logger.warning("Sarvam failed (%s), falling back to Claude for reply", exc)
        reply = await claude.generate_reply({
            "decision": decision,
            "persona": seller.persona or {},
            "product_name": product.name if product else "the product",
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
    extra: dict[str, Any] = {}

    if action == "accept":
        price = decision.get("price")
        extra["agreed_price"] = price
        return "awaiting_payment", extra

    if action == "counter":
        extra["negotiation_round"] = conversation.negotiation_round + 1
        return "negotiating", extra

    if action == "hold_firm":
        extra["negotiation_round"] = conversation.negotiation_round + 1
        return "negotiating", extra

    if action == "request_payment":
        return "awaiting_payment", extra

    if action == "escalate":
        return "manual_review", extra

    if action == "show_product" and product:
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
    client = InstagramClient(seller.instagram_token)
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
