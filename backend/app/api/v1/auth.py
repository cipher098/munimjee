"""Native access and resumable onboarding; no legacy seller credentials are minted."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.api.v1.identity import business_view, current_actor
from app.api.v1.session import check_login_origin, require_v1_mutation
from app.models.identity import Membership
from app.models.identity_auth import BusinessInvitation
from app.schemas.identity_auth import (SignupInput, LoginInput, ProfileInput,
    InvitationInput, InvitationAcceptInput, MembershipChangeInput)
from app.services import identity_auth as domain
from app.services.auth_sessions import (clear_auth_cookies, issue_session, native_session,
    now_utc, request_auth_token, revoke_all_sessions, revoke_browser_session,
    secret_digest, set_native_cookies)
from app.services.identity import Actor, accessible_businesses, require_business_access
from app.services.onboarding import onboarding_view, profile_view


def enabled():
    if not settings.V1_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="V1 sign-in is unavailable")


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/v1", tags=["v1-auth"], dependencies=[Depends(enabled), Depends(no_store)])


async def actor_view(db, actor, csrf=None):
    return {"user_id": actor.user_id, "auth_method": actor.auth_method,
        "businesses": [business_view(a) for a in await accessible_businesses(db, actor)],
        "csrf_token": csrf}


async def start_session(db, user, request, response):
    await revoke_browser_session(db, request)
    token, csrf, _ = await issue_session(db, user)
    result = await actor_view(db, Actor(user.id, "v1_user"), csrf)
    await db.commit()
    set_native_cookies(response, request, token, csrf)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/auth/signup", status_code=201)
async def signup(body: SignupInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_login_origin(request)
    try:
        return await start_session(db, await domain.signup(db, body), request, response)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Account already exists; sign in instead")


@router.post("/auth/login")
async def login(body: LoginInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_login_origin(request)
    try:
        return await start_session(db, await domain.authenticate(db, body.email, body.password), request, response)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Account changed; sign in again")


@router.get("/auth/session")
async def session(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    context = await native_session(db, request_auth_token(request))
    csrf = request.cookies.get("v1_csrf", "")
    # Missing/altered CSRF state does not get silently rebound through a GET.
    if not csrf or len(csrf) > 200 or secret_digest(csrf) != context.session.csrf_digest:
        csrf = None
    response.headers["Cache-Control"] = "no-store"
    return await actor_view(db, context.actor, csrf)


@router.post("/auth/logout")
async def logout(request: Request, response: Response, actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    context = await native_session(db, request_auth_token(request))
    context.session.revoked_at = now_utc()
    domain.audit(db, actor.user_id, "session_logout", subject_id=context.session.id)
    await db.commit()
    clear_auth_cookies(response)
    return {"signed_out": True}


@router.post("/auth/logout-all")
async def logout_all(request: Request, response: Response, actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    context = await native_session(db, request_auth_token(request))
    await revoke_all_sessions(db, context.user)
    domain.audit(db, actor.user_id, "all_sessions_revoked")
    await db.commit()
    clear_auth_cookies(response)
    return {"signed_out": True}


@router.post("/auth/invitations/accept")
async def accept_invitation(body: InvitationAcceptInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_login_origin(request)
    try:
        return await start_session(db, await domain.accept_invitation(db, body), request, response)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Account or membership changed; sign in and ask the owner to review access")


@router.get("/businesses/{business_id}/profile")
async def profile(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await require_business_access(db, actor, business_id, "business.read")
    return profile_view(access.business)


@router.put("/businesses/{business_id}/profile")
async def update_profile(business_id: UUID, body: ProfileInput, actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    return profile_view(await domain.save_profile(db, actor, business_id, body))


@router.get("/businesses/{business_id}/onboarding")
async def onboarding(business_id: UUID, request: Request, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    routes = {getattr(route, "path", "").replace("{business_id}", str(business_id)) for route in request.app.routes}
    return await onboarding_view(db, actor, business_id, available_actions=routes)


def invitation_view(row):
    return {"id": row.id, "email": row.auth_email, "role": row.role, "expires_at": row.expires_at,
            "consumed": row.consumed_at is not None, "revoked": row.revoked_at is not None}


@router.post("/businesses/{business_id}/invitations", status_code=201)
async def invite(business_id: UUID, body: InvitationInput, actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    row, token = await domain.create_invitation(db, actor, business_id, body.email, body.role)
    return {**invitation_view(row), "invitation_url": "/v1#invite=" + token}


@router.get("/businesses/{business_id}/invitations")
async def invitations(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "members.manage")
    rows = await db.scalars(select(BusinessInvitation).where(BusinessInvitation.business_id == business_id)
        .order_by(BusinessInvitation.created_at.desc()).limit(100))
    return [invitation_view(row) for row in rows]


@router.delete("/businesses/{business_id}/invitations/{invitation_id}")
async def revoke_invitation(business_id: UUID, invitation_id: UUID, actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "members.manage")
    row = await db.scalar(select(BusinessInvitation).where(BusinessInvitation.id == invitation_id,
        BusinessInvitation.business_id == business_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    row.revoked_at = now_utc()
    domain.audit(db, actor.user_id, "invitation_revoked", business_id=business_id, subject_id=row.id)
    return invitation_view(row)


@router.get("/businesses/{business_id}/members")
async def members(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "members.manage")
    rows = await db.scalars(select(Membership).where(Membership.business_id == business_id).order_by(Membership.created_at).limit(100))
    return [{"id": row.id, "user_id": row.user_id, "role": row.role,
             "active": row.is_active and row.revoked_at is None} for row in rows]


@router.patch("/businesses/{business_id}/members/{membership_id}")
async def change_member(business_id: UUID, membership_id: UUID, body: MembershipChangeInput,
    actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    row = await domain.revoke_membership(db, actor, business_id, membership_id)
    return {"id": row.id, "active": False}
