"""Cookie-based auth for the dashboard.

Two roles:
  - seller: logs in with email OR whatsapp_number + their account password; scoped to their
            own seller_id.
  - admin : logs in with a phone in DASHBOARD_ALLOWED_PHONES + DASHBOARD_PASSWORD; can list
            all sellers and "view as" any seller (a `view_seller` cookie scopes the seller
            pages to that seller).
"""
from app.paths import STATIC_DIR as _STATIC_DIR

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import _verify_password, _secure_cookie
from app.config import settings
from app.database import get_db
from app.models.seller import Seller

router = APIRouter(prefix="/dashboard-auth", tags=["dashboard-auth"])

_COOKIE = "dashboard_session"
_VIEW_COOKIE = "view_seller"
_EXPIRE_DAYS = 30


@dataclass
class DashCtx:
    role: str                      # "seller" | "admin"
    seller_id: str | None          # the seller's own id (seller role)
    view_seller_id: str | None     # the seller an admin is currently viewing (admin role)


def _make_token(role: str, seller_id: str | None, sub: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=_EXPIRE_DAYS)
    return jwt.encode(
        {"role": role, "seller_id": seller_id, "sub": sub, "iat": datetime.now(timezone.utc).timestamp(), "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _redirect_login() -> HTTPException:
    return HTTPException(status_code=302, headers={"Location": "/dashboard-auth/login"})


async def verify_dashboard_cookie(
    dashboard_session: str | None = Cookie(default=None),
    view_seller: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> DashCtx:
    """Auth gate for every dashboard route. Returns the caller's role + ids."""
    if not dashboard_session:
        raise _redirect_login()
    try:
        payload = jwt.decode(
            dashboard_session, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        raise _redirect_login()
    role = payload.get("role")
    if role not in ("seller", "admin"):
        raise _redirect_login()
    if role == "seller":
        try:
            seller_id = UUID(payload.get("seller_id") or "")
        except (ValueError, TypeError):
            raise _redirect_login()
        seller = await db.get(Seller, seller_id)
        if seller is None or not seller.is_active:
            raise _redirect_login()
        from app.services.auth_sessions import enforce_legacy_owner_access
        await enforce_legacy_owner_access(db, seller_id, payload)
    if role == "admin" and view_seller and settings.V1_ENFORCE_LEGACY_ACCESS:
        raise HTTPException(status_code=403, detail="An explicit support grant is required")
    return DashCtx(
        role=role,
        seller_id=payload.get("seller_id"),
        view_seller_id=(view_seller if role == "admin" else None),
    )


def current_seller_id(ctx: DashCtx = Depends(verify_dashboard_cookie)) -> str:
    """The effective seller for seller-scoped routes: the seller's own id, or the seller an
    admin is currently viewing. 400 if an admin hasn't picked a seller yet."""
    if ctx.role == "seller" and ctx.seller_id:
        return ctx.seller_id
    if ctx.role == "admin" and ctx.view_seller_id:
        return ctx.view_seller_id
    raise HTTPException(status_code=400, detail="No seller selected")


def require_admin(ctx: DashCtx = Depends(verify_dashboard_cookie)) -> DashCtx:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return ctx


@router.get("/login")
async def login_page():
    return FileResponse(_STATIC_DIR / "dashboard_login.html")


@router.post("/login")
async def do_login(
    request: Request,
    identifier: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ident = (identifier or "").strip()
    phone_norm = ident.replace(" ", "").replace("+91", "")

    # 1) Seller login — email or whatsapp_number + their account password.
    res = await db.execute(
        select(Seller).where(
            or_(
                Seller.email == ident,
                Seller.whatsapp_number == ident,
                Seller.whatsapp_number == phone_norm,
            )
        )
    )
    seller = res.scalars().first()
    if seller and seller.password_hash and _verify_password(password, seller.password_hash):
        if not seller.is_active:
            raise HTTPException(status_code=403, detail="Account inactive")
        from app.services.auth_sessions import revoke_browser_session
        await revoke_browser_session(db, request)
        await db.commit()
        token = _make_token("seller", str(seller.id), seller.email or str(seller.id))
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.set_cookie(_COOKIE, token, max_age=_EXPIRE_DAYS * 86400, httponly=True, secure=_secure_cookie(request), samesite="lax")
        resp.delete_cookie(_VIEW_COOKIE)
        resp.delete_cookie("v1_session")
        resp.delete_cookie("v1_csrf")
        resp.delete_cookie("seller_session")
        return resp

    # 2) Admin login — allowed phone + shared dashboard password.
    admin_password = settings.DASHBOARD_PASSWORD
    configured_admin = bool(admin_password and admin_password.strip().casefold() != "changeme" and admin_password.strip())
    if configured_admin and phone_norm in settings.DASHBOARD_ALLOWED_PHONES and password == admin_password:
        from app.services.auth_sessions import revoke_browser_session
        await revoke_browser_session(db, request)
        await db.commit()
        token = _make_token("admin", None, phone_norm)
        resp = RedirectResponse(url="/dashboard/admin", status_code=303)
        resp.set_cookie(_COOKIE, token, max_age=_EXPIRE_DAYS * 86400, httponly=True, secure=_secure_cookie(request), samesite="lax")
        resp.delete_cookie(_VIEW_COOKIE)
        resp.delete_cookie("v1_session")
        resp.delete_cookie("v1_csrf")
        resp.delete_cookie("seller_session")
        return resp

    raise HTTPException(status_code=403, detail="Invalid email/phone or password")


@router.get("/me")
async def me(ctx: DashCtx = Depends(verify_dashboard_cookie), db: AsyncSession = Depends(get_db)):
    """Used by the dashboard pages to learn the role + which seller they're scoped to."""
    out = {"role": ctx.role, "seller_id": None, "business_name": None, "viewing": False}
    sid = ctx.seller_id if ctx.role == "seller" else ctx.view_seller_id
    if ctx.role == "admin" and ctx.view_seller_id:
        out["viewing"] = True
    if sid:
        s = await db.get(Seller, sid)
        out["seller_id"] = str(sid)
        out["business_name"] = (s.business_name or s.email) if s else None
    return out


@router.post("/view/{seller_id}")
async def view_seller(seller_id: str, request: Request, ctx: DashCtx = Depends(require_admin)):
    """Admin picks a seller to view — scopes the seller pages to them."""
    if settings.V1_ENFORCE_LEGACY_ACCESS:
        raise HTTPException(status_code=403, detail="An explicit support grant is required")
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie(_VIEW_COOKIE, seller_id, max_age=_EXPIRE_DAYS * 86400, httponly=True, secure=_secure_cookie(request), samesite="lax")
    return resp


@router.get("/exit-view")
async def exit_view(ctx: DashCtx = Depends(require_admin)):
    resp = RedirectResponse(url="/dashboard/admin", status_code=303)
    resp.delete_cookie(_VIEW_COOKIE)
    return resp


@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    from app.services.auth_sessions import revoke_browser_session, clear_auth_cookies
    await revoke_browser_session(db, request)
    await db.commit()
    resp = RedirectResponse(url="/dashboard-auth/login", status_code=303)
    clear_auth_cookies(resp)
    resp.delete_cookie(_COOKIE)
    resp.delete_cookie(_VIEW_COOKIE)
    resp.delete_cookie("seller_session")
    resp.delete_cookie("instagram_oauth_browser", path="/auth/instagram/oauth")
    return resp
