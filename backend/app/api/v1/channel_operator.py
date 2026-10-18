"""Versioned native seller channel operations. Never uses admin impersonation."""
import re
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
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

def private_response(response: Response):
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"})


router = APIRouter(tags=["v1-channels"], dependencies=[Depends(private_response)])
BASE = "/api/v1/businesses/{business_id}/channels"
STATIC = Path(__file__).resolve().parents[3] / "static"

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


async def native_actor(request: Request, db: AsyncSession = Depends(get_db)):
    if not connections.settings.V1_AUTH_ENABLED:
        raise HTTPException(404, "V1 sign-in is unavailable")
    actor = await current_actor(request, db)
    if actor.auth_method != "v1_user":
        raise HTTPException(401, "Sign in with your own V1 account")
    return actor


async def native_mutation(request: Request, db: AsyncSession = Depends(get_db)):
    actor = await require_v1_mutation(request, db)
    if actor.auth_method != "v1_user":
        raise HTTPException(401, "Sign in with your own V1 account")
    return actor


async def reauthorize(request, db, business_id, actor, capability, *, mutation=False):
    current = await (native_mutation(request, db) if mutation else native_actor(request, db))
    if current != actor:
        raise HTTPException(401, "Your sign-in changed")
    return await require_business_access(db, current, business_id, capability)


def native_read(capability):
    async def guarded(request: Request, business_id: UUID, db: AsyncSession = Depends(get_db)):
        actor = await native_actor(request, db)
        await require_business_access(db, actor, business_id, capability)
        yield actor
        await reauthorize(request, db, business_id, actor, capability)
    return guarded


def acknowledge(result, business_id, payload, action):
    return {**result, "business_id": str(business_id), "idempotency_key": str(payload.idempotency_key), "action": action}


async def finalize(request, db, business_id, actor, capability, *, oauth=False):
    # Flush before the final check: FK/audit lock waits must not occur later
    # during an implicit commit flush after authorization was already checked.
    await db.flush()
    return await reauthorize(request, db, business_id, actor, capability, mutation=not oauth)


@router.get("/v1/businesses/{business_id}/channels", include_in_schema=False)
async def page(business_id: UUID, actor: Actor = Depends(native_read("inbox.read")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "inbox.read")
    return FileResponse(STATIC / "channel_operator.html", headers=PRIVATE_HEADERS)


@router.get(BASE)
async def overview(business_id: UUID, request: Request, actor: Actor = Depends(native_read("inbox.read")), db: AsyncSession = Depends(get_db)):
    channels = await connections.connection_views(db, business_id)
    access = await reauthorize(request, db, business_id, actor, "inbox.read")
    return {"business_id": str(business_id), "business_name": access.business.name,
            "capabilities": sorted(access.capabilities), "channels": channels}


@router.get(BASE + "/instagram/receipts")
async def receipts(business_id: UUID, status: str = "error", limit: int = Query(25, ge=1, le=100), cursor: str | None = None,
                   actor: Actor = Depends(native_read("inbox.read")), db: AsyncSession = Depends(get_db)):
    return await service.list_receipts(db, actor, business_id, status=status, limit=limit, cursor=cursor)


@router.get(BASE + "/instagram/receipts/{receipt_id}")
async def receipt_detail(business_id: UUID, receipt_id: UUID, request: Request, actor: Actor = Depends(native_read("inbox.read")), db: AsyncSession = Depends(get_db)):
    access = await require_business_access(db, actor, business_id, "inbox.read")
    row = await service.receipt_for(db, business_id, receipt_id)
    result = service.receipt_view(row, detail=True)
    result["replay_block_reason"] = await service.replay_block_reason(db, row, actor_id=actor.user_id) if row.status == "error" else "This item is not awaiting review."
    history = (await db.execute(select(ChannelOperation).where(ChannelOperation.business_id == business_id,
                      ChannelOperation.resource_id == receipt_id).order_by(ChannelOperation.created_at.desc()).limit(20))).scalars().all()
    result["history"] = [{"action": item.action, "actor_id": str(item.actor_user_id), "reason": item.reason,
                           "before_status": item.before_status, "after_status": item.after_status,
                           "created_at": item.created_at.isoformat()} for item in history]
    access = await reauthorize(request, db, business_id, actor, "inbox.read")
    result["can_review"] = "automation.manage" in access.capabilities and row.status == "error" and row.error_code != "legacy_snapshot_unidentified"
    return result


@router.post(BASE + "/instagram/receipts/{receipt_id}/review")
async def review(business_id: UUID, receipt_id: UUID, payload: Review, request: Request,
                 actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    result = await service.review_receipt(db, actor, business_id, receipt_id, payload)
    await finalize(request, db, business_id, actor, "automation.manage")
    await db.commit()
    if result["queued"]:
        row = await service.receipt_for(db, business_id, receipt_id)
        try:
            from app.workers.instagram_ingress import process_instagram_ingress
            process_instagram_ingress.apply_async(args=[str(business_id), row.account_id, row.customer_id])
        except Exception:
            pass  # Committed retry is found by the durable recovery scan.
    return acknowledge(result, business_id, payload, "instagram_receipt_review")


@router.post(BASE + "/{channel}/disconnect")
async def disconnect(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Mutation, request: Request,
                     actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    result = await connections.disconnect(db, actor, business_id, channel, payload)
    await finalize(request, db, business_id, actor, "channels.disconnect")
    return acknowledge(result, business_id, payload, "disconnect_" + channel)


@router.post(BASE + "/{channel}/verify")
async def verify(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Mutation, request: Request,
                 actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    result = await connections.verify(db, actor, business_id, channel, payload)
    await finalize(request, db, business_id, actor, "channels.connect")
    return acknowledge(result, business_id, payload, "verify_" + channel)


@router.post(BASE + "/{channel}/automation")
async def automation(business_id: UUID, channel: Literal["instagram", "whatsapp"], payload: Automation, request: Request,
                     actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    result = await connections.set_automation(db, actor, business_id, channel, payload)
    await finalize(request, db, business_id, actor, "automation.manage")
    return acknowledge(result, business_id, payload, "automation_" + channel)


@router.post(BASE + "/whatsapp/connect")
async def whatsapp_connect(business_id: UUID, payload: WhatsAppConnect, request: Request,
                          expected_version: str | None = Header(None, alias="X-Channel-Version"),
                          actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    if expected_version is not None:
        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", expected_version) or int(expected_version) > 2_000_000_000:
            raise HTTPException(422, "Invalid connection version")
        expected_version = int(expected_version)
    result = await connections.connect_whatsapp(db, actor, business_id, payload, expected_version=expected_version)
    await finalize(request, db, business_id, actor, "channels.connect")
    return acknowledge(result, business_id, payload, "connect_whatsapp")


@router.post(BASE + "/instagram/connect")
async def instagram_connect(business_id: UUID, payload: Mutation, request: Request, response: Response,
                           actor: Actor = Depends(native_mutation), db: AsyncSession = Depends(get_db)):
    result, browser = await connections.start_instagram(db, actor, business_id, payload, request)
    await finalize(request, db, business_id, actor, "channels.connect")
    response.set_cookie("v1_ig_link", browser, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or connections.settings.PUBLIC_BASE_URL.startswith("https://"), max_age=600,
                        path=f"/api/v1/businesses/{business_id}/channels/instagram/callback")
    return acknowledge(result, business_id, payload, "start_instagram")


@router.get(BASE + "/instagram/callback", include_in_schema=False)
async def instagram_callback(business_id: UUID, request: Request, state: str | None = None,
                             code: str | None = None, error: str | None = None,
                             actor: Actor = Depends(native_actor), db: AsyncSession = Depends(get_db)):
    async def before_consume():
        await finalize(request, db, business_id, actor, "channels.connect", oauth=True)
    result = await connections.finish_instagram(db, actor, business_id, request, signed_state=state, code=code, denied=error, reauthorize=before_consume)
    await finalize(request, db, business_id, actor, "channels.connect", oauth=True)
    await db.commit()
    response = RedirectResponse(f"/v1/businesses/{business_id}/channels?connection={result}", status_code=303)
    response.delete_cookie("v1_ig_link", path=f"/api/v1/businesses/{business_id}/channels/instagram/callback")
    return response
