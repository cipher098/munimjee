"""Normalize, commit and replay inbound IG messages; Redis is only a wake-up hint."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller

BATCH_SECONDS = 20
PROCESSING_TIMEOUT_SECONDS = 15 * 60
UNKNOWN_EFFECT_ERRORS = {"processing_failed_unknown_effect", "processing_interrupted_unknown_effect"}


def normalize_message(event: dict) -> list[dict]:
    """Keep only fields consumed by the existing processor, never the raw webhook.

    Match legacy attachment precedence: an attachment-bearing message is not also
    processed as text. URLs are needed for media processing, not logged here.
    """
    message = event.get("message") or {}
    if message.get("is_echo"):
        return []
    mid = message.get("mid")
    if mid is not None and (not isinstance(mid, str) or len(mid) > 255):
        raise ValueError("invalid_provider_message_id")
    normalized = []
    for attachment in message.get("attachments") or []:
        payload = attachment.get("payload") or {}
        kind = attachment.get("type")
        url = payload.get("url") or (payload.get("link") if kind in {"video", "ig_reel", "share"} else None)
        if not isinstance(url, str) or not url:
            continue
        if kind == "image":
            normalized.append({"type": "image", "image_url": url, "mid": mid})
        elif kind in {"video", "ig_reel", "share"}:
            normalized.append({"type": "reel", "reel_url": url,
                               "reel_video_id": payload.get("reel_video_id"),
                               "reel_title": payload.get("title"), "mid": mid})
    if not message.get("attachments") and isinstance(message.get("text"), str) and message["text"]:
        normalized.append({"type": "text", "text": message["text"],
                           "reply_to_mid": (message.get("reply_to") or {}).get("mid"), "mid": mid})
    return normalized


def event_key(event: dict, events: list[dict]) -> str:
    """Provider mid is stable even when a redelivery changes attachment URLs.

    Without mid, hash normalized content plus provider timestamp and participants.
    Identical no-mid/no-timestamp messages cannot be distinguished by Meta's data.
    """
    mid = (event.get("message") or {}).get("mid")
    identity = {"mid": mid} if mid else {
        "sender": (event.get("sender") or {}).get("id"),
        "recipient": (event.get("recipient") or {}).get("id"),
        "timestamp": event.get("timestamp"), "events": events,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def persist_message(db, event: dict) -> InstagramIngress | None:
    events = normalize_message(event)
    if not events:
        return None
    account_id = (event.get("recipient") or {}).get("id")
    customer_id = (event.get("sender") or {}).get("id")
    if not all(isinstance(value, str) and 0 < len(value) <= 100 for value in (account_id, customer_id)):
        raise ValueError("invalid_instagram_participants")
    # Bind only from the signed provider account + trusted DB mapping. Ignore
    # any seller_id or tenant field in the event. Reject ambiguous bindings.
    sellers = (await db.execute(select(Seller).where(
        Seller.instagram_page_id == account_id, Seller.is_active.is_(True),
    ).limit(2))).scalars().all()
    if not sellers:
        return None
    if len(sellers) != 1:
        raise ValueError("ambiguous_instagram_account")
    key = event_key(event, events)
    now = datetime.now(timezone.utc)
    await db.execute(insert(InstagramIngress).values(
        id=uuid4(), seller_id=sellers[0].id, account_id=account_id, customer_id=customer_id,
        event_key=key, provider_message_id=(event.get("message") or {}).get("mid"),
        events=events, status="pending", attempts=0, available_at=now + timedelta(seconds=BATCH_SECONDS),
    ).on_conflict_do_nothing(constraint="instagram_ingress_event_once"))
    receipt = await db.scalar(select(InstagramIngress).where(
        InstagramIngress.account_id == account_id, InstagramIngress.event_key == key,
    ))
    # Explicit commit BEFORE optional broker dispatch or HTTP/SQS acknowledgement.
    await db.commit()
    return receipt


async def replay_receipt(db, receipt_id, seller_id, *, side_effects_reviewed: bool = False) -> bool:
    """Operator service seam; caller must authorize seller access.

    Errors may follow an external send whose DB commit failed. Require an explicit
    review before replay. No public endpoint or blind automatic retry is exposed.
    """
    row = await db.scalar(select(InstagramIngress).where(
        InstagramIngress.id == receipt_id, InstagramIngress.seller_id == seller_id,
    ).with_for_update())
    if row is None or row.status != "error":
        return False
    if row.error_code in UNKNOWN_EFFECT_ERRORS and not side_effects_reviewed:
        raise ValueError("side_effect_review_required")
    seller = await db.scalar(select(Seller).where(
        Seller.id == row.seller_id, Seller.instagram_page_id == row.account_id, Seller.is_active.is_(True),
    ))
    if seller is None:
        raise ValueError("instagram_account_binding_changed")
    row.status, row.error_code = "retry", None
    row.available_at = datetime.now(timezone.utc)
    row.started_at = row.finished_at = None
    await db.flush()
    return True
