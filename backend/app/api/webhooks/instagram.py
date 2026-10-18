import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.conversation import Conversation
from app.models.seller import Seller

logger = logging.getLogger(__name__)

router = APIRouter()


# GET /webhooks/instagram — Meta webhook verification

@router.get("/webhooks/instagram")
async def verify_webhook(
    hub_mode: str = Query(default=None, alias="hub.mode"),
    hub_challenge: str = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str = Query(default=None, alias="hub.verify_token"),
):
    """Meta calls this once to verify the webhook endpoint before sending events."""
    if settings.META_VERIFY_TOKEN and hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Instagram webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("Instagram webhook verification failed — bad verify token")
    raise HTTPException(status_code=403, detail="Verification failed")


# POST /webhooks/instagram — Receive DM events

@router.post("/webhooks/instagram")
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hub_signature_256: str = Header(default=None),
):
    """Receives Instagram DM events from Meta. Validates signature, routes to handler."""
    body = await request.body()

    _verify_signature(body, x_hub_signature_256)

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    if payload.get("object") != "instagram":
        return {"status": "ignored"}
    entries = payload.get("entry", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise HTTPException(status_code=400, detail="Invalid webhook entries")
    from app.services.instagram_ingress import validate_message_shape
    try:
        for entry in entries:
            for key in ("messaging", "changes"):
                if not isinstance(entry.get(key, []), list):
                    raise ValueError("Invalid webhook entry")
            for event in entry.get("messaging", []):
                validate_message_shape(event)
            for change in entry.get("changes", []):
                if not isinstance(change, dict) or (change.get("value") is not None and not isinstance(change["value"], dict)):
                    raise ValueError("Invalid webhook change")
                value = change.get("value") or {}
                if any(value.get(key) is not None and not isinstance(value[key], dict) for key in ("media", "from")):
                    raise ValueError("Invalid webhook change")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook event")
    from app.services.comment_automation import ingest_comment
    for entry in entries:
        for messaging_event in entry.get("messaging", []):
            await _handle_messaging_event(messaging_event, db)
        for change in entry.get("changes", []):
            await ingest_comment(db, entry.get("id"), change, entry.get("time"))

    # Actionable DM receipts have committed before acknowledging Meta.
    return {"status": "ok"}


# Signature verification

def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Validates X-Hub-Signature-256 to confirm the request is from Meta."""
    if not settings.META_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook signature verification is not configured")

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=400, detail="Missing signature header")

    expected = hmac.new(
        settings.META_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")

    if not received.isascii() or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Invalid signature")


# Event routing

async def _handle_messaging_event(event: dict, db: AsyncSession) -> None:
    from app.services.instagram_ingress import validate_message_shape
    try:
        validate_message_shape(event)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook event")
    sender_id: str = (event.get("sender") or {}).get("id", "")
    recipient_id: str = (event.get("recipient") or {}).get("id", "")  # seller's Instagram page ID

    if not sender_id or not recipient_id:
        return

    message = event.get("message") or {}
    if not message:
        return

    # Reserved proof commands must never enter echo/transcript/automation paths.
    from app.services.customer_links import ingest_instagram_command
    if await ingest_instagram_command(db, event):
        await db.commit()
        return

    # Echo events fire for every outbound message from the seller's IG account —
    # both the bot's own sends AND the seller replying manually from IG's inbox.
    # We classify by mid: if the echo's mid matches one we already stored on a
    # bot turn, it's our own send (drop). Otherwise, the seller typed it
    # manually in IG → record it + stamp last_seller_manual_reply_at so the
    # bot pauses for this conversation.
    if message.get("is_echo"):
        await _handle_echo_event(sender_id, recipient_id, message, db)
        return

    text: str | None = message.get("text")
    attachments: list = message.get("attachments", [])

    # Quick-exit: nothing actionable
    if not text and not attachments:
        return

    from app.services.instagram_ingress import persist_message, BATCH_SECONDS
    try:
        receipt = await persist_message(db, event)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook event")
    if receipt is not None:
        # The receipt is committed already. Broker outages cannot lose accepted
        # work; the periodic recovery scanner dispatches pending DB receipts.
        try:
            from app.workers.instagram_ingress import process_instagram_ingress
            process_instagram_ingress.apply_async(
                args=[str(receipt.seller_id), receipt.account_id, receipt.customer_id],
                countdown=BATCH_SECONDS,
            )
        except Exception:
            logger.warning("Instagram ingress wake-up unavailable; durable receipt retained")


def is_known_outbound_mid(messages: list[dict], mid: str | None) -> bool:
    """True if this Instagram message_id is already on record in conversation history.

    Used to distinguish the bot's own echo (we sent it, we stored the mid) from
    a seller's manual reply typed in IG's inbox (mid is novel to us). Returns
    False when mid is falsy — without a mid we can't match anything, so we err
    on the side of "treat as seller manual" to avoid silently swallowing real
    seller activity.
    """
    if not mid:
        return False
    for entry in messages or []:
        if entry.get("mid") == mid:
            return True
    return False


def build_seller_manual_entry(text: str, mid: str | None, now: datetime | None = None) -> dict:
    """Construct the JSONB entry to append to conversation.messages for a manual reply."""
    entry: dict = {
        "role": "seller_manual",
        "content": text or "",
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
    }
    if mid:
        entry["mid"] = mid
    return entry


async def _handle_echo_event(
    seller_page_id: str,
    customer_ig_id: str,
    message: dict,
    db: AsyncSession,
) -> None:
    """Classify echo: bot's own send → drop. Seller manual reply → record + stamp."""
    from app.integrations.instagram import is_registered_outbound_mid

    echo_mid = message.get("mid")
    echo_text = message.get("text") or ""
    has_attachment = bool(message.get("attachments") or message.get("attachment"))

    # Fast path: the bot registered this mid the moment it sent the message.
    # Robust against the JSONB tag losing the race with the echo webhook.
    if is_registered_outbound_mid(echo_mid):
        return

    # An attachment-only echo with no text (e.g. the bot's own photo send, or a
    # delivery artifact) carries no manual-reply signal — recording it just
    # creates a blank seller_manual entry and falsely pauses the bot. Skip it.
    if not echo_text and has_attachment:
        logger.info("Skipping blank attachment echo (mid=%s)", echo_mid)
        return

    seller = await _get_seller_by_page_id(seller_page_id, db)
    if not seller:
        # Echo for a page we don't manage — nothing to do.
        return

    # Find the (single, permanent) conversation with this customer. Echoes only
    # matter when there's an existing thread; if there isn't one, it was a
    # seller-initiated outbound to someone who never messaged us — ignore.
    result = await db.execute(
        select(Conversation).where(
            Conversation.seller_id == seller.id,
            Conversation.customer_instagram_id == customer_ig_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return

    if is_known_outbound_mid(conversation.messages or [], echo_mid):
        # Bot's own echo (or duplicate webhook delivery) — already recorded.
        return

    msgs = list(conversation.messages or [])
    msgs.append(build_seller_manual_entry(echo_text, echo_mid))
    conversation.messages = msgs
    conversation.last_seller_manual_reply_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    logger.info(
        "seller manual reply detected for conversation %s (text=%r) — bot paused",
        conversation.id, echo_text,
    )
    # No ETA scheduling here — the celery-beat scan_resume_paused_conversations
    # task picks up expired pauses every RESUME_SCAN_EVERY_SECONDS. That survives
    # worker restarts and deploys, which the old per-message ETA task did not.


async def _get_seller_by_page_id(page_id: str, db: AsyncSession) -> Seller | None:
    result = await db.execute(
        select(Seller).where(Seller.instagram_page_id == page_id, Seller.is_active == True)
    )
    return result.scalar_one_or_none()


async def _get_or_create_conversation(
    seller: Seller,
    customer_instagram_id: str,
    db: AsyncSession,
) -> Conversation:
    # One permanent conversation per (seller, customer) — the customer thread.
    # No status: it's never closed, so we just fetch it or create it once.
    # Keep creation races inside a savepoint so a uniqueness conflict cannot
    # roll back the caller's durable receipt locks or other processing changes.
    seller_id = seller.id

    def _q():
        return select(Conversation).where(
            Conversation.seller_id == seller_id,
            Conversation.customer_instagram_id == customer_instagram_id,
        )

    def _new() -> Conversation:
        return Conversation(
            seller_id=seller_id,
            customer_instagram_id=customer_instagram_id,
            messages=[],
        )

    conversation = (await db.execute(_q())).scalar_one_or_none()
    if conversation:
        return conversation

    try:
        async with db.begin_nested():
            conversation = _new()
            db.add(conversation)
            await db.flush()
        return conversation
    except IntegrityError:
        conversation = (await db.execute(_q())).scalar_one_or_none()
        if conversation is None:
            raise
        return conversation


import re as _re

_IG_URL_RE = _re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+")
