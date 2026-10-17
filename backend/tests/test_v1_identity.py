"""Pure identity/auth contract tests; no database connections or live services."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from jose import jwt
from starlette.requests import Request
from app.api.v1.identity import decode_actor_credentials, business_view, readiness
from app.config import settings
from app.services.identity import (Actor, BusinessAccess, capabilities_for, legacy_membership_id,
                                   legacy_owner_id, resolve_user_actor)


def token(**claims):
    return jwt.encode({"exp": datetime.now(timezone.utc) + timedelta(minutes=5), **claims},
                      settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def request(bearer=None, cookies=None, authorization=None):
    headers = []
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    if cookies:
        headers.append((b"cookie", "; ".join(f"{key}={value}" for key, value in cookies.items()).encode()))
    return Request({"type": "http", "headers": headers})


def test_legacy_bearer_and_dashboard_session_resolve_same_owner():
    sid = uuid4()
    assert decode_actor_credentials(request(bearer=token(role="seller", sub=str(sid)))) == ("legacy_owner", sid)
    assert decode_actor_credentials(request(cookies={"dashboard_session": token(role="seller", seller_id=str(sid), sub="owner@example.test"),
                                                    "view_seller": str(uuid4())})) == ("legacy_owner", sid)


def test_native_user_is_distinct_from_legacy_seller():
    uid = uuid4()
    assert decode_actor_credentials(request(bearer=token(role="v1_user", purpose="v1_actor", sub=str(uid)))) == ("v1_user", uid)


@pytest.mark.parametrize("claims", [
    {"role": "admin", "sub": "support"}, {"role": "delivery", "sub": str(uuid4())},
    {"role": "staff", "sub": str(uuid4())}, {"role": "viewer", "sub": str(uuid4())},
    {"role": "seller", "purpose": "v1_actor", "sub": str(uuid4())},
    {"role": "v1_user", "sub": str(uuid4())}, {"purpose": "v1_actor", "sub": str(uuid4())},
    {"role": "seller", "sub": "not-a-uuid"}, {"role": "seller"},
    {"role": "seller", "sub": str(uuid4()), "seller_id": str(uuid4())},
    {"role": "v1_user", "purpose": "v1_actor", "sub": "invalid"},
])
def test_invalid_identity_credentials_fail_closed(claims):
    with pytest.raises(HTTPException) as exc:
        decode_actor_credentials(request(bearer=token(**claims), cookies={"view_seller": str(uuid4())}))
    assert exc.value.status_code == 401


def test_expiry_signature_and_missing_exp_are_rejected():
    sid = str(uuid4())
    bad_tokens = [token(role="seller", sub=sid, exp=datetime.now(timezone.utc) - timedelta(seconds=5)),
                  jwt.encode({"role": "seller", "sub": sid}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM),
                  jwt.encode({"role": "seller", "sub": sid, "exp": 9999999999}, "wrong-signing-key", algorithm="HS256")]
    for value in bad_tokens:
        with pytest.raises(HTTPException):
            decode_actor_credentials(request(bearer=value))


@pytest.mark.parametrize("authorization", ["Basic arbitrary", "Bearer ", "Bearer garbage"])
def test_invalid_explicit_auth_never_falls_back_to_owner_cookie(authorization):
    with pytest.raises(HTTPException):
        decode_actor_credentials(request(authorization=authorization, cookies={"seller_session": token(role="seller", sub=str(uuid4()))}))


@pytest.mark.parametrize("role", ["manager", "staff", "viewer", "sales_support", "admin", "unknown"])
def test_only_owner_manages_members_and_channels(role):
    assert not {"members.manage", "channels.connect", "channels.disconnect"} & capabilities_for(role)
    assert {"members.manage", "channels.connect", "channels.disconnect"} <= capabilities_for("owner")


def test_staff_and_viewer_write_boundaries():
    assert {"orders.write", "inbox.reply"} <= capabilities_for("staff")
    assert not {"catalogue.write", "business.write", "analytics.read", "automation.manage"} & capabilities_for("staff")
    assert all(cap.endswith(".read") for cap in capabilities_for("viewer"))
    assert {"catalogue.write", "business.write", "automation.manage"} <= capabilities_for("manager")
    assert not capabilities_for("sales_support")


def test_deterministic_ids_do_not_link_distinct_sellers():
    first, second = uuid4(), uuid4()
    assert legacy_owner_id(first) == legacy_owner_id(first)
    assert legacy_owner_id(first) != legacy_owner_id(second)
    assert legacy_owner_id(first) != legacy_membership_id(first)


@pytest.mark.asyncio
async def test_missing_current_user_cannot_resolve_actor():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        await resolve_user_actor(db, uuid4(), "v1_user")
    assert exc.value.status_code == 401


def test_public_business_view_uses_allowlist_only():
    access = BusinessAccess(SimpleNamespace(id=uuid4(), name="Test boutique", password_hash="secret"),
                            SimpleNamespace(role="viewer"), SimpleNamespace(instagram_token="secret"))
    out = business_view(access).model_dump(mode="json")
    assert set(out) == {"id", "name", "role", "capabilities"}
    assert "secret" not in str(out)


@pytest.mark.asyncio
async def test_readiness_does_not_claim_complete_onboarding(monkeypatch):
    bid = uuid4()
    access = SimpleNamespace(seller=SimpleNamespace(onboarding_state="active"))
    monkeypatch.setattr("app.api.v1.identity.require_business_access", AsyncMock(return_value=access))
    result = await readiness(bid, Actor(uuid4(), "v1_user"), object())
    assert result.identity_ready is True
    assert result.onboarding_complete is None
    assert result.scope == "identity_foundation"
    assert {c.key for c in result.checks if c.status == "not_evaluated"} == {
        "catalogue_review", "channel_connections", "storefront_publication", "checkout"}


@pytest.mark.asyncio
async def test_native_token_is_rejected_by_legacy_seller_dependency_before_db_access():
    from fastapi.security import HTTPAuthorizationCredentials
    from app.dependencies import get_current_seller
    db = SimpleNamespace(execute=AsyncMock())
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(
        role="v1_user", purpose="v1_actor", sub=str(uuid4())))
    with pytest.raises(HTTPException) as exc:
        await get_current_seller(credentials, db)
    assert exc.value.status_code == 403
    db.execute.assert_not_called()
