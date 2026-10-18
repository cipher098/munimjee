"""Shared V1 mutation dependency. All callers still check tenant capabilities."""
import secrets
from urllib.parse import urlsplit
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.services.auth_sessions import native_session, request_auth_token, secret_digest
from app.services.identity import Actor


def allowed_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    sources = [str(request.base_url), settings.PUBLIC_BASE_URL, *settings.BACKEND_CORS_ORIGINS]
    allowed = {f"{part.scheme}://{part.netloc}" for source in sources if source
               and (part := urlsplit(source)).scheme in {"http", "https"} and part.netloc}
    return origin in allowed


def check_login_origin(request: Request) -> None:
    # Nonbrowser API clients may omit Origin. A supplied Origin must be trusted.
    if request.headers.get("origin") is not None and not allowed_origin(request):
        raise HTTPException(status_code=403, detail="Untrusted request origin")


async def require_v1_mutation(request: Request, db: AsyncSession = Depends(get_db)) -> Actor:
    if not settings.V1_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="V1 sign-in is unavailable")
    from app.api.v1.identity import current_actor
    actor = await current_actor(request, db)
    if request.headers.get("authorization") is not None:
        check_login_origin(request)
        return actor
    if actor.auth_method != "v1_user":
        raise HTTPException(status_code=401, detail="Native V1 sign-in required")
    context = await native_session(db, request_auth_token(request))
    cookie = request.cookies.get("v1_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if (not allowed_origin(request) or not cookie or len(cookie) > 200
            or not secrets.compare_digest(cookie, header)
            or not secrets.compare_digest(secret_digest(cookie), context.session.csrf_digest)):
        raise HTTPException(status_code=403, detail="Refresh this page before trying again")
    return actor


def business_mutation(capability: str):
    """Revalidate a native mutation before its caller-owned transaction commits.

    FastAPI 0.111 closes this yield dependency before its get_db dependency.
    Writers used with this guard must not commit internally or send externally.
    A revocation during any awaited row lock therefore rolls back staged facts,
    reservations and outbox rows, even when an older domain helper only checks
    authority before waiting.
    """
    from uuid import UUID
    from app.services.identity import require_business_access

    async def guarded(request: Request, business_id: UUID, db: AsyncSession = Depends(get_db)):
        actor = await require_v1_mutation(request, db)
        await require_business_access(db, actor, business_id, capability)
        yield actor
        # Flush every staged audit/outbox/domain row before the final guard;
        # a revoke during a constraint/row wait must precede this decision.
        await db.flush()
        current = await require_v1_mutation(request, db)
        if current != actor:
            raise HTTPException(401, 'The native session changed')
        await require_business_access(db, current, business_id, capability)

    return guarded
