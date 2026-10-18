"""Canonical actual SKU orders + additive provenance on actual migrated PG16."""
import asyncio
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import func,select,text,update
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.models.activity_v1 import ActivityContext,ActivityEvent,ActivityPolicy,ActivityPolicyCommand,OrderActivity
from app.models.commerce import CommerceOrder
from app.schemas.activity_v1 import ContextWrite,EventWrite,PolicyWrite
from app.services import activity_v1 as activity,checkout_v1
from app.services.identity import Actor,legacy_owner_id
from tests.test_v1_checkout import sessions,seed,checkout


async def setup(sessions,monkeypatch):
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',True)
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',True)
    monkeypatch.setattr(settings,'APP_ENV','production')
    bid,pid,skus=await seed(sessions,stock=20)
    actor=Actor(legacy_owner_id(bid),'v1_user')
    async with sessions.begin() as db:
        await activity.change_policy(db,bid,actor,PolicyWrite(expected_revision=0,idempotency_key=uuid4(),
            mode='live',first_party_measurement_acknowledged=True))
        context=await activity.start_context(db,bid,ContextWrite(idempotency_key=uuid4()))
    return bid,pid,skus[0],actor,context


async def place(sessions,bid,sku,context=None,**proof):
    payload=checkout(sku)
    async with sessions.begin() as db:
        store=await checkout_v1.lock_store(db,bid)
        order,replayed=await checkout_v1.create_sku_order(db,store,payload)
        assert not replayed
        await activity.record_order(db,order,context_id=context.context_id if context else None,
            authorization='Bearer '+context.capability if context else None,**proof)
        oid=order.id
    return oid,payload


@pytest.mark.asyncio
async def test_real_cod_link_and_exact_checkout_replay_cannot_backfill(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    oid,payload=await place(sessions,bid,sku,context)
    async with sessions.begin() as db:
        store=await checkout_v1.lock_store(db,bid)
        replay,is_replay=await checkout_v1.create_sku_order(db,store,payload)
        assert replay.id==oid and is_replay
        original=await db.get(OrderActivity,oid)
        assert original.classification=='live' and original.context_id==context.context_id
        assert await db.scalar(select(func.count()).select_from(OrderActivity))==1
        assert original.accepted_at==replay.created_at
    async with sessions() as db:
        row=await db.get(OrderActivity,oid);row.context_id=None;row.classification='unknown';row.reason='unproven_context'
        with pytest.raises(IntegrityError):await db.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize('proof',['missing','invalid','foreign','expired'])
async def test_optional_bad_measurement_never_denies_financial_order(sessions,monkeypatch,proof):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    from types import SimpleNamespace
    if proof=='missing':context=None
    elif proof=='invalid':context=SimpleNamespace(context_id=context.context_id,capability='invalid')
    elif proof=='foreign':context=SimpleNamespace(context_id=uuid4(),capability=context.capability)
    else:
        from jose import jwt
        claims=activity.decode_capability('Bearer '+context.capability);claims['iat']-=1801;claims['exp']-=1801
        context=SimpleNamespace(context_id=context.context_id,capability=jwt.encode(claims,settings.SECRET_KEY,algorithm=settings.JWT_ALGORITHM))
    oid,payload=await place(sessions,bid,sku,context)
    async with sessions() as db:
        row=await db.get(OrderActivity,oid)
        assert row.classification=='unknown' and row.context_id is None
        assert (await db.get(CommerceOrder,oid)).payment_status=='pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['gateway','native','deployment','context'])
async def test_known_test_evidence_always_excludes_order(sessions,monkeypatch,source):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    if source=='deployment':monkeypatch.setattr(settings,'APP_ENV','test')
    if source=='context':
        async with sessions.begin() as db:context=await activity.start_context(db,bid,ContextWrite(idempotency_key=uuid4()),native=True)
    async with sessions.begin() as db:
        store=await checkout_v1.lock_store(db,bid)
        order,_=await checkout_v1.create_sku_order(db,store,checkout(sku))
        if source=='gateway':order.gateway_credentials={'mode':'test'};await db.flush()
        await activity.record_order(db,order,context_id=context.context_id,authorization='Bearer '+context.capability,native=source=='native')
        assert (await db.get(OrderActivity,order.id)).classification=='test'


@pytest.mark.asyncio
async def test_supported_complete_context_cohort_counts_and_current_placement_conversion(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    # Seed an explicit earlier owner-consent chronology BEFORE contexts; raw SQL
    # update is forbidden, so use a fresh second tenant with original timestamps.
    second,pid2,ids2=await seed(sessions,stock=20)
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    async with sessions.begin() as db:
        at=start-timedelta(days=1)
        db.add(ActivityPolicy(business_id=second,mode='live',revision=1,updated_at=at))
        db.add(ActivityPolicyCommand(business_id=second,idempotency_key=uuid4(),actor_user_id=legacy_owner_id(second),
            request_hash='a'*64,mode='live',revision=1,notice_version='first-party.v1',created_at=at))
        await db.flush()
        context=await activity.start_context(db,second,ContextWrite(idempotency_key=uuid4()))
        await activity.accept_event(db,second,'Bearer '+context.capability,EventWrite(event_kind='product_view',product_id=pid2))
        await activity.accept_event(db,second,'Bearer '+context.capability,EventWrite(event_kind='checkout_opened'))
    first,_=await place(sessions,second,ids2[0],context)
    await place(sessions,second,ids2[0],context)
    await place(sessions,second,ids2[0]) # unknown excluded, never merged into live
    async with sessions.begin() as db:
        order=await db.get(CommerceOrder,first);order.fulfillment_status='cancelled';order.payment_status='cancelled'
    async with sessions() as db:
        report=await activity.report(db,second,start.date(),start.date()+timedelta(days=1))
        assert report.coverage.state=='available'
        assert report.counts.model_dump()==dict(visits=1,product_views=1,checkout_starts=1,accepted_placements=2)
        assert report.conversion.numerator==1 and report.conversion.denominator==1 and report.conversion.percentage=='100.00'
        assert report.production_orders.placed==2 and report.production_orders.cancelled==1
        assert report.production_orders.excluded_unclassified==1 and report.production_orders.state=='partial'
        assert report.production_orders.currency_totals[0].placed_order_value_minor=='259800'
        assert report.channel_activity.enquiry_messages is None


@pytest.mark.asyncio
async def test_foreign_product_unactivated_product_and_event_duplicates_concurrent(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    foreign,foreign_pid,_=await seed(sessions)
    private,private_pid,_=await seed(sessions,activate=False)
    async with sessions() as db:
        for product in (foreign_pid,private_pid):
            with pytest.raises(HTTPException) as error:
                await activity.accept_event(db,bid,'Bearer '+context.capability,EventWrite(event_kind='product_view',product_id=product))
            assert error.value.status_code==404
    async def send():
        async with sessions.begin() as db:return await activity.accept_event(db,bid,'Bearer '+context.capability,EventWrite(event_kind='product_view',product_id=pid))
    result=await asyncio.wait_for(asyncio.gather(send(),send()),5)
    assert sorted(r.replayed for r in result)==[False,True]


@pytest.mark.asyncio
async def test_two_same_revision_policy_writers_only_one_commits(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async def change(mode):
        try:
            async with sessions.begin() as db:
                await activity.change_policy(db,bid,actor,PolicyWrite(expected_revision=1,idempotency_key=uuid4(),mode=mode,first_party_measurement_acknowledged=True))
            return 'saved'
        except HTTPException as error:
            assert error.status_code==409;return 'stale'
    assert sorted(await asyncio.wait_for(asyncio.gather(change('off'),change('test')),5))==['saved','stale']


@pytest.mark.asyncio
async def test_cleanup_ungated_and_lifetime_order_link_survives_raw_deletion(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    # Original raw facts are expired, canonical order chronology is explicit.
    old=datetime.now(timezone.utc)-timedelta(days=91)
    other,_,other_skus=await seed(sessions)
    async with sessions.begin() as db:
        db.add(ActivityPolicy(business_id=other,mode='live',revision=1,updated_at=old-timedelta(seconds=1)))
        db.add(ActivityPolicyCommand(business_id=other,idempotency_key=uuid4(),actor_user_id=legacy_owner_id(other),request_hash='b'*64,
            mode='live',revision=1,notice_version='first-party.v1',created_at=old-timedelta(seconds=1)))
        await db.flush()
        raw=ActivityContext(business_id=other,idempotency_key=uuid4(),classification='live',reason='live_policy',policy_revision=1,
            started_at=old,expires_at=old+timedelta(minutes=30),retained_until=old+timedelta(days=90))
        db.add(raw);await db.flush();cid=raw.id
        store=await checkout_v1.lock_store(db,other)
        order,_=await checkout_v1.create_sku_order(db,store,checkout(other_skus[0]))
        order.created_at=old+timedelta(seconds=1);await db.flush()
        oid=order.id
        db.add(OrderActivity(order_id=oid,business_id=other,classification='live',reason='live_context',context_id=cid,accepted_at=order.created_at))
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',False)
    async with sessions.begin() as db:
        result=await activity.delete_expired(db)
        assert result['v1_activity_contexts']==1
    async with sessions() as db:
        assert await db.get(ActivityContext,cid) is None
        assert (await db.get(OrderActivity,oid)).context_id==cid
        assert await db.get(CommerceOrder,oid) is not None


@pytest.mark.asyncio
async def test_product_view_fk_lock_cannot_invert_canonical_checkout_context_lock(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    from app.models.product import Product
    async with sessions.begin() as checkout_db:
        store=await checkout_v1.lock_store(checkout_db,bid)
        await checkout_db.scalar(select(Product.id).where(Product.id==pid).with_for_update())
        async def view():
            async with sessions.begin() as event_db:
                return await activity.accept_event(event_db,bid,'Bearer '+context.capability,
                    EventWrite(event_kind='product_view',product_id=pid))
        waiting=asyncio.create_task(view())
        try:
            for _ in range(100):
                async with sessions() as observer:
                    count=await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%products%'"))
                if count:break
                await asyncio.sleep(.01)
            assert count
            order,_=await checkout_v1.create_sku_order(checkout_db,store,checkout(sku))
            # If event already held Context while waiting for its Product FK,
            # this wait would form a true cycle/deadlock against checkout.
            await asyncio.wait_for(activity.record_order(checkout_db,order,
                context_id=context.context_id,authorization='Bearer '+context.capability),2)
        except BaseException:
            waiting.cancel();await asyncio.gather(waiting,return_exceptions=True);raise
    result=await asyncio.wait_for(waiting,3)
    assert result.state=='accepted'


@pytest.mark.asyncio
async def test_live_to_test_policy_cannot_reuse_old_live_context_for_production(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async with sessions.begin() as db:
        old=await db.get(ActivityContext,context.context_id)
        await activity.change_policy(db,bid,actor,PolicyWrite(expected_revision=1,idempotency_key=uuid4(),mode='test',first_party_measurement_acknowledged=True))
        result=await activity.start_context(db,bid,ContextWrite(idempotency_key=old.idempotency_key))
        assert result.state=='excluded'
        event=await activity.accept_event(db,bid,'Bearer '+context.capability,EventWrite(event_kind='checkout_opened'))
        assert event.state=='disabled'
    oid,_=await place(sessions,bid,sku,context)
    async with sessions() as db:
        row=await db.get(OrderActivity,oid)
        assert row.classification=='test' and row.context_id is None
        assert (await db.get(ActivityContext,context.context_id)).classification=='live' # immutable original


@pytest.mark.asyncio
async def test_utc_context_start_cohort_separates_next_day_accepted_order_cohort(sessions,monkeypatch):
    # Synthetic original chronology, seeded against the actual immutable schema:
    # context23:59UTC -> order00:10UTC, inside the original30-minute context.
    # Context conversion belongs to the first day; order value to the second.
    from app.config import settings
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',True)
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',True)
    bid,pid,skus=await seed(sessions)
    day=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=2)
    context_start=day+timedelta(hours=23,minutes=59)
    accepted=day+timedelta(days=1,minutes=10)
    async with sessions.begin() as db:
        db.add(ActivityPolicy(business_id=bid,mode='live',revision=1,updated_at=day-timedelta(days=1)))
        db.add(ActivityPolicyCommand(business_id=bid,idempotency_key=uuid4(),actor_user_id=legacy_owner_id(bid),
            request_hash='c'*64,mode='live',revision=1,notice_version='first-party.v1',created_at=day-timedelta(days=1)))
        await db.flush()
        context=ActivityContext(business_id=bid,idempotency_key=uuid4(),classification='live',reason='live_policy',policy_revision=1,
            started_at=context_start,expires_at=context_start+timedelta(minutes=30),retained_until=context_start+timedelta(days=90))
        db.add(context);await db.flush()
        store=await checkout_v1.lock_store(db,bid)
        order,_=await checkout_v1.create_sku_order(db,store,checkout(skus[0]));order.created_at=accepted;await db.flush()
        db.add(OrderActivity(order_id=order.id,business_id=bid,classification='live',reason='live_context',context_id=context.id,accepted_at=accepted))
    async with sessions() as db:
        first=await activity.report(db,bid,day.date(),(day+timedelta(days=1)).date())
        second=await activity.report(db,bid,(day+timedelta(days=1)).date(),(day+timedelta(days=2)).date())
        assert first.counts.visits==1 and first.counts.accepted_placements==1 and first.conversion.percentage=='100.00'
        assert first.production_orders.placed==0
        assert second.counts.visits==0 and second.conversion.percentage is None
        assert second.conversion.unavailable_reason=='no_observed_contexts'
        assert second.production_orders.placed==1
