"""Opt-in domain-migration checks in a rollback-only, randomly named schema.

P01 validates an explicit disposable lane and holds its reset lease.
The identity-specific baseline/backfill check uses an extra rollback-only schema.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.identity import router
from app.database import get_db
from app.models.identity import Business, Membership, User
from app.models.seller import Seller
from app.services.identity import (Actor, accessible_businesses, ensure_legacy_owner_bridge, legacy_owner_id,
                                   require_business_access, resolve_legacy_owner)
from tests.test_v1_identity import token
from alembic.script import ScriptDirectory

MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/0040_v1_identity.py"
spec = importlib.util.spec_from_file_location("identity_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest_asyncio.fixture
async def identity_db(migrated_engine):
    engine = migrated_engine
    schema = "v1_identity_" + uuid4().hex
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            def baseline(conn):
                script = ScriptDirectory(str(MIGRATION_PATH.parents[1]))
                with Operations.context(MigrationContext.configure(conn)):
                    for revision in reversed(list(script.walk_revisions(base="base", head="0039"))):
                        revision.module.upgrade()
            await connection.run_sync(baseline)
            session = AsyncSession(bind=connection, expire_on_commit=False)
            one = Seller(id=uuid4(), email="first@example.test", password_hash="synthetic", business_name="One", whatsapp_number="unverified-shared-phone", is_active=True)
            two = Seller(id=uuid4(), email="second@example.test", password_hash="synthetic", business_name="Two", whatsapp_number="unverified-shared-phone", is_active=True)
            inactive = Seller(id=uuid4(), email="inactive@example.test", password_hash="synthetic", is_active=False)
            session.add_all([one, two, inactive])
            await session.flush()
            def upgrade(conn):
                with Operations.context(MigrationContext.configure(conn)):
                    migration.upgrade()
            await connection.run_sync(upgrade)
            # Retain the 0039→0040 backfill boundary, then match current ORM
            # fields through actual later migrations before querying users.
            def followups(conn):
                script = ScriptDirectory(str(MIGRATION_PATH.parents[1]))
                with Operations.context(MigrationContext.configure(conn)):
                    for revision in reversed(list(script.walk_revisions(base="0040_v1_identity", head="head"))):
                        if revision.revision != "0040_v1_identity":
                            revision.module.upgrade()
            await connection.run_sync(followups)
            yield session, connection, one, two, inactive
            await session.close()
        finally:
            # DDL and fixture data, including the schema, are rolled back.
            await transaction.rollback()


@pytest.mark.asyncio
async def test_domain_migration_backfill_and_rerun_preserve_revocation(identity_db):
    db, connection, one, two, inactive = identity_db
    assert (await db.get(Business, one.id)).id == one.id
    assert (await db.get(User, legacy_owner_id(one.id))).legacy_seller_id == one.id
    assert not (await db.get(User, legacy_owner_id(inactive.id))).is_active
    user = await db.get(User, legacy_owner_id(one.id))
    membership = (await db.execute(select(Membership).where(Membership.business_id == one.id))).scalar_one()
    user.revoked_at = datetime.now(timezone.utc)
    membership.revoked_at = datetime.now(timezone.utc)
    membership.is_active = False
    await db.flush()
    await connection.run_sync(migration.backfill_legacy_owners)
    await ensure_legacy_owner_bridge(db, one)
    await db.refresh(user)
    await db.refresh(membership)
    assert user.revoked_at is not None
    assert membership.revoked_at is not None and not membership.is_active
    for model in (Business, User, Membership):
        assert await db.scalar(select(func.count()).select_from(model)) == 3
    with pytest.raises(HTTPException):
        await resolve_legacy_owner(db, one.id)


@pytest.mark.asyncio
async def test_tenant_isolation_and_revocation(identity_db):
    db, _, one, two, inactive = identity_db
    actor = await resolve_legacy_owner(db, one.id)
    assert [a.business.id for a in await accessible_businesses(db, actor)] == [one.id]
    with pytest.raises(HTTPException) as cross:
        await require_business_access(db, actor, two.id)
    assert cross.value.status_code == 404
    with pytest.raises(HTTPException):
        await resolve_legacy_owner(db, inactive.id)
    membership = (await db.execute(select(Membership).where(Membership.business_id == one.id))).scalar_one()
    membership.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    assert await accessible_businesses(db, actor) == []
    with pytest.raises(HTTPException):
        await require_business_access(db, actor, one.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["manager", "staff", "viewer"])
async def test_native_roles_cannot_gain_owner_actions_or_legacy_bridge(identity_db, role):
    db, _, one, _, _ = identity_db
    owner_membership = (await db.execute(select(Membership).where(Membership.business_id == one.id))).scalar_one()
    owner_membership.role = role
    await db.flush()
    actor = Actor(legacy_owner_id(one.id), "v1_user")
    for capability in ("members.manage", "channels.connect", "channels.disconnect"):
        with pytest.raises(HTTPException) as denied:
            await require_business_access(db, actor, one.id, capability)
        assert denied.value.status_code == 403
    await ensure_legacy_owner_bridge(db, one)
    assert owner_membership.role == role
    with pytest.raises(HTTPException):
        await resolve_legacy_owner(db, one.id)


@pytest.mark.asyncio
async def test_api_legacy_owner_native_viewer_and_admin_denial(identity_db):
    db, _, one, two, _ = identity_db
    viewer = User(id=uuid4(), is_active=True)
    db.add(viewer)
    await db.flush()
    db.add(Membership(business_id=one.id, user_id=viewer.id, role="viewer", is_active=True))
    await db.flush()
    app = FastAPI()
    app.include_router(router)
    async def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app), base_url="http://identity.test") as client:
        owner_auth = {"Authorization": "Bearer " + token(role="seller", sub=str(one.id))}
        me = await client.get("/api/v1/me", headers=owner_auth)
        assert me.status_code == 200
        assert me.json()["businesses"][0]["id"] == str(one.id)
        assert (await client.get(f"/api/v1/businesses/{two.id}", headers=owner_auth)).status_code == 404
        from app.services.auth_sessions import issue_session
        viewer_token, _, _ = await issue_session(db, viewer)
        viewer_auth = {"Authorization": "Bearer " + viewer_token}
        response = await client.get(f"/api/v1/businesses/{one.id}/readiness", headers=viewer_auth)
        assert response.status_code == 200 and response.json()["onboarding_complete"] is None
        assert "instagram_token" not in me.text and "password_hash" not in me.text
        response = await client.get("/api/v1/me", cookies={"dashboard_session": token(role="admin", sub="support"), "view_seller": str(one.id)})
        assert response.status_code == 401
        viewer.is_active = False
        await db.flush()
        assert (await client.get("/api/v1/me", headers=viewer_auth)).status_code == 401


@pytest.mark.asyncio
async def test_database_rejects_orphan_tenants_duplicate_memberships_and_invalid_roles(identity_db):
    db, _, one, _, _ = identity_db
    unrelated_user = User(id=uuid4(), is_active=True)
    db.add(unrelated_user)
    await db.flush()
    for membership in (
        Membership(business_id=uuid4(), user_id=legacy_owner_id(one.id), role="viewer"),
        Membership(business_id=one.id, user_id=uuid4(), role="viewer"),
        Membership(business_id=one.id, user_id=legacy_owner_id(one.id), role="viewer"),
        Membership(business_id=one.id, user_id=unrelated_user.id, role="sales_support"),
    ):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(membership)
                await db.flush()


@pytest.mark.asyncio
async def test_new_legacy_seller_requires_explicit_bridge_and_inactive_business_is_denied(identity_db):
    db, _, one, _, _ = identity_db
    new_seller = Seller(id=uuid4(), email="new@example.test", password_hash="synthetic", is_active=True)
    db.add(new_seller)
    await db.flush()
    before = await db.scalar(select(func.count()).select_from(User))
    with pytest.raises(HTTPException):
        await resolve_legacy_owner(db, new_seller.id)
    assert await db.scalar(select(func.count()).select_from(User)) == before
    await ensure_legacy_owner_bridge(db, new_seller)
    await ensure_legacy_owner_bridge(db, new_seller)
    assert (await resolve_legacy_owner(db, new_seller.id)).user_id == legacy_owner_id(new_seller.id)
    assert await db.scalar(select(func.count()).select_from(User)) == before + 1
    business = await db.get(Business, one.id)
    business.is_active = False
    await db.flush()
    await ensure_legacy_owner_bridge(db, one)
    assert not business.is_active
    with pytest.raises(HTTPException):
        await require_business_access(db, Actor(legacy_owner_id(one.id), "v1_user"), one.id)
