"""Native onboarding through HTTP against the actual migrated disposable schema."""
from uuid import UUID, uuid4
import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api.v1.auth import router
from app.api.v1.identity import router as identity_router
from app.api.routes.auth import router as legacy_router
from app.api.dashboard_auth import router as dashboard_router
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_seller
from app.models.identity import User, Membership
from app.models.identity_auth import BusinessInvitation
from app.services.auth_sessions import secret_digest

PASSWORD = "synthetic-password-123"


@pytest.fixture
async def client(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "V1_ENFORCE_LEGACY_ACCESS", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://test")
    app = FastAPI()
    for r in (router, identity_router, legacy_router, dashboard_router):
        app.include_router(r)
    @app.get("/test/seller")
    async def protected_seller(seller=Depends(get_current_seller)):
        return {"id": str(seller.id)}
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": "http://test"}) as c:
        c.factory = factory
        yield c


async def signup(c, email=None):
    response = await c.post("/api/v1/auth/signup", json={"email": email or f"{uuid4().hex}@example.com",
        "password": PASSWORD, "business_name": "Synthetic Boutique"})
    assert response.status_code == 201, response.text
    return response.json()


def headers(c):
    return {"X-CSRF-Token": c.cookies.get("v1_csrf", "")}


async def invite(c, bid, email, role="staff"):
    response = await c.post(f"/api/v1/businesses/{bid}/invitations", headers=headers(c), json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_fresh_signup_profile_and_resumed_checklist(client):
    c = client
    email = f"{uuid4().hex}@example.com"
    actor = await signup(c, email)
    bid = actor["businesses"][0]["id"]
    token = c.cookies["v1_session"]
    assert actor["auth_method"] == "v1_user" and actor["businesses"][0]["role"] == "owner"
    assert c.cookies.get("seller_session") is None
    assert (await c.get("/api/v1/auth/session")).json()["csrf_token"] == c.cookies["v1_csrf"]
    initial = (await c.get(f"/api/v1/businesses/{bid}/onboarding")).json()
    assert initial["completed_steps"] == 1
    body = {"expected_version": 0, "name": "Confirmed Boutique", "business_type": "boutique", "country": "IN"}
    url = f"/api/v1/businesses/{bid}/profile"
    assert (await c.put(url, json=body)).status_code == 403
    saved = await c.put(url, headers=headers(c), json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["confirmed"] and saved.json()["version"] == 1
    assert (await c.put(url, headers=headers(c), json=body)).status_code == 409
    assert (await c.get(f"/api/v1/businesses/{uuid4()}/profile")).status_code == 404
    assert (await c.post("/api/v1/auth/logout", headers=headers(c))).status_code == 200
    assert (await c.get("/api/v1/auth/session", headers={"Authorization": "Bearer " + token})).status_code == 401
    assert (await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200
    resumed = (await c.get(f"/api/v1/businesses/{bid}/onboarding")).json()
    assert resumed["completed_steps"] == 2 and not resumed["onboarding_complete"]
    assert resumed["profile"]["name"] == "Confirmed Boutique"


@pytest.mark.asyncio
async def test_invitation_new_staff_is_not_seller_and_membership_revoke_is_immediate(client):
    c = client
    owner = await signup(c)
    bid = owner["businesses"][0]["id"]
    owner_token = c.cookies["v1_session"]
    email = f"{uuid4().hex}@example.com"
    invitation = await invite(c, bid, email)
    secret = invitation["invitation_url"].split("=", 1)[1]
    async with c.factory() as db:
        row = await db.get(BusinessInvitation, UUID(invitation["id"]))
        assert row.token_digest == secret_digest(secret) and row.token_digest != secret
    listed = await c.get(f"/api/v1/businesses/{bid}/invitations")
    assert secret not in listed.text and "token_digest" not in listed.text
    accepted = await c.post("/api/v1/auth/invitations/accept", json={"email": email, "password": PASSWORD, "token": secret})
    assert accepted.status_code == 200, accepted.text
    staff = accepted.json()
    assert staff["businesses"][0]["role"] == "staff"
    staff_token = c.cookies["v1_session"]
    async with c.factory() as db:
        user = await db.get(User, UUID(staff["user_id"]))
        assert user.legacy_seller_id is None
        membership = await db.scalar(select(Membership).where(Membership.user_id == user.id))
        mid = membership.id
    assert (await c.post(f"/api/v1/businesses/{bid}/invitations", headers=headers(c), json={"email": "other@example.com", "role": "manager"})).status_code == 403
    assert (await c.put(f"/api/v1/businesses/{bid}/profile", headers=headers(c), json={"name": "Staff edit", "expected_version": 0, "country": "IN", "business_type": "boutique"})).status_code == 403
    assert (await c.get("/dashboard-auth/me", cookies={"dashboard_session": staff_token})).status_code == 302
    assert (await c.post("/auth/seller/connect-instagram", headers={"Authorization": "Bearer " + staff_token}, json={"short_lived_token": "no-call"})).status_code == 401
    assert (await c.post("/api/v1/auth/invitations/accept", json={"email": email, "password": PASSWORD, "token": secret})).status_code == 400
    revoke = await c.patch(f"/api/v1/businesses/{bid}/members/{mid}", headers={"Authorization": "Bearer " + owner_token}, json={"action": "revoke"})
    # Switching browser identity revokes the old owner session.
    assert revoke.status_code == 401
    c.cookies.clear()  # A separate owner browser leaves the staff session live.
    assert (await c.post("/api/v1/auth/login", json={"email": (await _email(c, owner["user_id"])), "password": PASSWORD})).status_code == 200
    assert (await c.patch(f"/api/v1/businesses/{bid}/members/{mid}", headers=headers(c), json={"action": "revoke"})).status_code == 200
    assert (await c.get(f"/api/v1/businesses/{bid}/profile", headers={"Authorization": "Bearer " + staff_token})).status_code == 404


async def _email(c, uid):
    async with c.factory() as db:
        return (await db.get(User, UUID(uid))).auth_email


@pytest.mark.asyncio
async def test_existing_account_invitation_requires_password_not_matching_email(client):
    c = client
    existing_email = f"{uuid4().hex}@example.com"
    existing = await signup(c, existing_email)
    owner = await signup(c)
    bid = owner["businesses"][0]["id"]
    invitation = await invite(c, bid, existing_email, "viewer")
    secret = invitation["invitation_url"].split("=", 1)[1]
    body = {"email": existing_email, "password": "wrong-password", "token": secret}
    assert (await c.post("/api/v1/auth/invitations/accept", json=body)).status_code == 401
    body["password"] = PASSWORD
    response = await c.post("/api/v1/auth/invitations/accept", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == existing["user_id"]
    assert len(response.json()["businesses"]) == 2


@pytest.mark.asyncio
async def test_logout_all_revokes_other_native_and_legacy_supported_routes(client):
    c = client
    email = f"{uuid4().hex}@example.com"
    owner = await signup(c, email)
    first_token = c.cookies["v1_session"]
    legacy = await c.post("/auth/seller/login", json={"email": email, "password": PASSWORD})
    assert legacy.status_code == 200
    legacy_token = legacy.json()["access_token"]
    # Legacy login revoked the previous native browser session and removed its cookies.
    assert c.cookies.get("v1_session") is None
    assert (await c.get("/api/v1/me", headers={"Authorization": "Bearer " + first_token})).status_code == 401
    dashboard = await c.post("/dashboard-auth/login", data={"identifier": email, "password": PASSWORD})
    assert dashboard.status_code == 303
    old_dashboard = c.cookies["dashboard_session"]
    assert (await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200
    assert c.cookies.get("dashboard_session") is None and c.cookies.get("seller_session") is None
    assert (await c.post("/api/v1/auth/logout-all", headers=headers(c))).status_code == 200
    assert (await c.get("/api/v1/me", headers={"Authorization": "Bearer " + legacy_token})).status_code == 401
    assert (await c.get("/dashboard-auth/me", cookies={"dashboard_session": old_dashboard})).status_code == 401
    assert (await c.post("/auth/seller/connect-instagram", headers={"Authorization": "Bearer " + legacy_token}, json={"short_lived_token": "no-call"})).status_code == 401
    assert (await c.get("/test/seller", headers={"Authorization": "Bearer " + legacy_token})).status_code == 401
    # Proving credentials again creates a new legacy session after the revocation cutoff.
    assert (await c.post("/auth/seller/login", json={"email": email, "password": PASSWORD})).status_code == 200
    assert (await c.get("/api/v1/me")).status_code == 200


@pytest.mark.asyncio
async def test_flags_origins_and_malformed_inputs_fail_closed(client, monkeypatch):
    c = client
    body = {"email": "synthetic@example.com", "password": PASSWORD, "business_name": "Synthetic"}
    assert (await c.post("/api/v1/auth/signup", json=body, headers={"Origin": "https://evil.invalid"})).status_code == 403
    assert (await c.post("/api/v1/auth/signup", json={**body, "role": "owner"})).status_code == 422
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", False)
    assert (await c.post("/api/v1/auth/signup", json=body)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["expired", "revoked", "email_mismatch", "inviter_revoked"])
async def test_invitation_failures_do_not_consume_or_create_access(client, reason):
    from datetime import timedelta
    from app.services.auth_sessions import now_utc
    c = client
    owner = await signup(c)
    bid = owner["businesses"][0]["id"]
    email = f"{uuid4().hex}@example.com"
    invitation = await invite(c, bid, email, "manager")
    async with c.factory() as db:
        row = await db.get(BusinessInvitation, UUID(invitation["id"]))
        if reason == "expired": row.expires_at = now_utc() - timedelta(seconds=1)
        elif reason == "revoked": row.revoked_at = now_utc()
        elif reason == "inviter_revoked":
            (await db.get(User, UUID(owner["user_id"]))).revoked_at = now_utc()
        await db.commit()
    response = await c.post("/api/v1/auth/invitations/accept", json={"email": "mismatch@example.com" if reason == "email_mismatch" else email,
        "password": PASSWORD, "token": invitation["invitation_url"].split("=",1)[1]})
    assert response.status_code in {400,401}, response.text
    async with c.factory() as db:
        row = await db.get(BusinessInvitation, UUID(invitation["id"]))
        assert row.consumed_at is None and row.accepted_by is None
        assert await db.scalar(select(User.id).where(User.auth_email == email)) is None


@pytest.mark.asyncio
async def test_concurrent_signup_and_one_use_invitation_are_transactional(client):
    import asyncio
    from sqlalchemy import func
    c = client
    email=f"{uuid4().hex}@example.com"
    body={"email":email,"password":PASSWORD,"business_name":"Concurrent boutique"}
    results=await asyncio.gather(c.post("/api/v1/auth/signup",json=body),c.post("/api/v1/auth/signup",json=body))
    assert sorted(r.status_code for r in results)==[201,409]
    owner=next(r.json() for r in results if r.status_code==201)
    bid=owner["businesses"][0]["id"]
    # Shared-client cookie updates from the conflict response must not replace the winner.
    await c.post("/api/v1/auth/login",json={"email":email,"password":PASSWORD})
    guest=f"{uuid4().hex}@example.com"
    invitation=await invite(c,bid,guest)
    accept={"email":guest,"password":PASSWORD,"token":invitation["invitation_url"].split("=",1)[1]}
    results=await asyncio.gather(c.post("/api/v1/auth/invitations/accept",json=accept),c.post("/api/v1/auth/invitations/accept",json=accept))
    assert sorted(r.status_code for r in results)==[200,400]
    async with c.factory() as db:
        assert await db.scalar(select(func.count()).select_from(User).where(User.auth_email==guest))==1
        assert await db.scalar(select(func.count()).select_from(Membership).where(Membership.business_id==UUID(bid)))==2


@pytest.mark.asyncio
async def test_legacy_signup_bridge_revoked_user_and_rollout_compatibility(client,monkeypatch):
    from app.services.auth_sessions import now_utc
    from app.services.identity import legacy_owner_id
    c=client
    email=f"{uuid4().hex}@example.com"
    legacy=await c.post("/auth/seller/signup",json={"email":email,"password":PASSWORD,"business_name":"Legacy boutique"})
    assert legacy.status_code==200,legacy.text
    bid=UUID(legacy.json()["seller_id"])
    token=legacy.json()["access_token"]
    assert (await c.get("/test/seller",headers={"Authorization":"Bearer "+token})).status_code==200
    async with c.factory() as db:
        user=await db.get(User,legacy_owner_id(bid))
        assert user is not None and user.auth_email is None
    native=await c.post("/api/v1/auth/login",json={"email":email,"password":PASSWORD})
    assert native.status_code==200,native.text
    async with c.factory() as db:
        user=await db.get(User,legacy_owner_id(bid))
        assert user.auth_email==email
        user.revoked_at=now_utc()
        await db.commit()
    assert (await c.get("/api/v1/auth/session")).status_code==401
    assert (await c.get("/test/seller",headers={"Authorization":"Bearer "+token})).status_code==401
    monkeypatch.setattr(settings,"V1_ENFORCE_LEGACY_ACCESS",False)
    assert (await c.get("/test/seller",headers={"Authorization":"Bearer "+token})).status_code==200


@pytest.mark.asyncio
async def test_admin_impersonation_requires_separate_unimplemented_grant(client):
    from app.api.dashboard_auth import _make_token
    c=client
    owner=await signup(c)
    bid=owner["businesses"][0]["id"]
    admin=_make_token("admin",None,"synthetic-admin")
    c.cookies.clear()
    c.cookies.set("dashboard_session",admin)
    assert (await c.post(f"/dashboard-auth/view/{bid}")).status_code==403
    c.cookies.set("view_seller",bid)
    assert (await c.get("/dashboard-auth/me")).status_code==403
    assert (await c.get("/api/v1/me")).status_code==401
