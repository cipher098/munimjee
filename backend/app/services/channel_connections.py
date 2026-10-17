"""Owner-authorized local connection lifecycle using existing provider adapters."""
import hashlib
import hmac
from datetime import timedelta
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import or_, select, text, update

from app.config import settings
from app.integrations import instagram as ig
from app.models.channel_operator import ChannelConnectionState, ChannelOAuthAttempt, ChannelOperation
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount
from app.services import whatsapp_provider
from app.services.channel_credentials import encrypt, decrypt
from app.services.channel_operator import begin_operation, locked_access, now


async def state_for(db, business_id, channel):
    state = await db.get(ChannelConnectionState, (business_id, channel))
    if state is None:
        seller = await db.get(Seller, business_id)
        account = await db.get(WhatsAppAccount, business_id) if channel == "whatsapp" else None
        enabled = bool(account and account.enabled) if channel == "whatsapp" else bool(seller and seller.instagram_token and seller.instagram_page_id)
        state = ChannelConnectionState(business_id=business_id, channel=channel, version=0,
                                       automation_enabled=enabled, check_status="not_checked", provider_account_id=account.phone_number_id if account else seller.instagram_page_id if channel == "instagram" and seller else None)
        db.add(state)
        await db.flush()
    if not state.provider_account_id:
        seller = await db.get(Seller, business_id)
        account = await db.get(WhatsAppAccount, business_id) if channel == "whatsapp" else None
        state.provider_account_id = account.phone_number_id if account else seller.instagram_page_id if channel == "instagram" and seller else None
    return state


def credential_hash(request):
    authorization = request.headers.get("authorization")
    token = authorization if authorization is not None else next((request.cookies.get(key) for key in (
        "v1_session", "dashboard_session", "seller_session") if request.cookies.get(key)), "")
    return hmac.new(settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()


def oauth_browser(attempt_id, credential):
    return hmac.new(settings.SECRET_KEY.encode(), f"channel-browser:{attempt_id}:{credential}".encode(), hashlib.sha256).hexdigest()


def redirect_uri(request, business_id):
    base = settings.PUBLIC_BASE_URL.rstrip("/") if settings.PUBLIC_BASE_URL else str(request.base_url).rstrip("/")
    return f"{base}/api/v1/businesses/{business_id}/channels/instagram/callback"


async def connection_views(db, business_id):
    seller = await db.get(Seller, business_id)
    wa = await db.get(WhatsAppAccount, business_id)
    result = []
    for channel in ("instagram", "whatsapp"):
        control = await db.get(ChannelConnectionState, (business_id, channel))
        configured = bool(seller.instagram_token and seller.instagram_page_id) if channel == "instagram" else bool(wa and wa.access_token)
        expired = bool(channel == "instagram" and seller.instagram_token_expires_at and seller.instagram_token_expires_at <= now())
        webhook = bool(settings.META_WEBHOOK_SECRET) if channel == "instagram" else bool(settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN)
        if not configured:
            status = "disconnected"
        elif expired or control and control.check_status == "needs_reconnect":
            status = "needs_reconnect"
        elif not webhook:
            status = "setup_needed"
        elif not control or not control.checked_at or control.checked_at < now() - timedelta(hours=24):
            status = "not_checked"
        elif channel == "instagram" and not control.automation_enabled:
            status = "paused"
        elif channel == "whatsapp" and not wa.enabled:
            status = "paused"
        else:
            status = "access_verified"
        account_id = seller.instagram_page_id if channel == "instagram" else wa.phone_number_id if wa else None
        result.append({"channel": channel, "status": status, "configured": configured,
                       "account_hint": "••" + account_id[-6:] if account_id else None,
                       "checked_at": control.checked_at.isoformat() if control and control.checked_at else None,
                       "error_code": control.error_code if control else None, "webhook_configured": webhook,
                       "automation_enabled": bool((control.automation_enabled if control else configured) if channel == "instagram" else wa and wa.enabled),
                       "oauth_configured": bool(settings.INSTAGRAM_APP_ID and settings.INSTAGRAM_APP_SECRET) if channel == "instagram" else None,
                       "provider_approval": "not_evaluated", "readiness_scope": "local_account_access",
                       "end_to_end_tested": False})
    return result


async def disconnect(db, actor, business_id, channel, payload):
    access = await locked_access(db, actor, business_id, "channels.disconnect")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key, "disconnect_" + channel, payload.model_dump())
    if operation.outcome:
        return operation.outcome
    state = await state_for(db, business_id, channel)
    state.version += 1
    state.automation_enabled, state.check_status, state.error_code = False, "disconnected", None
    if channel == "instagram":
        access.seller.instagram_token = None
        access.seller.instagram_page_id = None
        access.seller.instagram_id = None
        access.seller.fb_page_id = None
        access.seller.instagram_token_expires_at = None
        await db.execute(update(ChannelOAuthAttempt).where(ChannelOAuthAttempt.business_id == business_id,
                         ChannelOAuthAttempt.consumed_at.is_(None)).values(consumed_at=now(), result="cancelled"))
    else:
        account = await db.get(WhatsAppAccount, business_id)
        if account:
            account.enabled, account.automation_enabled, account.access_token = False, False, ""
    operation.after_status = "disconnected"
    operation.outcome = {"status": "disconnected", "message": "Disconnected in munimjee. Review app permissions separately in Meta if you also want to revoke provider access.",
                         "operation_id": str(operation.id)}
    return operation.outcome


async def verify(db, actor, business_id, channel, payload):
    access = await locked_access(db, actor, business_id, "channels.connect")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key, "verify_" + channel, payload.model_dump())
    if operation.outcome:
        return operation.outcome
    state = await state_for(db, business_id, channel)
    try:
        if channel == "instagram":
            if not access.seller.instagram_token or not access.seller.instagram_page_id:
                raise ValueError()
            user = await ig.fetch_ig_user(access.seller.instagram_token)
            if str(user.get("user_id") or user.get("id") or "") != access.seller.instagram_page_id:
                raise ValueError()
        else:
            account = await db.get(WhatsAppAccount, business_id)
            if not account or not account.access_token:
                raise ValueError()
            await whatsapp_provider.verify_connection(decrypt(account.access_token), account.waba_id, account.phone_number_id)
        state.checked_at, state.check_status, state.error_code = now(), "verified", None
    except Exception:
        # Never return exception/response text: provider errors can contain tokens.
        state.checked_at = now()
        state.check_status, state.error_code, state.automation_enabled = "needs_reconnect", "provider_check_failed", False
        if channel == "whatsapp":
            account = await db.get(WhatsAppAccount, business_id)
            if account:
                account.enabled = False
    operation.after_status = state.check_status
    operation.outcome = {"status": state.check_status, "operation_id": str(operation.id),
                         "message": "Account access checked. Provider approvals and end-to-end delivery still need separate verification." if state.check_status == "verified" else "The account could not be verified. Reconnect or check provider access; no message was sent."}
    return operation.outcome


async def connect_whatsapp(db, actor, business_id, payload):
    await locked_access(db, actor, business_id, "channels.connect")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key, "connect_whatsapp", payload.model_dump())
    if operation.outcome:
        return operation.outcome
    account = await db.get(WhatsAppAccount, business_id)
    if account and account.phone_number_id != payload.phone_number_id:
        raise HTTPException(409, "This business cannot change its WhatsApp number while retaining the old inbox")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:account))"), {"account": "wa-owner:" + payload.phone_number_id})
    other = await db.scalar(select(WhatsAppAccount.seller_id).where(WhatsAppAccount.phone_number_id == payload.phone_number_id,
                                                                  WhatsAppAccount.seller_id != business_id))
    if other:
        raise HTTPException(409, "This number is connected to another business")
    encrypted = encrypt(payload.access_token)
    try:
        phone = await whatsapp_provider.verify_connection(payload.access_token, payload.waba_id, payload.phone_number_id)
    except Exception:
        operation.outcome = {"status": "connection_failed", "operation_id": str(operation.id),
                             "message": "WhatsApp access could not be verified. Check the account details and token. No changes were saved."}
        return operation.outcome
    if account is None:
        account = WhatsAppAccount(seller_id=business_id, phone_number_id=payload.phone_number_id, waba_id=payload.waba_id)
        db.add(account)
    account.access_token, account.waba_id = encrypted, payload.waba_id
    account.display_phone_number = str(phone.get("display_phone_number") or "")[:50]
    account.enabled, account.automation_enabled = False, False
    state = await state_for(db, business_id, "whatsapp")
    state.version += 1
    state.provider_account_id = payload.phone_number_id
    state.checked_at, state.check_status, state.error_code = now(), "verified", None
    operation.after_status = "paused"
    operation.outcome = {"status": "paused", "operation_id": str(operation.id),
                         "message": "WhatsApp access saved. Sending stays paused until you enable it after checking webhook setup."}
    return operation.outcome


async def set_automation(db, actor, business_id, channel, payload):
    access = await locked_access(db, actor, business_id, "automation.manage")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key, "automation_" + channel, payload.model_dump())
    if operation.outcome:
        return operation.outcome
    state = await state_for(db, business_id, channel)
    if payload.enabled:
        views = await connection_views(db, business_id)
        view = next(item for item in views if item["channel"] == channel)
        if not view["configured"] or not view["webhook_configured"] or state.check_status != "verified" or not state.checked_at or state.checked_at < now() - timedelta(hours=24):
            raise HTTPException(409, "Verify the connection and configure its webhook before enabling sending")
        if channel == "instagram" and access.seller.instagram_token_expires_at and access.seller.instagram_token_expires_at <= now():
            raise HTTPException(409, "Reconnect Instagram before enabling sending")
    state.automation_enabled = payload.enabled
    if channel == "whatsapp":
        account = await db.get(WhatsAppAccount, business_id)
        if account:
            account.enabled = payload.enabled
    operation.after_status = "enabled" if payload.enabled else "paused"
    operation.outcome = {"status": operation.after_status, "operation_id": str(operation.id),
                         "message": "Sending enabled subject to current conversation checks." if payload.enabled else "Sending paused. Incoming messages remain saved."}
    return operation.outcome


async def start_instagram(db, actor, business_id, payload, request):
    await locked_access(db, actor, business_id, "channels.connect")
    if not settings.INSTAGRAM_APP_ID or not settings.INSTAGRAM_APP_SECRET:
        raise HTTPException(409, "Instagram authorization is not configured for this application yet")
    operation = await begin_operation(db, actor, business_id, payload.idempotency_key, "start_instagram", payload.model_dump())
    state = await state_for(db, business_id, "instagram")
    credential = credential_hash(request)
    if operation.outcome:
        attempt = await db.get(ChannelOAuthAttempt, UUID(operation.outcome["attempt_id"]))
        if not attempt or attempt.credential_hash != credential or attempt.consumed_at or attempt.expires_at <= now():
            raise HTTPException(409, "This authorization attempt ended. Start a new connection.")
    else:
        attempt = ChannelOAuthAttempt(id=uuid4(), business_id=business_id, actor_user_id=actor.user_id,
                    operation_id=operation.id, credential_hash=credential, connection_version=state.version,
                    expires_at=now() + timedelta(minutes=10), result="pending")
        db.add(attempt)
        await db.flush()
        signed = jwt.encode({"purpose": "v1_instagram_link", "sub": str(actor.user_id), "business": str(business_id),
                             "attempt": str(attempt.id), "exp": attempt.expires_at}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        operation.outcome = {"attempt_id": str(attempt.id), "authorization_url": ig.build_oauth_authorize_url(redirect_uri(request, business_id), signed),
                             "status": "authorization_started"}
    return operation.outcome, oauth_browser(attempt.id, credential)


async def finish_instagram(db, actor, business_id, request, *, signed_state, code, denied):
    await locked_access(db, actor, business_id, "channels.connect")
    try:
        claims = jwt.decode(signed_state or "", settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("purpose") != "v1_instagram_link" or claims.get("sub") != str(actor.user_id) or claims.get("business") != str(business_id):
            raise ValueError()
        attempt_id = UUID(claims["attempt"])
    except (JWTError, ValueError, TypeError, KeyError):
        raise HTTPException(400, "Invalid or expired Instagram authorization")
    attempt = await db.scalar(select(ChannelOAuthAttempt).where(ChannelOAuthAttempt.id == attempt_id,
                    ChannelOAuthAttempt.business_id == business_id, ChannelOAuthAttempt.actor_user_id == actor.user_id).with_for_update())
    state = await state_for(db, business_id, "instagram")
    credential = credential_hash(request)
    if not attempt or attempt.consumed_at or attempt.expires_at <= now() or attempt.credential_hash != credential or attempt.connection_version != state.version:
        raise HTTPException(409, "This authorization attempt expired, was used, or was cancelled. Start again.")
    if not hmac.compare_digest(request.cookies.get("v1_ig_link", ""), oauth_browser(attempt.id, credential)):
        raise HTTPException(400, "Instagram authorization belongs to a different browser session")
    attempt.consumed_at, attempt.result = now(), "exchange_started"
    await db.commit()  # Consume before external exchange; an unknown exchange is never blindly repeated.
    if denied or not code:
        attempt.result = "declined"
        return "declined"
    try:
        data = await ig.exchange_code_for_user_token(code, redirect_uri(request, business_id))
        token = await ig.exchange_for_long_lived_token(data["access_token"])
        info = await ig.fetch_ig_user(token)
        account_id = str(info.get("user_id") or info.get("id") or "")
        if not account_id.isdigit() or len(account_id) > 100 or info.get("account_type") not in {"BUSINESS", "CREATOR"}:
            raise ValueError()
    except Exception:
        attempt.result = "exchange_failed"
        return "exchange_failed"
    # Recheck membership and disconnect generation after the network gap.
    access = await locked_access(db, actor, business_id, "channels.connect")
    state = await state_for(db, business_id, "instagram")
    await db.refresh(state)
    if state.version != attempt.connection_version:
        attempt.result = "cancelled"
        return "cancelled"
    from app.models.instagram_ingress import InstagramIngress
    historical = set((await db.scalars(select(InstagramIngress.account_id).where(InstagramIngress.seller_id == business_id).distinct())).all())
    if (state.provider_account_id and state.provider_account_id != account_id) or historical - {account_id}:
        attempt.result = "account_change_requires_migration"
        return "account_change_requires_migration"
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:account))"), {"account": "ig-owner:" + account_id})
    other = await db.scalar(select(Seller.id).where(Seller.id != business_id,
                     or_(Seller.instagram_id == account_id, Seller.instagram_page_id == account_id)))
    if other:
        attempt.result = "account_already_linked"
        return "account_already_linked"
    seller = access.seller
    seller.instagram_id = seller.instagram_page_id = seller.fb_page_id = account_id
    seller.instagram_token = token
    seller.instagram_token_expires_at = now() + timedelta(days=60)
    state.version += 1
    state.provider_account_id = account_id
    state.checked_at, state.check_status, state.error_code, state.automation_enabled = now(), "verified", None, False
    attempt.result = "connected"
    operation = await begin_operation(db, actor, business_id, uuid5(NAMESPACE_URL, "ig-callback:" + str(attempt.id)),
                                      "complete_instagram", {"attempt": str(attempt.id)})
    operation.after_status = "paused"
    operation.outcome = {"status": "paused", "message": "Instagram authorization saved. Sending is paused; webhook delivery and provider approvals remain unverified."}
    return "connected"
