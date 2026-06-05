"""
Conversation state machine (per ConversationProduct).

States (conv_product.state):
  product_inquiry → negotiating → awaiting_payment
  → verifying → payment_confirmed | failed | manual_review
  → dispatched_notified | not_interested | waiting_for_tag
"""
import base64
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import llm_logging
from app.models.conversation import Conversation
from app.models.conversation_product import ConversationProduct
from app.models.product import Product
from app.models.seller import Seller

logger = logging.getLogger(__name__)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _capture_llm_calls(db, *, seller_id, conversation_id, customer_message_mid=None):
    """Capture every LLM call made during a turn and persist the cost ledger.

    Brackets a top-level handler so all nested decide/reply/subagent calls
    (including those in child asyncio tasks, e.g. the intent classifier)
    attribute themselves to this conversation + triggering message. Rows are
    staged on `db` and flushed even if the body raises, so failed-turn costs
    are still recorded.
    """
    token = llm_logging.begin(
        seller_id=seller_id,
        conversation_id=conversation_id,
        customer_message_mid=customer_message_mid,
    )
    try:
        yield
    finally:
        try:
            await llm_logging.persist(db)
        finally:
            llm_logging.end(token)

TERMINAL_STATES = {"payment_confirmed", "failed", "dispatched_notified"}
# `customer_disengaged` is NOT terminal — conversation stays active so the
# customer's next message doesn't spawn a fresh conversation. Bot silence is
# instead enforced by Conversation.disengage_paused_until (see worker pause gate).


async def _sweep_inquiry_to_not_interested(conversation_id, db: AsyncSession) -> None:
    """On conversation close, mark any still-open product_inquiry records as not_interested."""
    result = await db.execute(
        select(ConversationProduct).where(
            ConversationProduct.conversation_id == conversation_id,
            ConversationProduct.state == "product_inquiry",
        )
    )
    for cp in result.scalars().all():
        cp.state = "not_interested"
        logger.info("Sweep: product %s → not_interested on conversation close", cp.product_id)


async def _classify_image_type(image_b64: str, media_type: str) -> str:
    """Returns 'payment' if the image is a payment receipt/screenshot, else 'product'.
    Routed to the agents.yaml-configured provider (vision) with fallback."""
    from app.integrations import llm_provider

    prompt = (
        "Is this image a payment receipt or transaction confirmation screenshot "
        "(UPI, Paytm, PhonePe, Google Pay, bank transfer success screen, etc.)? "
        "Reply with exactly one word: 'payment' or 'product'."
    )
    try:
        result = (await llm_provider.complete_vision(
            "classify_image_type",
            prompt=prompt,
            image={"kind": "base64", "media_type": media_type, "data": image_b64},
        )).strip().lower()
    except Exception as exc:
        logger.warning("Image-type classify failed (%s) — defaulting to 'product'", exc)
        return "product"
    return "payment" if "payment" in result else "product"


def _detect_media_type(data: bytes) -> str:
    """Detect image media type from magic bytes — don't trust Content-Type headers."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"  # fallback


def _append_message(conversation: Conversation, role: str, content: str, mid: str | None = None) -> None:
    messages = list(conversation.messages or [])
    entry: dict = {"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()}
    if mid:
        entry["mid"] = mid
    messages.append(entry)
    conversation.messages = messages


def _append_bot_reply(conversation: Conversation, reply: str, send_reply: bool) -> None:
    """Only record bot reply in message history when it will actually be sent."""
    if send_reply:
        _append_message(conversation, "bot", reply)


def _tag_last_bot_message_mid(conversation: Conversation, mid: str) -> None:
    """After send_message returns, store the Instagram message_id (and current product_id)
    on the last bot message so reply_to context can identify which product it was about."""
    msgs = list(conversation.messages or [])
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "bot":
            update: dict = {"mid": mid}
            if conversation.product_id:
                update["product_id"] = str(conversation.product_id)
            msgs[i] = {**msgs[i], **update}
            conversation.messages = msgs
            return


async def _send_and_tag(
    conversation: Conversation,
    client,
    reply: str,
    db: AsyncSession,
) -> None:
    """Send a text reply, capture the mid, and tag the last bot history entry."""
    try:
        result = await client.send_message(conversation.customer_instagram_id, reply)
        mid = result.get("message_id")
        if mid:
            _tag_last_bot_message_mid(conversation, mid)
            await db.flush()
    except Exception as exc:
        logger.error(
            "Failed to send Instagram reply in conversation %s: %s — reply saved to DB",
            conversation.id, exc,
        )


def find_message_by_mid(conversation: Conversation, mid: str) -> dict | None:
    """Return the message dict matching the given Instagram message_id, or None."""
    for msg in (conversation.messages or []):
        if msg.get("mid") == mid:
            return msg
    return None


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


async def _send_next_product_photo(
    conversation: Conversation,
    seller: Seller,
    product,
    conv_product: "ConversationProduct | None",
    db: AsyncSession,
) -> bool:
    """Send the next unsent product photo. Returns True if a photo was sent."""
    if not product:
        return False

    from app.config import settings
    from app.integrations.instagram import InstagramClient

    # Build the photo list. If the customer has locked in a variant
    # ("blue dedo") and that variant exists on the product, cycle ONLY its
    # photos. Otherwise fall back to the flat photo_url + photo_urls list.
    all_photos: list[str] = []
    variant_label = conv_product.active_variant_label if conv_product else None
    variants = product.variants or []
    matched_variant_photos: list[str] = []
    if variant_label and variants:
        wanted = variant_label.strip().casefold()
        for v in variants:
            if (v.get("label") or "").strip().casefold() == wanted:
                matched_variant_photos = list(v.get("photo_urls") or [])
                break

    if matched_variant_photos:
        all_photos.extend(matched_variant_photos)
    else:
        if product.photo_url:
            all_photos.append(product.photo_url)
        if product.photo_urls:
            all_photos.extend(product.photo_urls)

    if not all_photos:
        return False

    idx = conv_product.photos_sent_count if conv_product else 0
    if idx >= len(all_photos):
        # All photos already sent — wrap around to first photo
        idx = 0
        if conv_product:
            conv_product.photos_sent_count = 0

    photo_url = all_photos[idx]
    if photo_url.startswith("/") and settings.PUBLIC_BASE_URL:
        photo_url = settings.PUBLIC_BASE_URL.rstrip("/") + photo_url
    elif photo_url.startswith("/"):
        logger.warning("Cannot send product image — PUBLIC_BASE_URL not set")
        return False

    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    try:
        result = await client.send_image(conversation.customer_instagram_id, photo_url)
        logger.info("Sent product photo %d/%d for %r", idx + 1, len(all_photos), product.name)
        if conv_product:
            conv_product.photos_sent_count = idx + 1
        # Record the image in message history so reply_to on this photo can be resolved
        msgs = list(conversation.messages or [])
        msgs.append({"role": "bot", "content": "[product photo]"})
        conversation.messages = msgs
        mid = result.get("message_id")
        if mid:
            _tag_last_bot_message_mid(conversation, mid)
        await db.flush()
        return True
    except Exception as exc:
        logger.warning("Could not send product photo for %r: %s", product.name, exc)
        return False


async def _send_product_image_if_new(
    conversation: Conversation,
    seller: Seller,
    product,
    db: AsyncSession,
) -> None:
    """Send product photo to customer when a product is first identified in this conversation.
    Backwards-compatible wrapper around _send_next_product_photo.
    """
    await _send_next_product_photo(conversation, seller, product, None, db)


# ---------------------------------------------------------------------------
# Payment (UPI) — sharing the QR + saving received screenshots
# ---------------------------------------------------------------------------

async def _get_primary_upi_method(seller_id, db: AsyncSession):
    """The seller's primary active UPI payment method (or the oldest active one)."""
    from app.models.payment_method import PaymentMethod
    res = await db.execute(
        select(PaymentMethod)
        .where(
            PaymentMethod.seller_id == seller_id,
            PaymentMethod.category == "upi",
            PaymentMethod.is_active == True,  # noqa: E712
        )
        .order_by(PaymentMethod.is_primary.desc(), PaymentMethod.created_at.asc())
    )
    return res.scalars().first()


async def _share_primary_payment_method(conversation, seller, conv_product, db) -> str | None:
    """On entering awaiting_payment: record which UPI method we're sharing + when,
    send its QR image, and return a deterministic payment-instruction text to send
    (UPI id + exact amount come from the DB, never the LLM). Returns None if the
    seller has no usable UPI method (caller keeps the existing manual flow)."""
    from app.config import settings
    from app.integrations.instagram import InstagramClient

    method = await _get_primary_upi_method(seller.id, db)
    if method is None or not method.upi_id:
        logger.warning("No active UPI payment method for seller %s — cannot share QR", seller.id)
        return None

    conv_product.payment_method_id = method.id
    conv_product.payment_requested_at = datetime.now(timezone.utc)

    due_paise = (conv_product.agreed_price or conv_product.last_counter_price or 0) - (conv_product.amount_paid or 0)

    # Send the QR image if configured + publicly reachable.
    if method.qr_code_url:
        qr_url = method.qr_code_url
        if qr_url.startswith("/") and settings.PUBLIC_BASE_URL:
            qr_url = settings.PUBLIC_BASE_URL.rstrip("/") + qr_url
        elif qr_url.startswith("/"):
            logger.warning("Cannot send payment QR — PUBLIC_BASE_URL not set")
            qr_url = None
        if qr_url:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            try:
                result = await client.send_image(conversation.customer_instagram_id, qr_url)
                msgs = list(conversation.messages or [])
                msgs.append({"role": "bot", "content": "[payment QR]"})
                conversation.messages = msgs
                mid = result.get("message_id")
                if mid:
                    _tag_last_bot_message_mid(conversation, mid)
            except Exception as exc:
                logger.warning("Could not send payment QR: %s", exc)
    await db.flush()

    amount_str = f"₹{due_paise // 100} " if due_paise > 0 else ""
    return (
        f"{amount_str}ka payment is UPI pe kar do: {method.upi_id} 🙏 "
        f"QR bhi bhej diya hai, scan karke pay kar sakte ho. "
        f"Payment ke baad screenshot bhej dena, turant confirm kar dunga ✅"
    )


def _save_payment_screenshot(img_bytes: bytes, media_type: str) -> str | None:
    """Persist a received payment screenshot under uploads for audit. Returns the
    /uploads/... URL, or None on failure (verification still proceeds)."""
    from pathlib import Path
    from uuid import uuid4
    try:
        ext = {"image/png": ".png", "image/webp": ".webp"}.get(media_type, ".jpg")
        d = Path("/app/uploads/payment_screenshots/received")
        d.mkdir(parents=True, exist_ok=True)
        fname = f"pay_{uuid4().hex}{ext}"
        (d / fname).write_bytes(img_bytes)
        return f"/uploads/payment_screenshots/received/{fname}"
    except Exception as exc:
        logger.warning("Could not save payment screenshot: %s", exc)
        return None


async def advance_conversation(
    conversation: Conversation,
    seller: Seller,
    customer_message: str,
    db: AsyncSession,
    send_reply: bool = True,
    resume: bool = False,
    customer_mid: str | None = None,
) -> None:
    """Main entry point: processes a customer text message and sends a bot reply.
    Pass resume=True when re-processing an already-stored customer message so it
    is not appended to history a second time.
    """
    if conversation.status == "closed":
        return

    async with _capture_llm_calls(
        db,
        seller_id=seller.id,
        conversation_id=conversation.id,
        customer_message_mid=customer_mid,
    ):
        await _advance_conversation_inner(
            conversation, seller, customer_message, db, send_reply, resume, customer_mid
        )


async def _advance_conversation_inner(
    conversation: Conversation,
    seller: Seller,
    customer_message: str,
    db: AsyncSession,
    send_reply: bool,
    resume: bool,
    customer_mid: str | None,
) -> None:
    if not resume:
        _append_message(conversation, "customer", customer_message, mid=customer_mid)

    if not conversation.customer_gender and conversation.customer_name:
        from app.utils.gender import guess_gender, guess_gender_ai
        gender = guess_gender(conversation.customer_name)
        if gender == "unknown":
            gender = await guess_gender_ai(conversation.customer_name)
        conversation.customer_gender = gender

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

    if new_state == "not_interested":
        # Mark this product as rejected, then reset conversation to allow new product inquiry
        if conv_product is not None:
            conv_product.state = "not_interested"
        conversation.product_id = None
    elif new_state:
        if conv_product is not None:
            conv_product.state = new_state
        # Close conversation when a terminal state is reached
        if new_state in TERMINAL_STATES:
            conversation.status = "closed"
            await _sweep_inquiry_to_not_interested(conversation.id, db)

    # On entering awaiting_payment, share the seller's primary UPI QR once and
    # append exact payment instructions (UPI id + amount from DB, never the LLM).
    if new_state == "awaiting_payment" and conv_product is not None and conv_product.payment_requested_at is None:
        _pay_instr = await _share_primary_payment_method(conversation, seller, conv_product, db)
        if _pay_instr:
            reply = f"{reply}\n\n{_pay_instr}" if reply else _pay_instr

    # Mark explicitly rejected non-active products as not_interested
    rejected_ids = extra.get("rejected_product_ids") or []
    for rid in rejected_ids:
        _rej_res = await db.execute(
            select(ConversationProduct).where(
                ConversationProduct.conversation_id == conversation.id,
                ConversationProduct.product_id == rid,
            )
        )
        _rej_cp = _rej_res.scalar_one_or_none()
        if _rej_cp and _rej_cp.state not in TERMINAL_STATES:
            _rej_cp.state = "not_interested"
            logger.info("Marked product %s as not_interested (customer dismissed)", rid)

    # Bundle pitched — set flag to prevent repeat
    if extra.get("bundle_pitch") and conv_product is not None:
        conv_product.bundle_pitched = True

    # Variant lock-in: customer picked a specific color/size. Reset the photo
    # counter so the next photo cycle starts from this variant's first image.
    selected_variant = extra.get("selected_variant_label")
    if selected_variant and conv_product is not None:
        if conv_product.active_variant_label != selected_variant:
            conv_product.active_variant_label = selected_variant
            conv_product.photos_sent_count = 0

    # Disengagement pause: customer said "bye"/"ok"/"nahi chahiye" and the bot
    # is sending one warm ack. Stay quiet for CUSTOMER_DISENGAGE_PAUSE_MINUTES.
    if extra.get("start_disengage_pause"):
        from app.config import settings as _settings
        from datetime import timedelta
        conversation.disengage_paused_until = (
            datetime.now(timezone.utc)
            + timedelta(minutes=_settings.CUSTOMER_DISENGAGE_PAUSE_MINUTES)
        )

    if extra.get("agreed_price"):
        if conv_product is not None:
            conv_product.agreed_price = extra["agreed_price"]
            # Lock last_counter_price to agreed price — if customer renegotiates, can't go lower
            conv_product.last_counter_price = extra["agreed_price"]

    if extra.get("negotiation_round") is not None:
        if conv_product is not None:
            conv_product.negotiation_round = extra["negotiation_round"]

    if extra.get("last_counter_price") is not None:
        if conv_product is not None:
            conv_product.last_counter_price = extra["last_counter_price"]

    # last_shown_price is a monotonic floor on customer-facing prices: it only ever
    # ratchets DOWN. Once we've shown ₹1100, we can never quote higher; if we later
    # quote ₹1050, the new value wins.
    if extra.get("last_shown_price") is not None and conv_product is not None:
        new_shown = extra["last_shown_price"]
        if conv_product.last_shown_price is None or new_shown < conv_product.last_shown_price:
            conv_product.last_shown_price = new_shown

    new_product_id = extra.get("product_id")
    if new_product_id:
        from sqlalchemy import select as sa_select
        from app.models.product import Product as ProductModel
        is_new_product = str(new_product_id) != str(conversation.product_id)

        # If switching away from the current product and it was explicitly rejected
        # (not just browsing via show_product), close it out
        if is_new_product and conv_product is not None and not extra.get("send_image"):
            _old_pid = str(conversation.product_id)
            _already_rejected = [str(r) for r in (extra.get("rejected_product_ids") or [])]
            _closeable = {"product_inquiry", "negotiating"}
            if conv_product.state in _closeable and _old_pid not in _already_rejected:
                _old_state = conv_product.state
                conv_product.state = "not_interested"
                logger.info(
                    "Product switched away from %s (state=%s) without explicit browse — marking not_interested",
                    _old_pid, _old_state,
                )

        conversation.product_id = new_product_id

        result = await db.execute(sa_select(ProductModel).where(ProductModel.id == new_product_id))
        img_product = result.scalar_one_or_none()

        if is_new_product:
            # Product switched — send first photo of new product
            new_conv_product = await _get_or_create_conv_product(conversation.id, new_product_id, db)
            new_conv_product.photos_sent_count = 0
            await _send_next_product_photo(conversation, seller, img_product, new_conv_product, db)
        elif extra.get("send_image"):
            await _send_next_product_photo(conversation, seller, img_product, conv_product, db)

    elif extra.get("send_image") and conversation.product_id:
        # send_image requested but product_id wasn't in extra (same product already on conversation)
        from sqlalchemy import select as sa_select
        from app.models.product import Product as ProductModel
        result = await db.execute(sa_select(ProductModel).where(ProductModel.id == conversation.product_id))
        img_product = result.scalar_one_or_none()
        await _send_next_product_photo(conversation, seller, img_product, conv_product, db)

    if reply is None:
        # Conversation paused silently (e.g. waiting_for_tag) — do not send anything to customer
        await db.flush()
        return

    _append_bot_reply(conversation, reply, send_reply)
    await db.flush()

    if send_reply:
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        await _send_and_tag(conversation, client, reply, db)


async def handle_product_image(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
    send_reply: bool = True,
) -> None:
    """Customer sent an image — use Claude Vision to identify the product and start negotiation."""
    async with _capture_llm_calls(db, seller_id=seller.id, conversation_id=conversation.id):
        await _handle_product_image_inner(conversation, seller, image_url, db, send_reply)


async def _handle_product_image_inner(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
    send_reply: bool,
) -> None:
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
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
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
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
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
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
        return

    # Product identified — set it on conversation
    conversation.product_id = product_id

    # Get or create the ConversationProduct row for this product
    conv_product = await _get_or_create_conv_product(conversation.id, product_id, db)

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
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
        return

    # Send product image back to customer so they can confirm it's the right product —
    # only on fresh inquiry (no prior counter), not when re-sharing during negotiation.
    is_fresh_inquiry = not conv_product.last_counter_price and not conv_product.agreed_price
    if is_fresh_inquiry:
        conv_product.photos_sent_count = 0
        await _send_next_product_photo(conversation, seller, matched_product, conv_product, db)

    # Build a synthetic customer message for the responder.
    # During active negotiation, signal that it's a re-share, not a fresh inquiry —
    # so Claude doesn't restart the pitch at listed price.
    product_name = matched_product.name if matched_product else "product"
    if conv_product.state == "negotiating":
        synthetic_message = (
            f"[Customer re-sent image of: {product_name} — negotiation is ongoing, continue from last counter price]"
        )
    else:
        synthetic_message = f"[Customer sent image of: {product_name}]"

    reply, new_state, extra = await generate_bot_reply(
        conversation, synthetic_message, seller, db, conv_product=conv_product
    )

    if new_state:
        conv_product.state = new_state
        if new_state in TERMINAL_STATES:
            conversation.status = "closed"
    if extra.get("agreed_price"):
        conv_product.agreed_price = extra["agreed_price"]
        conv_product.last_counter_price = extra["agreed_price"]
    if extra.get("negotiation_round") is not None:
        conv_product.negotiation_round = extra["negotiation_round"]
    if extra.get("last_counter_price") is not None:
        conv_product.last_counter_price = extra["last_counter_price"]
    if extra.get("last_shown_price") is not None:
        new_shown = extra["last_shown_price"]
        if conv_product.last_shown_price is None or new_shown < conv_product.last_shown_price:
            conv_product.last_shown_price = new_shown

    _append_bot_reply(conversation, reply, send_reply)
    await db.flush()

    if send_reply:
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        await _send_and_tag(conversation, client, reply, db)


def _extract_ig_shortcode(url: str) -> str | None:
    """Extract shortcode from instagram.com/p/<code>/ or instagram.com/reel/<code>/."""
    import re
    m = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def _match_reel_url(incoming_url: str, stored_urls: list[str]) -> bool:
    """Return True if incoming_url matches any stored reel URL.

    Strategies tried in order:
    1. Exact URL match.
    2. asset_id match (both are CDN URLs).
    3. Instagram shortcode match (stored URL is instagram.com/p|reel/<code>/).
    """
    from urllib.parse import urlparse, parse_qs

    if not stored_urls:
        return False

    incoming_qs = parse_qs(urlparse(incoming_url).query)
    incoming_asset_id = incoming_qs.get("asset_id", [None])[0]
    incoming_shortcode = _extract_ig_shortcode(incoming_url)

    for stored in stored_urls:
        if stored == incoming_url:
            return True
        stored_qs = parse_qs(urlparse(stored).query)
        stored_asset_id = stored_qs.get("asset_id", [None])[0]
        if incoming_asset_id and stored_asset_id and incoming_asset_id == stored_asset_id:
            return True
        stored_shortcode = _extract_ig_shortcode(stored)
        if incoming_shortcode and stored_shortcode and incoming_shortcode == stored_shortcode:
            return True
    return False


async def handle_reel(
    conversation: Conversation,
    seller: Seller,
    reel_url: str,
    db: AsyncSession,
    reel_video_id: str | None = None,
    reel_title: str | None = None,
    send_reply: bool = True,
) -> None:
    """Customer shared an Instagram Reel — match against product reel_urls and start sales flow."""
    async with _capture_llm_calls(db, seller_id=seller.id, conversation_id=conversation.id):
        await _handle_reel_inner(
            conversation, seller, reel_url, db, reel_video_id, reel_title, send_reply
        )


async def _handle_reel_inner(
    conversation: Conversation,
    seller: Seller,
    reel_url: str,
    db: AsyncSession,
    reel_video_id: str | None,
    reel_title: str | None,
    send_reply: bool,
) -> None:
    from app.integrations.instagram import InstagramClient

    _append_message(conversation, "customer", f"[reel: {reel_url}]")
    await db.flush()

    # If we have a reel_video_id (media ID), resolve it to a shortcode via Graph API.
    # This lets us match CDN URLs against stored instagram.com/p/<shortcode>/ URLs.
    resolved_shortcode: str | None = None
    if reel_video_id:
        try:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            resolved_shortcode = await client.get_media_shortcode(reel_video_id)
            logger.info("Resolved reel_video_id %s → shortcode %s", reel_video_id, resolved_shortcode)
        except Exception as exc:
            logger.warning("Could not resolve reel_video_id %s: %s", reel_video_id, exc)

    # Build a synthetic URL with the resolved shortcode so _match_reel_url can compare
    effective_url = reel_url
    if resolved_shortcode:
        effective_url = f"https://www.instagram.com/reel/{resolved_shortcode}/"

    # Load all active products with reel_urls set
    result = await db.execute(
        select(Product).where(
            Product.seller_id == seller.id,
            Product.active == True,
            Product.reel_urls.isnot(None),
        )
    )
    products = result.scalars().all()

    matched_product = None
    for p in products:
        stored = p.reel_urls or []
        # Direct numeric ID match (stored IDs from oEmbed resolution)
        if reel_video_id and reel_video_id in stored:
            matched_product = p
            break
        # URL-based matching (shortcode/asset_id/exact)
        if _match_reel_url(effective_url, stored) or _match_reel_url(reel_url, stored):
            matched_product = p
            break

    # Fallback: if URL matching failed but we have a title, use Claude catalog match
    if not matched_product and reel_title:
        logger.info("URL match failed — trying title-based catalog match with: %r", reel_title)
        from app.integrations.claude import ClaudeClient
        all_result = await db.execute(
            select(Product).where(Product.seller_id == seller.id, Product.active == True)
        )
        all_products = all_result.scalars().all()
        products_for_match = [
            {"id": str(p.id), "name": p.name, "description": p.description or "", "listed_price_paise": p.listed_price}
            for p in all_products
        ]
        claude = ClaudeClient()
        match = await claude.match_product_by_description(reel_title, products_for_match)
        if match.get("confidence") in ("high", "medium") and match.get("product_id"):
            matched_product = next((p for p in all_products if str(p.id) == match["product_id"]), None)
            logger.info("Title-based match: %s (confidence: %s)", matched_product.name if matched_product else "none", match.get("confidence"))

    logger.info(
        "\n┌─────────────────────────────────────────\n"
        "│ REEL MATCH\n"
        "│ reel_video_id : %s\n"
        "│ SHORTCODE     : %s\n"
        "│ MATCHED       : %s\n"
        "└─────────────────────────────────────────",
        reel_video_id or "(none)",
        resolved_shortcode or "(not resolved)",
        matched_product.name if matched_product else "NO MATCH",
    )

    if not matched_product:
        reply = "Ye reel kaunse product ki hai? Product ka naam batao 😊"
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
        return

    # Product matched — set on conversation
    conversation.product_id = str(matched_product.id)
    conv_product = await _get_or_create_conv_product(conversation.id, str(matched_product.id), db)

    # If deal was already agreed, just send payment reminder
    if conv_product.agreed_price:
        agreed_rupees = conv_product.agreed_price // 100
        reply = (
            f"Bhai deal toh already ho gayi thi — ₹{agreed_rupees} mein! "
            f"Payment kar do, pack karke bhej deta hoon 🚀"
        )
        _append_bot_reply(conversation, reply, send_reply)
        await db.flush()
        if send_reply:
            client = InstagramClient(seller.instagram_token, seller.fb_page_id)
            await _send_and_tag(conversation, client, reply, db)
        return

    # Fresh inquiry — send product photo first
    is_fresh_inquiry = not conv_product.last_counter_price and not conv_product.agreed_price
    if is_fresh_inquiry:
        conv_product.photos_sent_count = 0
        await _send_next_product_photo(conversation, seller, matched_product, conv_product, db)

    from app.bot.responder import generate_bot_reply
    synthetic_message = f"[Customer shared reel of: {matched_product.name}]"
    reply, new_state, extra = await generate_bot_reply(
        conversation, synthetic_message, seller, db, conv_product=conv_product
    )

    if new_state:
        conv_product.state = new_state
        if new_state in TERMINAL_STATES:
            conversation.status = "closed"
    if extra.get("agreed_price"):
        conv_product.agreed_price = extra["agreed_price"]
        conv_product.last_counter_price = extra["agreed_price"]
    if extra.get("negotiation_round") is not None:
        conv_product.negotiation_round = extra["negotiation_round"]
    if extra.get("last_counter_price") is not None:
        conv_product.last_counter_price = extra["last_counter_price"]
    if extra.get("last_shown_price") is not None:
        new_shown = extra["last_shown_price"]
        if conv_product.last_shown_price is None or new_shown < conv_product.last_shown_price:
            conv_product.last_shown_price = new_shown

    _append_bot_reply(conversation, reply, send_reply)
    await db.flush()

    if send_reply:
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        await _send_and_tag(conversation, client, reply, db)


async def handle_payment_screenshot(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
) -> None:
    """Wrapper — captures the vision call's cost, then verifies the screenshot."""
    async with _capture_llm_calls(db, seller_id=seller.id, conversation_id=conversation.id):
        await _handle_payment_screenshot_inner(conversation, seller, image_url, db)


async def _handle_payment_screenshot_inner(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
) -> None:
    """Customer sent a payment screenshot while awaiting_payment.

    Auto-verifies it (vision extract + deterministic verdict); on a clean match
    records a Transaction and either confirms the order (cumulative ≥ agreed) or
    asks for the remaining balance (partial). Anything ambiguous/mismatched falls
    back to the existing manual seller-WhatsApp review — never auto-rejects.
    """
    from app.models.payment_method import PaymentMethod
    from app.models.transaction import Transaction
    from app.models.order import Order, OrderItem
    from app.bot import payment_verification as pv
    from app.bot.responder import send_manual_verification_ping
    from app.integrations.instagram import InstagramClient

    conv_product: ConversationProduct | None = None
    if conversation.product_id:
        conv_product = await _get_or_create_conv_product(
            conversation.id, conversation.product_id, db
        )
    _append_message(conversation, "customer", f"[screenshot: {image_url}]")
    if conv_product is not None:
        conv_product.state = "verifying"
    await db.flush()

    async def _send(text: str) -> None:
        _append_message(conversation, "bot", text)
        await db.flush()
        client = InstagramClient(seller.instagram_token, seller.fb_page_id)
        await _send_and_tag(conversation, client, text, db)

    async def _manual() -> None:
        await send_manual_verification_ping(conversation, seller, image_url, db, conv_product=conv_product)

    # We can only auto-verify if we actually shared a method (have a window + payee).
    if conv_product is None or conv_product.payment_requested_at is None or conv_product.payment_method_id is None:
        return await _manual()

    method = await db.get(PaymentMethod, conv_product.payment_method_id)

    # Download + persist the screenshot, then extract fields via vision.
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(image_url)
            r.raise_for_status()
        img_bytes = r.content
        img_b64 = base64.b64encode(img_bytes).decode()
        media_type = _detect_media_type(img_bytes)
    except Exception as exc:
        logger.warning("Could not download payment screenshot %s: %s — manual review", image_url, exc)
        return await _manual()

    screenshot_url = _save_payment_screenshot(img_bytes, media_type)
    from app.integrations.claude import ClaudeClient
    extracted = await ClaudeClient().extract_payment_details(img_b64, media_type)

    # Anti-replay: has this UTR ever been recorded?
    utr = (extracted.get("utr") or "").strip() or None
    utr_used = False
    if utr:
        _ex = await db.execute(select(Transaction).where(Transaction.utr_number == utr))
        utr_used = _ex.scalar_one_or_none() is not None

    remaining = (conv_product.agreed_price or 0) - (conv_product.amount_paid or 0)
    verdict = pv.evaluate_payment(
        extracted,
        method_upi_id=method.upi_id if method else None,
        method_account_name=method.account_name if method else None,
        shared_at=conv_product.payment_requested_at,
        received_at=datetime.now(timezone.utc),
        remaining_due_paise=remaining,
        utr_already_used=utr_used,
    )
    logger.info("Payment verdict for conv %s: %s (%s)", conversation.id, verdict.outcome, verdict.reason)

    if verdict.outcome == pv.DUPLICATE:
        await _send("Ye payment toh pehle hi mil chuka hai ✅")
        return
    if verdict.outcome == pv.MANUAL_REVIEW:
        return await _manual()

    # confirmed_full or partial → record the transaction against an order.
    order = (await db.execute(
        select(Order).where(Order.conversation_id == conversation.id,
                            Order.product_id == conversation.product_id)
    )).scalars().first()
    if order is None:
        order = Order(
            seller_id=seller.id, conversation_id=conversation.id,
            customer_name=conversation.customer_name or "",
            customer_instagram_id=conversation.customer_instagram_id,
            product_id=conversation.product_id,
            amount=conv_product.agreed_price or verdict.amount_paise,
            status="awaiting_payment",
        )
        db.add(order)
        await db.flush()
        db.add(OrderItem(
            order_id=order.id, conversation_product_id=conv_product.id,
            quantity=conv_product.quantity or 1,
            unit_price=conv_product.agreed_price or verdict.amount_paise,
        ))

    db.add(Transaction(
        seller_id=seller.id, order_id=order.id, utr_number=verdict.utr,
        amount=verdict.amount_paise, sender_name=extracted.get("payee_name"),
        timestamp=verdict.payment_dt or datetime.now(timezone.utc),
        verified_by="ocr_auto", screenshot_url=screenshot_url,
    ))
    conv_product.amount_paid = (conv_product.amount_paid or 0) + verdict.amount_paise
    await db.flush()

    if verdict.outcome == pv.PARTIAL:
        still_due = (conv_product.agreed_price or 0) - conv_product.amount_paid
        conv_product.state = "awaiting_payment"
        await _send(f"₹{verdict.amount_paise // 100} mil gaya ✅ Bas ₹{still_due // 100} aur bhej do, fir order pakka 🙏")
        return

    # confirmed_full
    order.status = "payment_confirmed"
    conv_product.state = "payment_confirmed"
    conversation.status = "closed"
    await _sweep_inquiry_to_not_interested(conversation.id, db)
    await db.flush()
    await _send("Payment confirm ho gaya 🎉 Aapka order aage badha diya hai, jaldi dispatch karenge!")
