"""Normalize, commit and replay inbound IG messages; Redis is only a wake-up hint."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller

BATCH_SECONDS = 20
PROCESSING_TIMEOUT_SECONDS = 15 * 60
UNKNOWN_EFFECT_ERRORS = {"processing_failed_unknown_effect", "processing_interrupted_unknown_effect", "legacy_identity_unverifiable", "legacy_cutover_review_required"}


def validate_message_shape(event: dict) -> None:
    """Reject malformed nested structures before handlers or persistence use them."""
    if not isinstance(event, dict):
        raise ValueError("invalid_instagram_event")
    for key in ("sender", "recipient", "message"):
        if event.get(key) is not None and not isinstance(event[key], dict):
            raise ValueError("invalid_instagram_event")
    for key in ("sender", "recipient"):
        value = (event.get(key) or {}).get("id")
        if value is not None and (not isinstance(value, str) or not 0 < len(value) <= 100):
            raise ValueError("invalid_instagram_participants")
    message = event.get("message") or {}
    if message.get("is_echo") is not None and not isinstance(message["is_echo"], bool):
        raise ValueError("invalid_instagram_message")
    if message.get("reply_to") is not None and not isinstance(message["reply_to"], dict):
        raise ValueError("invalid_instagram_reply")
    attachments = message.get("attachments")
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list):
        raise ValueError("invalid_instagram_attachments")
    for attachment in attachments:
        if not isinstance(attachment, dict) or (attachment.get("payload") is not None and not isinstance(attachment["payload"], dict)):
            raise ValueError("invalid_instagram_attachment")
        if attachment.get("type") is not None and not isinstance(attachment["type"], str):
            raise ValueError("invalid_instagram_attachment")
        for field in ("url", "link", "title", "reel_video_id"):
            value = (attachment.get("payload") or {}).get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError("invalid_instagram_attachment")
    for field in ("text", "mid"):
        if message.get(field) is not None and not isinstance(message[field], str):
            raise ValueError("invalid_instagram_message")
    reply_mid = (message.get("reply_to") or {}).get("mid")
    if reply_mid is not None and not isinstance(reply_mid, str):
        raise ValueError("invalid_instagram_reply")


async def thread_quarantined(db, seller_id, customer_id: str, *, owned_receipt_ids=()) -> bool:
    """Fence every automatic reply while a prior operation may have sent.

    Processing is included to close the gap between an external-send rollback
    and the separate durable error update. The owning worker may process its IDs.
    """
    processing = InstagramIngress.status == "processing"
    if owned_receipt_ids:
        processing = and_(processing, InstagramIngress.id.not_in(owned_receipt_ids))
    return await db.scalar(select(InstagramIngress.id).where(
        InstagramIngress.seller_id == seller_id, InstagramIngress.customer_id == customer_id,
        or_(processing, and_(InstagramIngress.status == "error", InstagramIngress.error_code.in_(UNKNOWN_EFFECT_ERRORS))),
    ).limit(1)) is not None


def normalize_message(event: dict) -> list[dict]:
    """Keep only fields consumed by the existing processor, never the raw webhook.

    Match legacy attachment precedence: an attachment-bearing message is not also
    processed as text. URLs are needed for media processing, not logged here.
    """
    validate_message_shape(event)
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
        events=events, processed_indices=[], status="pending", attempts=0, available_at=now + timedelta(seconds=BATCH_SECONDS),
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


async def persist_legacy_batch(db, seller, account_id: str, customer_id: str, events: list[dict]) -> int:
    """Transfer old Redis work into the same ledger used by provider receipts.

    No sends occur here. Legacy work is fenced for reviewed cutover because a
    previous worker may already have sent before losing its commit. The caller
    commits before trimming Redis. Provider mids
    dedupe text AND media across both paths. Missing mids cannot be correlated
    after legacy timestamp loss, so retain them for reviewed reconciliation.
    """
    groups = {}
    for position, item in enumerate(events):
        mid = item.get("mid")
        identity = ("mid", mid) if mid else ("unidentified", position)
        groups.setdefault(identity, []).append(item)
    now = datetime.now(timezone.utc)
    for position, ((kind, mid), grouped) in enumerate(groups.items()):
        identity = {"mid": mid} if kind == "mid" else {"legacy_events": grouped}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        uncertain = kind != "mid"
        await db.execute(insert(InstagramIngress).values(
            id=uuid4(), seller_id=seller.id, account_id=account_id, customer_id=customer_id,
            event_key=key, provider_message_id=mid if not uncertain else None,
            events=grouped, processed_indices=[], status="error", attempts=0,
            error_code="legacy_identity_unverifiable" if uncertain else "legacy_cutover_review_required",
            created_at=now + timedelta(microseconds=position), available_at=now,
        ).on_conflict_do_nothing(constraint="instagram_ingress_event_once"))
        row = await db.scalar(select(InstagramIngress).where(
            InstagramIngress.account_id == account_id, InstagramIngress.event_key == key,
        ).with_for_update())
        if row is not None and row.status in {"pending", "retry"}:
            row.status, row.error_code = "error", "legacy_cutover_review_required"
    await db.flush()
    return len(events)


async def resolve_receipt_without_replay(db, receipt_id, seller_id, *, side_effects_reviewed: bool = False) -> bool:
    """Release a reviewed quarantine without sending again (caller authorizes access).

    Use when provider evidence or a human response establishes that replay is not
    wanted. Preserve original payload/progress; resolved is distinct from handled.
    """
    if not side_effects_reviewed:
        raise ValueError("side_effect_review_required")
    row = await db.scalar(select(InstagramIngress).where(
        InstagramIngress.id == receipt_id, InstagramIngress.seller_id == seller_id,
        InstagramIngress.status == "error",
    ).with_for_update())
    if row is None:
        return False
    row.status, row.error_code = "resolved", "reviewed_without_replay"
    row.finished_at = datetime.now(timezone.utc)
    await db.flush()
    return True
