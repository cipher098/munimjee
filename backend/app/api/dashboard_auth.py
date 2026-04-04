"""Simple cookie-based auth for dashboard routes (product + training)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Form, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from jose import JWTError, jwt

from app.config import settings

router = APIRouter(prefix="/dashboard-auth", tags=["dashboard-auth"])

_COOKIE = "dashboard_session"
_EXPIRE_DAYS = 30


def _make_token(phone: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": phone, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_dashboard_cookie(dashboard_session: str | None = Cookie(default=None)) -> str:
    """FastAPI dependency — call this in any route that needs dashboard auth."""
    if not dashboard_session:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        payload = jwt.decode(
            dashboard_session, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        phone: str = payload.get("sub", "")
        if phone not in settings.DASHBOARD_ALLOWED_PHONES:
            raise HTTPException(status_code=403, detail="Not authorised")
        return phone
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")


@router.get("/login")
async def login_page():
    return FileResponse("/app/static/dashboard_login.html")


@router.post("/login")
async def do_login(
    response: Response,
    phone: str = Form(...),
    password: str = Form(...),
):
    phone = phone.strip().replace(" ", "").replace("+91", "")
    if phone not in settings.DASHBOARD_ALLOWED_PHONES:
        raise HTTPException(status_code=403, detail="Phone number not authorised")
    if password != settings.DASHBOARD_PASSWORD:
        raise HTTPException(status_code=403, detail="Wrong password")

    token = _make_token(phone)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        _COOKIE,
        token,
        max_age=_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/dashboard-auth/login", status_code=303)
    response.delete_cookie(_COOKIE)
    return response
