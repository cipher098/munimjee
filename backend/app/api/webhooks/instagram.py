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

    # Resolve which seller owns this page (match on FB page ID from webhook)
    seller = await _get_seller_by_page_id(recipient_id, db)
    if not seller:
        logger.warning("No seller found for Instagram page ID %s", recipient_id)
        return

    # Get or create conversation
    conversation = await _get_or_create_conversation(seller, sender_id, db)

    if attachments:
        await _handle_attachment(conversation, seller, attachments, db)
    elif text:
        await _handle_text_message(conversation, seller, text, db)


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


async def _handle_text_message(
    conversation: Conversation,
    seller: Seller,
    text: str,
    db: AsyncSession,
) -> None:
    from app.bot.conversation import advance_conversation

    logger.info(
        "Text message in conversation %s (state=%s): %r",
        conversation.id, conversation.state, text,
    )

    await advance_conversation(conversation, seller, text, db)
    await db.commit()


async def _handle_attachment(
    conversation: Conversation,
    seller: Seller,
    attachments: list,
    db: AsyncSession,
) -> None:
    from app.bot.conversation import handle_payment_screenshot, handle_product_image

    for attachment in attachments:
        if attachment.get("type") == "image":
            image_url: str = attachment.get("payload", {}).get("url", "")
            if not image_url:
                continue

            if conversation.state == "awaiting_payment":
                logger.info("Payment screenshot received in conversation %s", conversation.id)
                await handle_payment_screenshot(conversation, seller, image_url, db)

            elif conversation.state in ("greeting", "product_inquiry", "negotiating"):
                logger.info(
                    "Product image received in conversation %s (state=%s)",
                    conversation.id, conversation.state,
                )
                await handle_product_image(conversation, seller, image_url, db)

            else:
                logger.debug(
                    "Image received in unexpected state %s — ignoring", conversation.state
                )


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