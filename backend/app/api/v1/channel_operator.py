"""Versioned native seller channel operations. Never uses admin impersonation."""
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.channel_operator import ChannelOperation
from app.schemas.channel_operator import Automation, Mutation, Review, WhatsAppConnect
from app.services.identity import Actor, require_business_access
from app.services import channel_connections as connections, channel_operator as service

router = APIRouter(tags=["v1-channels"])
BASE = "/api/v1/businesses/{business_id}/channels"
STATIC = Path(__file__).resolve().parents[3] / "static"


@router.get("/v1/businesses/{business_id}/channels", include_in_schema=False)
async def page(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "inbox.read")
    return FileResponse(STATIC / "channel_operator.html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get(BASE)
async def overview(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await require_business_access(db, actor, business_id, "inbox.read")
    return {"business_id": str(business_id), "business_name": access.business.name,
            "capabilities": sorted(access.capabilities), "channels": await connections.connection_views(db, business_id)}


@router.get(BASE + "/instagram/receipts")
async def receipts(business_id: UUID, status: str = "error", limit: int = Query(25, ge=1, le=100), cursor: str | None = None,
                   actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.list_receipts(db, actor, business_id, status=status, limit=limit, cursor=cursor)


@router.get(BASE + "/instagram/receipts/{receipt_id}")
async def receipt_detail(business_id: UUID, receipt_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await require_business_access(db, actor, business_id, "inbox.read")
    row = await service.receipt_for(db, business_id, receipt_id)
    result = service.receipt_view(row, detail=True)
    result["replay_block_reason"] = await service.replay_block_reason(db, row, actor_id=actor.user_id) if row.status == "error" else "This item is not awaiting review."
    result["can_review"] = "automation.manage" in access.capabilities and row.status == "error" and row.error_code != "legacy_snapshot_unidentified"
    history = (await db.execute(select(ChannelOperation).where(ChannelOperation.business_id == business_id,
                      ChannelOperation.resource_id == receipt_id).order_by(ChannelOperation.created_at.desc()).limit(20))).scalars().all()
    result["history"] = [{"action": item.action, "actor_id": str(item.actor_user_id), "reason": item.reason,
                           "before_status": item.before_status, "after_status": item.after_status,
                           "created_at": item.created_at.isoformat()} for item in history]
    return result


@router.post(BASE + "/instagram/receipts/{receipt_id}/review")
async def review(business_id: UUID, receipt_id: UUID, payload: Review,
                 actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    result = await service.review_receipt(db, actor, business_id, receipt_id, payload)
    await db.commit()
    if result["queued"]:
        row = await service.receipt_for(db, business_id, receipt_id)
        try:
            from app.workers.instagram_ingress import process_instagram_ingress
            process_instagram_ingress.apply_async(args=[str(business_id), row.account_id, row.customer_id])
        except Exception:
            pass  # Committed retry is found by the durable recovery scan.
    return result


@router.post(BASE + "/{channel}/disconnect")
async def disconnect(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Mutation,
                     actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    return await connections.disconnect(db, actor, business_id, channel, payload)


@router.post(BASE + "/{channel}/verify")
async def verify(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Mutation,
                 actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    return await connections.verify(db, actor, business_id, channel, payload)


@router.post(BASE + "/{channel}/automation")
async def automation(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Automation,
                     actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    return await connections.set_automation(db, actor, business_id, channel, payload)


@router.post(BASE + "/whatsapp/connect")
async def whatsapp_connect(business_id: UUID, payload: WhatsAppConnect,
                          actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    return await connections.connect_whatsapp(db, actor, business_id, payload)


@router.post(BASE + "/instagram/connect")
async def instagram_connect(business_id: UUID, payload: Mutation, request: Request, response: Response,
                           actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    result, browser = await connections.start_instagram(db, actor, business_id, payload, request)
    response.set_cookie("v1_ig_link", browser, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or connections.settings.PUBLIC_BASE_URL.startswith("https://"), max_age=600,
                        path=f"/api/v1/businesses/{business_id}/channels/instagram/callback")
    return result


@router.get(BASE + "/instagram/callback", include_in_schema=False)
async def instagram_callback(business_id: UUID, request: Request, state: str | None = None,
                             code: str | None = None, error: str | None = None,
                             actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    result = await connections.finish_instagram(db, actor, business_id, request, signed_state=state, code=code, denied=error)
    await db.commit()
    response = RedirectResponse(f"/v1/businesses/{business_id}/channels?connection={result}", status_code=303)
    response.delete_cookie("v1_ig_link", path=f"/api/v1/businesses/{business_id}/channels/instagram/callback")
    return response
