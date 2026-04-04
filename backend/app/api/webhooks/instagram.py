import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.conversation import Conversation
from app.models.seller import Seller
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /webhooks/instagram — Meta webhook verification
# ---------------------------------------------------------------------------

@router.get("/webhooks/instagram")
async def verify_webhook(
    hub_mode: str = None,
    hub_challenge: str = None,
    hub_verify_token: str = None,
):
    """Meta calls this once to verify the webhook endpoint before sending events."""
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Instagram webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("Instagram webhook verification failed — bad verify token")
    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------------------------------
# POST /webhooks/instagram — Receive DM events
# ---------------------------------------------------------------------------

@router.post("/webhooks/instagram")
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hub_signature_256: str = Header(default=None),
):
    """Receives Instagram DM events from Meta. Validates signature, routes to handler."""
    body = await request.body()

    _verify_signature(body, x_hub_signature_256)

    payload: dict[str, Any] = await request.json()
    logger.info("RAW PAYLOAD: %s", payload)

    for entry in payload.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            sender_id = messaging_event.get("sender", {}).get("id", "?")
            msg = messaging_event.get("message", {})
            text = msg.get("text", "")
            is_echo = msg.get("is_echo", False)
            logger.info(
                "DM event — sender=%s echo=%s text=%r full=%s",
                sender_id, is_echo, text, messaging_event,
            )
            await _handle_messaging_event(messaging_event, db)

    # Always return 200 quickly — Meta will retry if we don't
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Validates X-Hub-Signature-256 to confirm the request is from Meta."""
    if not settings.META_WEBHOOK_SECRET:
        # Skip in dev if secret not set
        logger.warning("META_WEBHOOK_SECRET not set — skipping signature verification")
        return

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=400, detail="Missing signature header")

    expected = hmac.new(
        settings.META_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Invalid signature")


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------

async def _handle_messaging_event(event: dict, db: AsyncSession) -> None:
    sender_id: str = event.get("sender", {}).get("id", "")
    recipient_id: str = event.get("recipient", {}).get("id", "")  # seller's Instagram page ID

    if not sender_id or not recipient_id:
        return

    message = event.get("message", {})
    if not message or message.get("is_echo"):
        # Ignore echo events (messages the bot itself sent)
        return

    text: str | None = message.get("text")
    attachments: list = message.get("attachments", [])

    # Quick-exit: nothing actionable
    if not text and not attachments:
        return

    # Verify seller exists before queuing
    seller = await _get_seller_by_page_id(recipient_id, db)
    if not seller:
        logger.warning("No seller found for Instagram page ID %s", recipient_id)
        return

    # Serialize event(s) to Redis and schedule / reschedule the batch task
    from app.workers.message_batch import enqueue_event, get_pending_task_id, set_pending_task_id, BATCH_WINDOW_SECONDS

    def _queue_and_schedule(serialised: dict) -> None:
        enqueue_event(recipient_id, sender_id, serialised)

        # Revoke any previously scheduled task for this conversation
        old_task_id = get_pending_task_id(recipient_id, sender_id)
        if old_task_id:
            celery_app.control.revoke(old_task_id)

        # Schedule new task BATCH_WINDOW_SECONDS from now
        from app.workers.message_batch import process_message_batch
        result = process_message_batch.apply_async(
            args=[recipient_id, sender_id],
            countdown=BATCH_WINDOW_SECONDS,
        )
        set_pending_task_id(recipient_id, sender_id, result.id)
        logger.info(
            "Queued event type=%s for %s:%s, task=%s",
            serialised.get("type"), recipient_id, sender_id, result.id,
        )

    if attachments:
        for attachment in attachments:
            atype = attachment.get("type")
            payload = attachment.get("payload", {})

            if atype == "image":
                image_url: str = payload.get("url", "")
                if image_url:
                    _queue_and_schedule({"type": "image", "image_url": image_url})

            elif atype in ("video", "ig_reel", "share"):
                reel_url: str = payload.get("url", "") or payload.get("link", "")
                if reel_url:
                    _queue_and_schedule({
                        "type": "reel",
                        "reel_url": reel_url,
                        "reel_video_id": payload.get("reel_video_id"),
                        "reel_title": payload.get("title"),
                    })

    elif text:
        reply_to_mid: str | None = message.get("reply_to", {}).get("mid")
        if reply_to_mid:
            logger.info("reply_to detected: mid=%s text=%r", reply_to_mid, text)
        _queue_and_schedule({"type": "text", "text": text, "reply_to_mid": reply_to_mid})


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
    result = await db.execute(
        select(Conversation).where(
            Conversation.seller_id == seller.id,
            Conversation.customer_instagram_id == customer_instagram_id,
            Conversation.state.not_in(["payment_confirmed", "failed", "dispatched_notified"]),
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(
            seller_id=seller.id,
            customer_instagram_id=customer_instagram_id,
            state="greeting",
            messages=[],
        )
        db.add(conversation)
        await db.flush()
        logger.info(
            "New conversation %s for seller %s with customer %s",
            conversation.id, seller.id, customer_instagram_id,
        )

    return conversation


import re as _re

_IG_URL_RE = _re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+")


#  UPDATE sellers                                                                                                                                                                                                                                
#   SET instagram_token = 'PASTE_FULL_NEW_TOKEN_HERE'                                                                                                                                                                                             
#   WHERE instagram_id = '26686840534336341';
# IGAArmnXUkl2RBZAFpqWkthOVhxRm1Dc3JDdXl0N0lmOU1WMnJpdVhveFE2VnVKM0NDXzdyZAUEzekNXazRtdnlFQ2JCZAUtIa24taHl1ZAGFpaWR6bW5FVGZAlVzZAGM1loV1NvcEhTQXRJdXl4MWc3YzdMb1VsUGFWenN2eWwwSUVscwZDZD


# curl -X POST "https://graph.facebook.com/v19.0/26686840534336341/messages" \                                                                                                                                                                  
#     -H "Content-Type: application/json" \                                                                                                                                                                                                       
#     -d '{                                                                                                                                                                                                                                       
#       "recipient": {"id": "957282080130744"},                                                                                                                                                                                                   
#       "message": {"text": "Test"},                                                                                                                                                                                                              
#       "messaging_type": "RESPONSE"                                                                                                                                                                                                              
#     }' \                                                                                                                                                                                                                                        
#     -d "access_token="

#     curl -X POST "https://graph.facebook.com/v19.0/993227930551466/messages?access_token=IGAArmnXUkl2RBZAFpqWkthOVhxRm1Dc3JDdXl0N0lmOU1WMnJpdVhveFE2VnVKM0NDXzdyZAUEzekNXazRtdnlFQ2JCZAUtIa24taHl1ZAGFpaWR6bW5FVGZAlVzZAGM1loV1NvcEhTQXRJdXl4MWc3YzdMb1VsUGFWenN2eWwwSUVscwZDZD" \                                                                                                                                            
#     -H "Content-Type: application/json" \                                                                                                                                                                                                       
#     -d '{"recipient":{"id":"957282080130744"},"message":{"text":"Test"},"messaging_type":"RESPONSE"}'