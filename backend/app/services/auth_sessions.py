"""Native-session validity and guarded legacy compatibility, independent of routes."""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from uuid import UUID, uuid4
from fastapi import HTTPException, Request, Response
from jose import JWTError, jwt
from sqlalchemy import select, update
from app.config import settings
from app.models.identity import User
from app.models.identity_auth import UserSession
from app.services.identity import Actor, resolve_legacy_owner, resolve_user_actor

SESSION_DAYS = 7
AUTH_COOKIES = ("v1_session", "v1_csrf", "dashboard_session", "seller_session", "view_seller")


def now_utc():
    return datetime.now(timezone.utc)


def secret_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def decode_native_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                            options={"require_exp": True, "require_sub": True})
        if claims.get("role") != "v1_user" or claims.get("purpose") != "v1_actor":
            raise ValueError("Native login required")
        UUID(claims["sub"])
        UUID(claims["sid"])
        return claims
    except (JWTError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(status_code=401, detail="Native login required")


def request_auth_token(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise HTTPException(status_code=401, detail="Login required")
        return value
    return (request.cookies.get("v1_session") or request.cookies.get("dashboard_session")
            or request.cookies.get("seller_session") or "")


@dataclass(frozen=True)
class NativeSession:
    actor: Actor
    user: User
    session: UserSession


async def native_session(db, token: str) -> NativeSession:
    claims = decode_native_token(token)
    actor = await resolve_user_actor(db, UUID(claims["sub"]), "v1_user")
    user = await db.get(User, actor.user_id)
    session = await db.scalar(select(UserSession).join(User, User.id == UserSession.user_id).where(
        UserSession.id == UUID(claims["sid"]), UserSession.user_id == actor.user_id,
        UserSession.revoked_at.is_(None), UserSession.expires_at > now_utc(),
        UserSession.auth_version == User.auth_version, User.is_active.is_(True),
        User.revoked_at.is_(None)).execution_options(autoflush=False))
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    return NativeSession(actor, user, session)


async def issue_session(db, user: User) -> tuple[str, str, UserSession]:
    version = await db.scalar(select(User.auth_version).where(User.id == user.id,
        User.is_active.is_(True), User.revoked_at.is_(None)).execution_options(autoflush=False))
    if version is None:
        raise HTTPException(status_code=401, detail="Active user login required")
    csrf = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=SESSION_DAYS)
    session = UserSession(id=uuid4(), user_id=user.id, auth_version=version,
                          csrf_digest=secret_digest(csrf), expires_at=expires)
    db.add(session)
    await db.flush()
    token = jwt.encode({"sub": str(user.id), "sid": str(session.id), "role": "v1_user",
                        "purpose": "v1_actor", "iat": now_utc().timestamp(), "exp": expires},
                       settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, csrf, session


def clear_auth_cookies(response: Response) -> None:
    for name in AUTH_COOKIES:
        response.delete_cookie(name, path="/")
    response.delete_cookie("instagram_oauth_browser", path="/auth/instagram/oauth")


def set_native_cookies(response: Response, request: Request, token: str, csrf: str) -> None:
    clear_auth_cookies(response)
    secure = request.url.scheme == "https" or settings.PUBLIC_BASE_URL.startswith("https://")
    response.set_cookie("v1_session", token, httponly=True, secure=secure, samesite="lax",
                        max_age=SESSION_DAYS * 86400, path="/")
    response.set_cookie("v1_csrf", csrf, httponly=False, secure=secure, samesite="lax",
                        max_age=SESSION_DAYS * 86400, path="/")


async def revoke_browser_session(db, request: Request) -> None:
    """Switch/logout cleans up the previous native cookie identity, not bearer input."""
    token = request.cookies.get("v1_session")
    if not token:
        return
    try:
        claims = decode_native_token(token)
    except HTTPException:
        return
    await db.execute(update(UserSession).where(UserSession.id == UUID(claims["sid"]),
        UserSession.user_id == UUID(claims["sub"]), UserSession.revoked_at.is_(None)).values(revoked_at=now_utc()))


async def revoke_all_sessions(db, user: User) -> None:
    from sqlalchemy.orm.attributes import set_committed_value
    current = (await db.execute(update(User).where(User.id == user.id).values(
        auth_version=User.auth_version + 1, legacy_revoked_before=now_utc()).returning(
        User.auth_version, User.legacy_revoked_before).execution_options(synchronize_session=False))).one()
    set_committed_value(user, "auth_version", current.auth_version)
    set_committed_value(user, "legacy_revoked_before", current.legacy_revoked_before)
    await db.execute(update(UserSession).where(UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None)).values(revoked_at=now_utc()))
    await db.flush()


async def enforce_legacy_owner_access(db, seller_id: UUID, claims: dict) -> None:
    if not settings.V1_ENFORCE_LEGACY_ACCESS:
        return
    actor = await resolve_legacy_owner(db, seller_id)
    cutoff = await db.scalar(select(User.legacy_revoked_before).where(User.id == actor.user_id)
        .execution_options(autoflush=False))
    issued = claims.get("iat")
    if cutoff is not None and (type(issued) not in (int, float) or not isfinite(issued)
                              or issued < cutoff.timestamp() or issued > now_utc().timestamp() + 5):
        raise HTTPException(status_code=401, detail="Legacy session revoked; sign in again")
