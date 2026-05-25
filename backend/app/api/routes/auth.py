"""JWT auth endpoints for sellers and delivery team members."""
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.integrations.instagram import (
    build_oauth_authorize_url,
    exchange_code_for_user_token,
    exchange_for_long_lived_token,
    fetch_ig_user,
    subscribe_ig_user_to_messages,
)
from app.models.delivery_member import DeliveryMember
from app.models.seller import Seller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# bcrypt has a hard 72-byte input limit. Anything longer must be truncated
# (or pre-hashed) — otherwise bcrypt 4.x raises ValueError and the request
# 500s. We truncate by bytes, not characters, because UTF-8 multibyte chars
# can push a short-looking password past the limit.
_BCRYPT_MAX_BYTES = 72


def _bcrypt_clamp(password: str) -> bytes:
    encoded = password.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES]


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(_bcrypt_clamp(plain), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    """Reads `$2a$`, `$2b$`, `$2y$` hashes — compatible with anything passlib used to write."""
    try:
        return bcrypt.checkpw(_bcrypt_clamp(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash on the seller row — treat as auth failure, don't crash.
        return False


def _create_token(payload: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {**payload, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


class SellerSignupRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str | None = None


class SellerSignupResponse(BaseModel):
    seller_id: str
    access_token: str
    token_type: str = "bearer"
    onboarding_state: str
    instagram_oauth_url: str


@router.post("/seller/signup", response_model=SellerSignupResponse)
async def seller_signup(body: SellerSignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new seller account. Instagram is connected via /oauth/start afterwards."""
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Seed sensible defaults so the bot can reply intelligently the moment Instagram
    # is connected — seller can edit these in /dashboard/settings later.
    from app.seller_defaults import DEFAULT_PERSONA, DEFAULT_POLICIES

    seller = Seller(
        email=body.email,
        password_hash=_hash_password(body.password),
        business_name=body.business_name,
        onboarding_state="signed_up",
        is_active=True,
        persona=DEFAULT_PERSONA,
        policies=DEFAULT_POLICIES,
    )
    db.add(seller)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.commit()

    token = _create_token({"sub": str(seller.id), "role": "seller"})
    oauth_url = build_oauth_authorize_url(
        redirect_uri=_oauth_redirect_uri(request),
        state=_sign_oauth_state(str(seller.id)),
    )
    return SellerSignupResponse(
        seller_id=str(seller.id),
        access_token=token,
        onboarding_state=seller.onboarding_state,
        instagram_oauth_url=oauth_url,
    )


class SellerLoginRequest(BaseModel):
    email: str
    password: str


class DeliveryLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/seller/login", response_model=TokenResponse)
async def seller_login(body: SellerLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.email == body.email))
    seller = result.scalar_one_or_none()
    if not seller or not _verify_password(body.password, seller.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not seller.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    token = _create_token({"sub": str(seller.id), "role": "seller"})
    return TokenResponse(access_token=token, role="seller")


class ConnectInstagramRequest(BaseModel):
    seller_id: str
    short_lived_token: str


@router.post("/seller/connect-instagram")
async def connect_instagram(body: ConnectInstagramRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a short-lived Instagram token for a long-lived one and save it to the seller."""
    result = await db.execute(select(Seller).where(Seller.id == body.seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    try:
        long_lived_token = await exchange_for_long_lived_token(body.short_lived_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    seller.instagram_token = long_lived_token
    seller.instagram_token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    await db.commit()

    return {"detail": "Instagram token updated", "expires_at": seller.instagram_token_expires_at}


# ---------------------------------------------------------------------------
# Instagram self-serve OAuth flow (Instagram-direct, NOT Facebook Login)
# ---------------------------------------------------------------------------
# Seller hits /auth/instagram/oauth/start?seller_id=...
#   → we 302 to instagram.com/oauth/authorize with a signed `state`.
# Meta sends them back to /auth/instagram/oauth/callback?code=...&state=...
#   → we verify state, exchange code → short token → long-lived token,
#     fetch the IG account info via graph.instagram.com/me,
#     persist on the Seller row, and redirect to /onboarding?step=done.
#
# No Facebook Page involved. Webhook subscription is configured once at the
# App level in Meta dashboard (Webhooks → Instagram → messages), not per seller.


def _oauth_redirect_uri(request: Request) -> str:
    """OAuth redirect must match exactly what's whitelisted in the Meta App config."""
    if settings.PUBLIC_BASE_URL:
        base = settings.PUBLIC_BASE_URL.rstrip("/")
    else:
        # Fallback for local dev when PUBLIC_BASE_URL is unset.
        base = str(request.base_url).rstrip("/")
    return f"{base}/auth/instagram/oauth/callback"


def _sign_oauth_state(seller_id: str) -> str:
    """Sign the seller_id so we can verify the callback came from our own start route.

    Format: <seller_id>.<hex_sig>
    Sig = HMAC-SHA256(SECRET_KEY, seller_id). Constant-time compared on verify.
    """
    sig = hmac.new(
        settings.SECRET_KEY.encode(),
        seller_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{seller_id}.{sig}"


def _verify_oauth_state(state: str) -> str:
    """Returns the seller_id if the state signature is valid, else raises 400."""
    try:
        seller_id, sig = state.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed OAuth state")
    expected = hmac.new(
        settings.SECRET_KEY.encode(),
        seller_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid OAuth state signature")
    return seller_id


@router.get("/instagram/oauth/start")
async def instagram_oauth_start(seller_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Kick off Facebook Login. Returns a 302 to the Meta dialog."""
    result = await db.execute(select(Seller).where(Seller.id == seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    url = build_oauth_authorize_url(
        redirect_uri=_oauth_redirect_uri(request),
        state=_sign_oauth_state(str(seller.id)),
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/instagram/oauth/callback")
async def instagram_oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """Meta redirects the seller back here. Exchange code → token → persist → subscribe."""
    if error:
        logger.warning("Meta OAuth callback returned error: %s — %s", error, error_description)
        return RedirectResponse(
            url=f"/onboarding?error={error}",
            status_code=302,
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    seller_id = _verify_oauth_state(state)
    result = await db.execute(select(Seller).where(Seller.id == seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    redirect_uri = _oauth_redirect_uri(request)
    try:
        code_resp = await exchange_code_for_user_token(code, redirect_uri)
        short_token = code_resp["access_token"]
        # user_id is returned by the code-exchange response directly — use it as
        # a fallback if /me later fails or isn't reachable on this token type.
        prelim_user_id = code_resp.get("user_id")

        try:
            long_lived = await exchange_for_long_lived_token(short_token)
        except Exception as long_lived_exc:
            logger.warning("Long-lived token exchange failed (%s) — falling back to short-lived", long_lived_exc)
            long_lived = short_token

        try:
            ig_user = await fetch_ig_user(long_lived)
        except Exception as me_exc:
            logger.warning("graph.instagram.com/me failed (%s) — using user_id from code exchange", me_exc)
            ig_user = {"user_id": prelim_user_id}
    except Exception as exc:
        logger.exception("Instagram OAuth token exchange failed: %s", exc)
        return RedirectResponse(url="/onboarding?error=token_exchange_failed", status_code=302)

    ig_user_id = ig_user.get("user_id") or ig_user.get("id")
    if not ig_user_id:
        logger.warning("Seller %s OAuth: /me returned no user_id: %s", seller_id, ig_user)
        return RedirectResponse(url="/onboarding?error=no_instagram_account", status_code=302)

    account_type = ig_user.get("account_type")
    if account_type and account_type not in ("BUSINESS", "CREATOR"):
        logger.warning("Seller %s OAuth: IG account is %s, not Business/Creator", seller_id, account_type)
        return RedirectResponse(url="/onboarding?error=not_business_account", status_code=302)

    # Instagram-direct flow: no Page hop. fb_page_id holds the IG user id so
    # existing send_message code (which builds URLs as <base>/<fb_page_id>/messages)
    # hits graph.instagram.com/v22.0/<ig_user_id>/messages correctly.
    # Webhooks are subscribed at the App level in Meta dashboard, not per account.
    ig_user_id = str(ig_user_id)
    seller.instagram_id = ig_user_id
    seller.instagram_page_id = ig_user_id
    seller.fb_page_id = ig_user_id
    seller.instagram_token = long_lived
    seller.instagram_token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    seller.onboarding_state = "instagram_connected"
    await db.commit()

    # Subscribe this IG account to the app's `messages` webhook. Without this,
    # Meta won't fire webhook events for this seller's DMs.
    try:
        sub_resp = await subscribe_ig_user_to_messages(ig_user_id, long_lived)
        logger.info("Subscribed IG %s to messages webhook: %s", ig_user_id, sub_resp)
    except Exception as sub_exc:
        logger.warning("Failed to subscribe IG %s to webhook: %s", ig_user_id, sub_exc)

    logger.info(
        "Seller %s connected Instagram (direct flow): ig_user=%s username=%s",
        seller_id, ig_user_id, ig_user.get("username"),
    )
    return RedirectResponse(url="/onboarding?step=done", status_code=302)


@router.post("/delivery/login", response_model=TokenResponse)
async def delivery_login(body: DeliveryLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DeliveryMember).where(DeliveryMember.username == body.username)
    )
    member = result.scalar_one_or_none()
    if not member or not _verify_password(body.password, member.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not member.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    token = _create_token({
        "sub": str(member.id),
        "role": "delivery",
        "seller_id": str(member.seller_id),
    })
    return TokenResponse(access_token=token, role="delivery")
