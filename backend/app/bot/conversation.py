"""
Conversation state machine.

States:
  greeting → product_inquiry → negotiating → awaiting_payment
  → verifying → payment_confirmed | failed | manual_review
  → dispatched_notified
"""
import base64
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.product import Product
from app.models.seller import Seller

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"payment_confirmed", "failed", "dispatched_notified"}


def _detect_media_type(data: bytes) -> str:
    """Detect image media type from magic bytes — don't trust Content-Type headers."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"  # fallback


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

    if extra.get("last_counter_price") is not None:
        conversation.last_counter_price = extra["last_counter_price"]

    if extra.get("product_id"):
        conversation.product_id = extra["product_id"]

    _append_message(conversation, "bot", reply)
    await db.flush()

    # Send via Instagram
    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    try:
        await client.send_message(conversation.customer_instagram_id, reply)
    except Exception as exc:
        logger.error(
            "Failed to send Instagram reply in conversation %s: %s — reply saved to DB",
            conversation.id, exc,
        )


async def handle_product_image(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
) -> None:
    """Customer sent an image — use Claude Vision to identify the product and start negotiation."""
    from app.integrations.claude import ClaudeClient
    from app.integrations.instagram import InstagramClient
    from app.bot.responder import generate_bot_reply, DEFAULT_PERSONA

    _append_message(conversation, "customer", f"[product image: {image_url}]")
    await db.flush()

    # Fetch seller's active products
    result = await db.execute(
        select(Product).where(Product.seller_id == seller.id, Product.active == True)
    )
    products = result.scalars().all()

    if not products:
        reply = "Abhi koi product available nahi hai. Thodi der mein try karein 🙏"
        _append_message(conversation, "bot", reply)
        await db.flush()
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        try:
            await client.send_message(conversation.customer_instagram_id, reply)
        except Exception as exc:
            logger.error("Failed to send reply in conversation %s: %s", conversation.id, exc)
        return

    products_for_vision = [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description or "",
            "listed_price_paise": p.listed_price,
        }
        for p in products
    ]

    claude = ClaudeClient()

    # Download image — Instagram blocks Claude from fetching URLs directly
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            img_response = await http.get(image_url)
            img_response.raise_for_status()
        image_b64 = base64.b64encode(img_response.content).decode()
        media_type = _detect_media_type(img_response.content)
    except Exception as exc:
        logger.error("Failed to download product image %s: %s", image_url, exc)
        reply = "Image download nahi hua. Dobara bhejein please 🙏"
        _append_message(conversation, "bot", reply)
        await db.flush()
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        try:
            await client.send_message(conversation.customer_instagram_id, reply)
        except Exception:
            pass
        return

    # Stage 1 — Vision: describe what the customer is holding/showing
    description = await claude.describe_product_image(image_b64, media_type)

    # Stage 2 — Text: match description against catalog
    match = await claude.match_product_by_description(description, products_for_vision)

    product_id = match.get("product_id")
    confidence = match.get("confidence", "low")

    matched = next((p for p in products if str(p.id) == product_id), None) if product_id else None
    logger.info(
        "\n"
        "┌─────────────────────────────────────────\n"
        "│ IMAGE MATCH\n"
        "│ DESCRIPTION : %s\n"
        "│ MATCHED     : %s  (confidence: %s)\n"
        "│ LISTED      : %s  |  FLOOR: %s\n"
        "│ REASON      : %s\n"
        "└─────────────────────────────────────────",
        description,
        matched.name if matched else "NO MATCH",
        confidence,
        f"₹{matched.listed_price // 100}" if matched else "—",
        f"₹{matched.floor_price // 100}" if matched else "—",
        match.get("reason", ""),
    )

    if not product_id or confidence == "low":
        # Could not identify — ask customer to clarify
        reply = "Kaunsa product chahiye aapko? Thoda aur clearly batayein ya product ka naam likhein 😊"
        _append_message(conversation, "bot", reply)
        await db.flush()
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        try:
            await client.send_message(conversation.customer_instagram_id, reply)
        except Exception as exc:
            logger.error("Failed to send reply in conversation %s: %s", conversation.id, exc)
        return

    # Product identified — set it on conversation and generate opening price reply
    conversation.product_id = product_id
    conversation.state = "product_inquiry"

    # Build a synthetic customer message for the responder
    matched_product = next((p for p in products if str(p.id) == product_id), None)
    synthetic_message = f"[Customer sent image of: {matched_product.name if matched_product else 'product'}]"

    reply, new_state, extra = await generate_bot_reply(conversation, synthetic_message, seller, db)

    if new_state:
        conversation.state = new_state
    if extra.get("agreed_price"):
        conversation.agreed_price = extra["agreed_price"]
    if extra.get("negotiation_round") is not None:
        conversation.negotiation_round = extra["negotiation_round"]

    _append_message(conversation, "bot", reply)
    await db.flush()

    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    try:
        await client.send_message(conversation.customer_instagram_id, reply)
    except Exception as exc:
        logger.error("Failed to send reply in conversation %s: %s", conversation.id, exc)


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
