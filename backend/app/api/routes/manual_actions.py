"""Manual-action queue — post-payment change requests (refund / cancellation / item-change)
the bot escalated to the seller. While an action is `open` the bot stays silent on that chat;
resolving it here un-mutes the bot."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import verify_dashboard_cookie, current_seller_id
from app.database import get_db
from app.models.conversation import Conversation
from app.models.manual_action import ManualAction

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/manual-actions",
    tags=["manual-actions"],
    dependencies=[Depends(verify_dashboard_cookie)],
)

_KIND_LABEL = {
    "refund": "Refund request",
    "cancellation": "Cancellation",
    "item_change": "Item change / exchange",
    "other": "Needs review",
}


@router.get("")
async def list_manual_actions(status: str = "open", seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """List manual actions for the seller (default: open ones), newest first, each with the
    customer name and a short preview so the seller knows what action is required."""
    rows = (await db.execute(
        select(ManualAction, Conversation)
        .join(Conversation, ManualAction.conversation_id == Conversation.id)
        .where(ManualAction.seller_id == seller_id, ManualAction.status == status)
        .order_by(ManualAction.created_at.desc())
    )).all()
    out = []
    for ma, conv in rows:
        out.append({
            "id": str(ma.id),
            "conversation_id": str(ma.conversation_id),
            "customer_name": conv.customer_name or conv.customer_instagram_id,
            "kind": ma.kind,
            "kind_label": _KIND_LABEL.get(ma.kind, ma.kind),
            "detail": ma.detail,
            "status": ma.status,
            "created_at": ma.created_at.isoformat() if ma.created_at else None,
            "resolved_at": ma.resolved_at.isoformat() if ma.resolved_at else None,
        })
    return out


@router.get("/{action_id}/chat")
async def manual_action_chat(action_id: str, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """Full conversation transcript for a manual action so the seller can read the chat."""
    ma = await db.get(ManualAction, action_id)
    if ma is None or str(ma.seller_id) != seller_id:
        raise HTTPException(status_code=404, detail="Manual action not found")
    conv = await db.get(Conversation, ma.conversation_id)
    msgs = (conv.messages or []) if conv else []

    # Resolve renderable image URLs so the transcript shows actual images, not just text
    # markers: product photos via product_id, the payment QR via the seller's UPI method,
    # and customer screenshots from the URL embedded in the marker (best-effort).
    import re as _re
    from app.bot.conversation import _get_primary_upi_method
    from app.models.product import Product

    pids = {m.get("product_id") for m in msgs if m.get("content") == "[product photo]" and m.get("product_id")}
    photo_by_pid = {}
    if pids:
        prows = (await db.execute(select(Product).where(Product.id.in_(list(pids))))).scalars().all()
        photo_by_pid = {str(p.id): p.photo_url for p in prows}
    _method = await _get_primary_upi_method(ma.seller_id, db)
    qr_url = _method.qr_code_url if _method else None

    def _image_url(m: dict):
        c = m.get("content") or ""
        if c == "[product photo]" and m.get("product_id"):
            return photo_by_pid.get(str(m.get("product_id")))
        if c == "[payment QR]":
            return qr_url
        mm = _re.match(r"\[screenshot:\s*(\S+?)\s*\]", c)
        if mm:
            return mm.group(1)
        return None

    return {
        "id": str(ma.id),
        "conversation_id": str(ma.conversation_id),
        "customer_name": (conv.customer_name or conv.customer_instagram_id) if conv else None,
        "kind": ma.kind,
        "kind_label": _KIND_LABEL.get(ma.kind, ma.kind),
        "detail": ma.detail,
        "status": ma.status,
        "messages": [
            {
                "role": m.get("role"),
                "content": m.get("content"),
                "timestamp": m.get("timestamp"),
                "image_url": _image_url(m),
            }
            for m in msgs
        ],
    }


@router.post("/{action_id}/resolve")
async def resolve_manual_action(action_id: str, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """Mark the manual action resolved — un-mutes the bot for that conversation."""
    ma = await db.get(ManualAction, action_id)
    if ma is None or str(ma.seller_id) != seller_id:
        raise HTTPException(status_code=404, detail="Manual action not found")
    if ma.status != "resolved":
        ma.status = "resolved"
        ma.resolved_at = datetime.now(timezone.utc)
        # Mark everything so far as handled: append a seller boundary so the customer
        # messages that triggered/accumulated during the manual action are no longer
        # "unanswered" and the bot won't re-escalate the same (now-handled) request on the
        # customer's next message.
        conv = await db.get(Conversation, ma.conversation_id)
        if conv is not None:
            msgs = list(conv.messages or [])
            msgs.append({
                "role": "seller_manual",
                "content": f"[Seller resolved the {ma.kind.replace('_', ' ')} request manually]",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            conv.messages = msgs
        await db.flush()
    return {"id": str(ma.id), "status": ma.status}
