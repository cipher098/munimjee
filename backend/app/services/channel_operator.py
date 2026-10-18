"""Current-membership, tenant-scoped operator decisions; no customer sends here."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.channel_operator import ChannelConnectionState, ChannelOperation
from app.models.identity import Business, Membership, User
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.identity import Actor, BusinessAccess, capabilities_for, require_business_access
from app.services.instagram_ingress import UNKNOWN_EFFECT_ERRORS, replay_receipt, resolve_receipt_without_replay

STATUSES = {"pending", "retry", "processing", "completed", "error", "resolved"}
REASONS = {
    "processing_failed_unknown_effect": "Processing stopped after a reply may have been sent.",
    "processing_interrupted_unknown_effect": "The worker stopped before its result was saved. A reply may have been sent.",
    "legacy_cutover_review_required": "This message came from the older queue. Check Instagram before deciding whether to try again.",
    "legacy_snapshot_unidentified": "The older queue needs a stable transfer identity before this item can be reviewed.",
    "legacy_identity_unverifiable": "The older queue could not establish this message's identity.",
    "instagram_account_binding_changed": "The connected Instagram account changed before processing.",
    "provider_window_unverified": "A current customer messaging window could not be established. Review in Instagram and close without replay.",
    "authoritative_catalogue_handoff": "This product now uses the SKU catalogue. A person must confirm current options, price and availability.",
    "operator_replay_withheld": "The reviewed retry no longer passes the current reply checks.",
    "reviewed_without_replay": "A seller reviewed this item and closed it without another attempt.",
    "legacy_snapshot_transferred": "The older queue snapshot was transferred into individually tracked items.",
}


def now():
    return datetime.now(timezone.utc)


async def lock_tenant_rows(db, business_id, *, require_business=True):
    """Canonical Business -> Seller order, without creating legacy identities."""
    with db.no_autoflush:
        business = await db.scalar(select(Business).where(Business.id == business_id)
            .with_for_update(key_share=True).execution_options(populate_existing=True))
        seller = await db.scalar(select(Seller).where(Seller.id == business_id, Seller.is_active.is_(True))
            .with_for_update(key_share=True).execution_options(populate_existing=True))
    if seller is None or require_business and (business is None or not business.is_active):
        raise HTTPException(404, "Business not found")
    return business, seller


async def locked_access(db, actor: Actor, business_id: UUID, capability: str) -> BusinessAccess:
    # Explicit tenant ordering matches credential import/legacy writers; never
    # rely on a join planner's row-lock order across Business and Seller.
    await require_business_access(db, actor, business_id, capability)
    await lock_tenant_rows(db, business_id)
    row = (await db.execute(select(Business, Membership, Seller, User).join(
        Membership, Membership.business_id == Business.id).join(Seller, Seller.id == Business.id).join(
        User, User.id == Membership.user_id).where(
            Business.id == business_id, User.id == actor.user_id, User.is_active.is_(True), User.revoked_at.is_(None),
            Membership.is_active.is_(True), Membership.revoked_at.is_(None),
            Business.is_active.is_(True), Seller.is_active.is_(True),
        ).with_for_update(key_share=True, of=(Membership, User)).execution_options(populate_existing=True))).one_or_none()
    if row is None:
        raise HTTPException(404, "Business not found")
    access = BusinessAccess(*row[:3], authorized_role=row[1].role)
    if capability not in access.capabilities:
        raise HTTPException(403, "Your role cannot perform this action")
    return access


async def begin_operation(db, actor, business_id, key, action, payload, *, resource_id=None, reason=""):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), encoded, hashlib.sha256).hexdigest()
    await db.execute(insert(ChannelOperation).values(
        id=uuid4(), business_id=business_id, actor_user_id=actor.user_id, idempotency_key=key,
        action=action, resource_id=resource_id, request_hash=digest, reason=reason, outcome={},
    ).on_conflict_do_nothing(constraint="channel_operation_idempotency"))
    operation = await db.scalar(select(ChannelOperation).where(
        ChannelOperation.business_id == business_id, ChannelOperation.idempotency_key == key,
    ).with_for_update())
    if operation.actor_user_id != actor.user_id or operation.action != action or operation.request_hash != digest:
        raise HTTPException(409, "This action key was already used for a different request")
    return operation


async def receipt_for(db, business_id, receipt_id, *, lock=False):
    query = select(InstagramIngress).where(InstagramIngress.seller_id == business_id, InstagramIngress.id == receipt_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "Message item not found")
    return row


def receipt_view(row, *, detail=False):
    kinds = [item.get("type", "unknown") for item in row.events]
    texts = [item.get("text", "") for item in row.events if item.get("type") == "text"]
    result = {"id": str(row.id), "customer_ref": row.customer_id[-6:], "status": row.status,
              "reason_code": row.error_code, "reason": REASONS.get(row.error_code, "Waiting for processing." if row.status in {"pending", "retry"} else "No review needed."),
              "created_at": row.created_at.isoformat(), "updated_at": (row.updated_at or row.created_at).isoformat(),
              "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
              "kinds": kinds, "message_preview": "\n".join(texts)[:160], "attempts": row.attempts,
              "handled_components": len(row.processed_indices or []), "total_components": len(row.events),
              "delivery_confirmed": False}
    if detail:
        result["components"] = [{"kind": item.get("type", "unknown"), "text": item.get("text", "")[:2000],
                                  "handled": index in (row.processed_indices or [])} for index, item in enumerate(row.events)]
    return result


async def list_receipts(db, actor, business_id, *, status="error", limit=25, cursor=None):
    await require_business_access(db, actor, business_id, "inbox.read")
    if status != "all" and status not in STATUSES:
        raise HTTPException(422, "Unknown message status")
    filters = [InstagramIngress.seller_id == business_id]
    if status != "all":
        filters.append(InstagramIngress.status == status)
    if cursor:
        try:
            data = jwt.decode(cursor, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            if data.get("purpose") != "channel_cursor" or data.get("business") != str(business_id) or data.get("status") != status:
                raise ValueError()
            timestamp, identifier = datetime.fromisoformat(data["time"]), UUID(data["id"])
            filters.append(or_(InstagramIngress.created_at < timestamp,
                               and_(InstagramIngress.created_at == timestamp, InstagramIngress.id < identifier)))
        except (JWTError, ValueError, KeyError, TypeError):
            raise HTTPException(400, "This page link expired. Refresh the list.")
    rows = (await db.execute(select(InstagramIngress).where(*filters).order_by(
        InstagramIngress.created_at.desc(), InstagramIngress.id.desc()).limit(limit + 1))).scalars().all()
    token = None
    if len(rows) > limit:
        last = rows[limit - 1]
        token = jwt.encode({"purpose": "channel_cursor", "business": str(business_id), "status": status,
                            "time": last.created_at.isoformat(), "id": str(last.id), "exp": now() + timedelta(hours=1)},
                           settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return {"items": [receipt_view(row) for row in rows[:limit]], "next_cursor": token}


async def replay_block_reason(db, row, *, actor_id=None):
    seller = await db.get(Seller, row.seller_id)
    if not seller or not seller.is_active or seller.instagram_page_id != row.account_id or not seller.instagram_token:
        return "Reconnect this Instagram account before trying again."
    if seller.instagram_token_expires_at and seller.instagram_token_expires_at <= now():
        return "Reconnect Instagram: its saved authorization has expired."
    if not row.occurred_at or row.occurred_at > now() + timedelta(minutes=5) or row.occurred_at < now() - timedelta(hours=24):
        return "A recent customer message time could not be established. Review in Instagram and close this item without replay."
    if row.error_code == "legacy_snapshot_unidentified":
        return "The older Redis queue must be transferred into tracked items first."
    control = await db.get(ChannelConnectionState, (row.seller_id, "instagram"))
    if not control or control.check_status != "verified" or not control.checked_at or control.checked_at < now() - timedelta(hours=24):
        return "Run a current Instagram connection check before requesting a retry."
    from app.services.channel_readiness import instagram_automation_enabled
    if not await instagram_automation_enabled(db, row.seller_id):
        return "Instagram automation is paused. Check its connection before enabling it."
    blocked = await db.scalar(select(InstagramIngress.id).where(
        InstagramIngress.seller_id == row.seller_id, InstagramIngress.customer_id == row.customer_id,
        InstagramIngress.id != row.id,
        or_(InstagramIngress.status == "processing", and_(InstagramIngress.status == "error", InstagramIngress.error_code.in_(UNKNOWN_EFFECT_ERRORS))),
    ).limit(1))
    if blocked:
        return "Review the other held items in this conversation before retrying this one."
    from app.models.conversation import Conversation
    from app.models.manual_action import ManualAction
    conversation = await db.scalar(select(Conversation).where(Conversation.seller_id == row.seller_id,
                                                              Conversation.customer_instagram_id == row.customer_id))
    if conversation:
        if conversation.product_id:
            from app.services.checkout_v1 import is_product_activated
            if await is_product_activated(db, row.seller_id, conversation.product_id):
                return "This product uses the SKU catalogue. A person must confirm current product facts; automatic replay is unavailable."
        if conversation.last_seller_manual_reply_at and conversation.last_seller_manual_reply_at > now() - timedelta(minutes=settings.BOT_AUTO_RESUME_AFTER_MINUTES):
            return "A person has taken over this conversation. Wait for takeover to end."
        if conversation.disengage_paused_until and conversation.disengage_paused_until > now():
            return "This conversation is paused after the customer disengaged."
        if await db.scalar(select(ManualAction.id).where(ManualAction.conversation_id == conversation.id, ManualAction.status == "open").limit(1)):
            return "An open manual action needs a human response first."
    if actor_id is not None:
        membership = (await db.execute(select(Membership, User).join(User, User.id == Membership.user_id).join(
            Business, Business.id == Membership.business_id).where(
            Membership.business_id == row.seller_id, Membership.user_id == actor_id,
            Membership.is_active.is_(True), Membership.revoked_at.is_(None), User.is_active.is_(True), User.revoked_at.is_(None),
            Business.is_active.is_(True),
        ))).one_or_none()
        if membership is None or "automation.manage" not in capabilities_for(membership[0].role):
            return "The reviewer no longer has permission to resume automation."
    return None


async def review_receipt(db, actor, business_id, receipt_id, payload):
    # Match the durable worker's receipt -> seller lock order. Authorize a
    # scoped read before locking; recheck current mutation rights under locks.
    await require_business_access(db, actor, business_id, "automation.manage")
    row = await receipt_for(db, business_id, receipt_id, lock=True)
    await locked_access(db, actor, business_id, "automation.manage")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key,
                                      "ingress_" + payload.decision, payload.model_dump(), resource_id=receipt_id, reason=payload.reason)
    if operation.outcome:
        return operation.outcome
    if not payload.reviewed:
        raise HTTPException(422, "Confirm that you checked whether the earlier reply was sent")
    if row.status != "error":
        raise HTTPException(409, "This item is no longer awaiting review. Refresh its status.")
    if (row.updated_at or row.created_at) != payload.expected_updated_at:
        raise HTTPException(409, "This item changed while you were reviewing it. Refresh before deciding.")
    operation.before_status = row.status
    try:
        if payload.decision == "replay":
            blocked = await replay_block_reason(db, row, actor_id=actor.user_id)
            if blocked:
                raise HTTPException(409, blocked)
            await replay_receipt(db, row.id, business_id, side_effects_reviewed=True)
            row.operator_replay_pending = True
        else:
            await resolve_receipt_without_replay(db, row.id, business_id, side_effects_reviewed=True)
    except ValueError:
        raise HTTPException(409, "The older queue must be transferred into tracked items before it can be reviewed")
    operation.after_status = row.status
    operation.outcome = {"operation_id": str(operation.id), "receipt_id": str(row.id), "status": row.status,
                         "delivery_confirmed": False, "queued": payload.decision == "replay",
                         "message": "Queued for current reply checks. Delivery is not confirmed." if payload.decision == "replay" else "Closed after review. No new reply was requested; delivery is not confirmed."}
    await db.flush()
    return operation.outcome
