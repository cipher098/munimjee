"""Native-session, CSRF and compatibility revocation checks on actual migrations."""
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request
from app.api.v1.session import check_login_origin, require_v1_mutation
from app.config import settings
from app.models.identity import User
from app.models.identity_auth import UserSession
from app.models.seller import Seller
from app.services.auth_sessions import (enforce_legacy_owner_access, issue_session, native_session,
    now_utc, revoke_all_sessions)
from app.services.identity import ensure_legacy_owner_bridge, legacy_owner_id


def request(token=None, csrf=None, origin="http://test", *, bearer=False, header_csrf=None):
    headers = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if bearer:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    else:
        cookies = []
        if token:
            cookies.append("v1_session=" + token)
        if csrf:
            cookies.append("v1_csrf=" + csrf)
        headers.append((b"cookie", "; ".join(cookies).encode()))
        if csrf or header_csrf:
            headers.append((b"x-csrf-token", (header_csrf or csrf).encode()))
    return Request({"type": "http", "method": "POST", "scheme": "http", "path": "/",
                    "server": ("test", 80), "headers": headers})


@pytest.fixture
async def db(migrated_engine):
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def user_and_session(db):
    user = User(id=uuid4(), display_name="Synthetic", is_active=True)
    db.add(user)
    await db.flush()
    token, csrf, session = await issue_session(db, user)
    return user, token, csrf, session


@pytest.mark.asyncio
async def test_native_issued_session_is_persistent_and_distinct_from_legacy(db):
    user, token, _, session = await user_and_session(db)
    claims = jwt.get_unverified_claims(token)
    assert claims["role"] == "v1_user" and claims["purpose"] == "v1_actor"
    assert claims["sid"] == str(session.id)
    assert (await native_session(db, token)).actor.user_id == user.id
    assert await db.get(UserSession, session.id) is session


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["session_revoked", "user_revoked", "expired", "version", "missing_session"])
async def test_session_checks_authoritative_revocation_and_expiry(db, reason):
    user, token, _, session = await user_and_session(db)
    if reason == "session_revoked":
        session.revoked_at = now_utc()
    elif reason == "user_revoked":
        user.revoked_at = now_utc()
    elif reason == "expired":
        session.expires_at = now_utc() - timedelta(seconds=1)
    elif reason == "version":
        user.auth_version += 1
    else:
        await db.delete(session)
    await db.flush()
    with pytest.raises(HTTPException) as denied:
        await native_session(db, token)
    assert denied.value.status_code == 401


@pytest.mark.asyncio
async def test_cookie_mutation_requires_origin_and_session_bound_csrf(db, monkeypatch):
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    user, token, csrf, _ = await user_and_session(db)
    assert (await require_v1_mutation(request(token, csrf), db)).user_id == user.id
    for req in (request(token, csrf, origin=None), request(token, csrf, origin="https://evil.invalid"),
                request(token), request(token, csrf, header_csrf="wrong"), request(token, "unbound-cookie")):
        with pytest.raises(HTTPException) as denied:
            await require_v1_mutation(req, db)
        assert denied.value.status_code == 403
    assert (await require_v1_mutation(request(token, bearer=True, origin=None), db)).user_id == user.id


@pytest.mark.asyncio
async def test_revoke_all_invalidates_native_and_older_legacy_credentials(db, monkeypatch):
    monkeypatch.setattr(settings, "V1_ENFORCE_LEGACY_ACCESS", True)
    seller = Seller(id=uuid4(), email="owner@example.test", password_hash="unused", is_active=True)
    db.add(seller)
    await db.flush()
    await ensure_legacy_owner_bridge(db, seller)
    user = await db.get(User, legacy_owner_id(seller.id))
    token, _, _ = await issue_session(db, user)
    old = {"iat": now_utc().timestamp() - 5}
    await enforce_legacy_owner_access(db, seller.id, old)
    await revoke_all_sessions(db, user)
    with pytest.raises(HTTPException):
        await native_session(db, token)
    for claims in ({}, old):
        with pytest.raises(HTTPException):
            await enforce_legacy_owner_access(db, seller.id, claims)
    await enforce_legacy_owner_access(db, seller.id, {"iat": now_utc().timestamp()})


def test_login_rejects_explicit_foreign_origin():
    with pytest.raises(HTTPException) as denied:
        check_login_origin(request(origin="https://evil.invalid"))
    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['session_revoked','session_expired','user_version'])
async def test_native_session_ignores_retained_orm_authority_after_other_commit(db,migrated_engine,change):
    from sqlalchemy import update
    user,token,_,session=await user_and_session(db)
    await db.commit()
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async with sessions.begin() as other:
        if change=='user_version':
            await other.execute(update(User).where(User.id==user.id).values(auth_version=User.auth_version+1))
        else:
            values={'revoked_at':now_utc()} if change=='session_revoked' else {'expires_at':now_utc()-timedelta(seconds=1)}
            await other.execute(update(UserSession).where(UserSession.id==session.id).values(**values))
    # Strong references deliberately remain stale; the database authorizes.
    assert session.revoked_at is None and user.auth_version==0
    with pytest.raises(HTTPException) as denied:
        await native_session(db,token)
    assert denied.value.status_code==401


@pytest.mark.asyncio
async def test_legacy_revocation_cutoff_uses_current_database_not_cached_user(db,migrated_engine,monkeypatch):
    from sqlalchemy import update
    monkeypatch.setattr(settings,'V1_ENFORCE_LEGACY_ACCESS',True)
    seller=Seller(id=uuid4(),email='cached-owner@example.test',password_hash='synthetic',is_active=True)
    db.add(seller)
    await db.flush()
    await ensure_legacy_owner_bridge(db,seller)
    user=await db.get(User,legacy_owner_id(seller.id))
    await db.commit()
    old={'iat':now_utc().timestamp()-10}
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async with sessions.begin() as other:
        await other.execute(update(User).where(User.id==user.id).values(legacy_revoked_before=now_utc()))
    assert user.legacy_revoked_before is None
    with pytest.raises(HTTPException) as denied:
        await enforce_legacy_owner_access(db,seller.id,old)
    assert denied.value.status_code==401
