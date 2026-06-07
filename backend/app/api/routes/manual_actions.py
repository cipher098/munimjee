"""Manual-action queue — post-payment change requests (refund / cancellation / item-change)
the bot escalated to the seller. While an action is `open` the bot stays silent on that chat;
resolving it here un-mutes the bot."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import verify_dashboard_cookie
from app.database import get_db
from app.models.conversation import Conversation
from app.models.manual_action import ManualAction

logger = logging.getLogger(__name__)

SELLER_ID = "ac2303e0-00f3-4470-98ca-36a8f4ae5866"

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
async def list_manual_actions(status: str = "open", db: AsyncSession = Depends(get_db)):
    """List manual actions for the seller (default: open ones), newest first, each with the
    customer name and a short preview so the seller knows what action is required."""
    rows = (await db.execute(
        select(ManualAction, Conversation)
        .join(Conversation, ManualAction.conversation_id == Conversation.id)
        .where(ManualAction.seller_id == SELLER_ID, ManualAction.status == status)
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
async def manual_action_chat(action_id: str, db: AsyncSession = Depends(get_db)):
    """Full conversation transcript for a manual action so the seller can read the chat."""
    ma = await db.get(ManualAction, action_id)
    if ma is None or str(ma.seller_id) != SELLER_ID:
        raise HTTPException(status_code=404, detail="Manual action not found")
    conv = await db.get(Conversation, ma.conversation_id)
    msgs = (conv.messages or []) if conv else []
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
            }
            for m in msgs
        ],
    }


@router.post("/{action_id}/resolve")
async def resolve_manual_action(action_id: str, db: AsyncSession = Depends(get_db)):
    """Mark the manual action resolved — un-mutes the bot for that conversation."""
    ma = await db.get(ManualAction, action_id)
    if ma is None or str(ma.seller_id) != SELLER_ID:
        raise HTTPException(status_code=404, detail="Manual action not found")
    if ma.status != "resolved":
        ma.status = "resolved"
        ma.resolved_at = datetime.now(timezone.utc)
        await db.flush()
    return {"id": str(ma.id), "status": ma.status}
