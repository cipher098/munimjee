"""Actual 0053→0054 constraints, not create_all or copied test-only tables."""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import func,inspect,select,text
from sqlalchemy.exc import IntegrityError
from app.models.activity_v1 import ActivityContext,ActivityEvent,ActivityPolicy,ActivityPolicyCommand
from tests.test_v1_native_completion_import_http import native_import


async def policy(j,db,*,mode='live',at=None):
    at=at or await db.scalar(select(func.clock_timestamp()))
    db.add(ActivityPolicy(business_id=j.bid,mode=mode,revision=1,updated_at=at))
    db.add(ActivityPolicyCommand(business_id=j.bid,idempotency_key=uuid4(),actor_user_id=j.uid,request_hash='a'*64,mode=mode,revision=1,notice_version='first-party.v1',created_at=at))
    await db.flush();return at


async def context(j,db,*,at=None,classification='live',reason='live_policy'):
    at=at or await db.scalar(select(func.clock_timestamp()))
    row=ActivityContext(id=uuid4(),business_id=j.bid,idempotency_key=uuid4(),classification=classification,reason=reason,policy_revision=1,started_at=at,expires_at=at+timedelta(minutes=30),retained_until=at+timedelta(days=90))
    db.add(row);await db.flush();return row


@pytest.mark.asyncio
async def test_activity_actual_head_and_model_column_parity(native_import):
    j=native_import
    async with j.sessions() as db:
        assert await db.scalar(text('SELECT version_num FROM alembic_version'))=='0054_v1_activity'
        connection=await db.connection()
        from app.models.activity_v1 import Base
        for name,table in Base.metadata.tables.items():
            if name.startswith('v1_activity_') or name=='v1_order_activity':
                actual=await connection.run_sync(lambda c:inspect(c).get_columns(name))
                assert {c['name'] for c in actual}==set(table.columns.keys())


@pytest.mark.asyncio
async def test_activity_tenant_reason_immutability_and_retention(native_import):
    j=native_import
    async with j.sessions.begin() as db:
        await policy(j,db);row=await context(j,db);cid=row.id
        db.add(ActivityEvent(business_id=j.bid,context_id=cid,event_kind='checkout_opened'))
    for command in (
        'UPDATE v1_activity_contexts SET classification=\'test\',reason=\'policy_test\' WHERE id=:id',
        'UPDATE v1_activity_contexts SET started_at=started_at-interval \'1 day\' WHERE id=:id',
        'DELETE FROM v1_activity_contexts WHERE id=:id',
        'DELETE FROM v1_activity_events WHERE context_id=:id',
    ):
        async with j.sessions() as db:
            with pytest.raises(IntegrityError):await db.execute(text(command),{'id':cid})
            await db.rollback()
    async with j.sessions.begin() as db:
        row=await db.get(ActivityContext,cid);row.lossy=True
    async with j.sessions() as db:
        row=await db.get(ActivityContext,cid);row.lossy=False
        with pytest.raises(IntegrityError):await db.flush()
        await db.rollback()
    async with j.sessions() as db:
        # Composite tenant context FK is enforced independently of API checks.
        db.add(ActivityEvent(business_id=uuid4(),context_id=cid,event_kind='checkout_opened'))
        with pytest.raises(IntegrityError):await db.flush()
        await db.rollback()
    async with j.sessions() as db:
        db.add(ActivityEvent(business_id=j.bid,context_id=cid,event_kind='checkout_opened'))
        with pytest.raises(IntegrityError):await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_activity_expired_raw_context_can_be_deleted_without_canonical_writes(native_import):
    j=native_import
    async with j.sessions.begin() as db:
        old=await db.scalar(select(func.clock_timestamp()))-timedelta(days=91)
        await policy(j,db,at=old-timedelta(seconds=1));row=await context(j,db,at=old)
        db.add(ActivityEvent(business_id=j.bid,context_id=row.id,event_kind='checkout_opened',created_at=old+timedelta(seconds=1)))
        await db.flush();await db.delete(row)
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityContext))==0
        assert await db.scalar(select(func.count()).select_from(ActivityEvent))==0
        assert await db.scalar(select(func.count()).select_from(ActivityPolicyCommand))==1
