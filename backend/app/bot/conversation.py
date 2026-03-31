"""
Conversation state machine.

States:
  greeting → product_inquiry → negotiating → awaiting_payment
  → verifying → payment_confirmed | failed | manual_review
  → dispatched_notified
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.seller import Seller

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"payment_confirmed", "failed", "dispatched_notified"}


def _append_message(conversation: Conversation, role: str, content: str) -> None:
    messages = list(conversation.messages or [])
    messages.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    conversation.messages = messages


async def advance_conversation(
    conversation: Conversation,
    seller: Seller,
    customer_message: str,
    db: AsyncSession,
) -> None:
    """Main entry point: processes a customer text message and sends a bot reply."""
    if conversation.state in TERMINAL_STATES:
        return

    _append_message(conversation, "customer", customer_message)

    from app.bot.responder import generate_bot_reply
    from app.integrations.instagram import InstagramClient

    reply, new_state, extra = await generate_bot_reply(conversation, customer_message, seller, db)

    if new_state:
        conversation.state = new_state

    if extra.get("agreed_price"):
        conversation.agreed_price = extra["agreed_price"]

    if extra.get("negotiation_round") is not None:
        conversation.negotiation_round = extra["negotiation_round"]

    if extra.get("product_id"):
        conversation.product_id = extra["product_id"]

    _append_message(conversation, "bot", reply)
    await db.flush()

    # Send via Instagram
    client = InstagramClient(seller.instagram_token)
    await client.send_message(conversation.customer_instagram_id, reply)


async def handle_payment_screenshot(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
) -> None:
    """Handles an image attachment when the conversation is in awaiting_payment."""
    conversation.state = "verifying"
    _append_message(conversation, "customer", f"[screenshot: {image_url}]")
    await db.flush()

    # Phase 2 will wire in OCR + UTR verification here.
    # For Phase 1: fall back to manual review (Level 5 — owner WhatsApp ping).
    from app.bot.responder import send_manual_verification_ping
    await send_manual_verification_ping(conversation, seller, image_url, db)
