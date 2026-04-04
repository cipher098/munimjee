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
from app.models.conversation_product import ConversationProduct
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


async def _get_or_create_conv_product(
    conversation_id,
    product_id,
    db: AsyncSession,
) -> ConversationProduct:
    """Return the ConversationProduct row for this (conversation, product) pair, creating it if absent."""
    result = await db.execute(
        select(ConversationProduct).where(
            ConversationProduct.conversation_id == conversation_id,
            ConversationProduct.product_id == product_id,
        )
    )
    conv_product = result.scalar_one_or_none()
    if conv_product is None:
        conv_product = ConversationProduct(
            conversation_id=conversation_id,
            product_id=product_id,
            negotiation_round=0,
            last_counter_price=None,
            agreed_price=None,
        )
        db.add(conv_product)
        await db.flush()
    return conv_product


async def _send_product_image_if_new(
    conversation: Conversation,
    seller: Seller,
    product,
    db: AsyncSession,
) -> None:
    """Send product photo to customer when a product is first identified in this conversation.
    Only fires if photo_url is set and this is the first time this product has been shown
    (i.e. conv_product has no prior negotiation — negotiation_round == 0 and no last_counter_price).
    """
    if not product or not product.photo_url:
        return

    from app.config import settings
    from app.integrations.instagram import InstagramClient

    photo_url = product.photo_url
    # Meta requires a fully-qualified public URL — prefix relative /uploads/ paths
    if photo_url.startswith("/") and settings.PUBLIC_BASE_URL:
        photo_url = settings.PUBLIC_BASE_URL.rstrip("/") + photo_url
    elif photo_url.startswith("/"):
        logger.warning(
            "Cannot send product image for %r — PUBLIC_BASE_URL not set in config", product.name
        )
        return

    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    try:
        await client.send_image(conversation.customer_instagram_id, photo_url)
        logger.info("Sent product image for %r to %s", product.name, conversation.customer_instagram_id)
    except Exception as exc:
        logger.warning("Could not send product image for %r: %s", product.name, exc)


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

    # Look up the per-product state before calling the responder so it can use it
    conv_product: ConversationProduct | None = None
    if conversation.product_id:
        conv_product = await _get_or_create_conv_product(
            conversation.id, conversation.product_id, db
        )

    reply, new_state, extra = await generate_bot_reply(
        conversation, customer_message, seller, db, conv_product=conv_product
    )

    if new_state:
        conversation.state = new_state

    if extra.get("agreed_price"):
        conversation.agreed_price = extra["agreed_price"]
        # Lock last_counter_price to agreed price — if customer renegotiates, can't go lower
        conversation.last_counter_price = extra["agreed_price"]
        if conv_product is not None:
            conv_product.agreed_price = extra["agreed_price"]
            conv_product.last_counter_price = extra["agreed_price"]

    if extra.get("negotiation_round") is not None:
        conversation.negotiation_round = extra["negotiation_round"]
        if conv_product is not None:
            conv_product.negotiation_round = extra["negotiation_round"]

    if extra.get("last_counter_price") is not None:
        conversation.last_counter_price = extra["last_counter_price"]
        if conv_product is not None:
            conv_product.last_counter_price = extra["last_counter_price"]

    # If product was just identified via text (show_product action), send its image first
    new_product_id = extra.get("product_id")
    if new_product_id and new_product_id != str(conversation.product_id):
        conversation.product_id = new_product_id
        # Load product to get photo_url
        from sqlalchemy import select as sa_select
        from app.models.product import Product as ProductModel
        result = await db.execute(sa_select(ProductModel).where(ProductModel.id == new_product_id))
        new_product = result.scalar_one_or_none()
        await _send_product_image_if_new(conversation, seller, new_product, db)
    elif new_product_id:
        conversation.product_id = new_product_id

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

    # Product identified — set it on conversation and restore per-product price state
    conversation.product_id = product_id

    # Get or create the ConversationProduct row for this product
    conv_product = await _get_or_create_conv_product(conversation.id, product_id, db)

    # Restore conversation state from per-product state (source of truth)
    if conv_product.agreed_price:
        conversation.state = "awaiting_payment"
    elif conv_product.last_counter_price:
        conversation.state = "negotiating"
    else:
        conversation.state = "product_inquiry"

    conversation.negotiation_round = conv_product.negotiation_round
    conversation.last_counter_price = conv_product.last_counter_price

    # If deal was already agreed for this product, skip generate_bot_reply —
    # just send a payment reminder. Calling the responder with a product image
    # message confuses Claude into restarting negotiation.
    matched_product = next((p for p in products if str(p.id) == product_id), None)
    if conv_product.agreed_price:
        agreed_rupees = conv_product.agreed_price // 100
        reply = (
            f"Bhai deal toh already ho gayi thi — ₹{agreed_rupees} mein! "
            f"Payment kar do, pack karke bhej deta hoon 🚀"
        )
        _append_message(conversation, "bot", reply)
        await db.flush()
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        try:
            await client.send_message(conversation.customer_instagram_id, reply)
        except Exception as exc:
            logger.error("Failed to send reply in conversation %s: %s", conversation.id, exc)
        return

    # Send product image back to customer so they can confirm it's the right product —
    # only on fresh inquiry (no prior counter), not when re-sharing during negotiation.
    is_fresh_inquiry = not conv_product.last_counter_price and not conv_product.agreed_price
    if is_fresh_inquiry:
        await _send_product_image_if_new(conversation, seller, matched_product, db)

    # Build a synthetic customer message for the responder.
    # During active negotiation, signal that it's a re-share, not a fresh inquiry —
    # so Claude doesn't restart the pitch at listed price.
    product_name = matched_product.name if matched_product else "product"
    if conversation.state == "negotiating":
        synthetic_message = (
            f"[Customer re-sent image of: {product_name} — negotiation is ongoing, continue from last counter price]"
        )
    else:
        synthetic_message = f"[Customer sent image of: {product_name}]"

    reply, new_state, extra = await generate_bot_reply(
        conversation, synthetic_message, seller, db, conv_product=conv_product
    )

    if new_state:
        conversation.state = new_state
    if extra.get("agreed_price"):
        conversation.agreed_price = extra["agreed_price"]
        conversation.last_counter_price = extra["agreed_price"]
        conv_product.agreed_price = extra["agreed_price"]
        conv_product.last_counter_price = extra["agreed_price"]
    if extra.get("negotiation_round") is not None:
        conversation.negotiation_round = extra["negotiation_round"]
        conv_product.negotiation_round = extra["negotiation_round"]
    if extra.get("last_counter_price") is not None:
        conversation.last_counter_price = extra["last_counter_price"]
        conv_product.last_counter_price = extra["last_counter_price"]

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
