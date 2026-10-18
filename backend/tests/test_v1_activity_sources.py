"""Future producer seam: real source rows/tenant checks, no provider payload copy."""
import asyncio
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import func,select
from sqlalchemy.exc import IntegrityError
from app.models.activity_v1 import ActivitySource
from app.models.instagram_ingress import InstagramIngress
from app.models.whatsapp import WhatsAppContact,WhatsAppMessage
from app.schemas.activity_v1 import PolicyWrite
from app.services import activity_v1 as activity
from tests.test_v1_checkout import sessions,seed
from tests.test_v1_activity_orders import setup


async def inbound(db,bid,*,kind='instagram',mid=True,old=False):
    at=await activity.clock(db)
    if old:at-=timedelta(days=1)
    if kind=='instagram':
        row=InstagramIngress(seller_id=bid,account_id='synthetic-account',customer_id='private-customer-marker',
            event_key=uuid4().hex,provider_message_id=uuid4().hex if mid else None,
            events=[{'text':'private-source-body-marker'}],available_at=at,created_at=at)
    else:
        contact=WhatsAppContact(seller_id=bid,phone=uuid4().hex[:20],name='Private contact marker')
        db.add(contact);await db.flush()
        row=WhatsAppMessage(seller_id=bid,contact_id=contact.id,phone_number_id='synthetic-phone',
            provider_message_id=uuid4().hex if mid else None,idempotency_key=uuid4().hex,
            direction='inbound' if kind=='whatsapp' else 'outbound',text='private-source-body-marker',
            payload={'sensitive':'private-payload-marker'},status='received' if kind=='whatsapp' else 'queued',created_at=at)
    db.add(row);await db.flush();return row.id


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,source',[('instagram','instagram_ingress'),('whatsapp','wa_inbound')])
async def test_new_deduplicated_inbound_tenant_source_is_minimal_and_immutable(sessions,monkeypatch,kind,source):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async with sessions.begin() as db:
        sid=await inbound(db,bid,kind=kind)
        assert await activity.record_source(db,bid,source,sid,origin='inbound',is_new=True)
        assert not await activity.record_source(db,bid,source,sid,origin='inbound',is_new=True,test_evidence=True)
        marker=await db.get(ActivitySource,(bid,source,sid))
        assert marker.classification=='live' and marker.origin=='inbound'
        assert set(marker.__table__.columns.keys())=={'business_id','source_kind','source_id','classification','origin','created_at','retained_until'}
        foreign=uuid4()
        assert not await activity.record_source(db,foreign,source,sid,origin='inbound',is_new=True)
    async with sessions.begin() as db:
        await activity.change_policy(db,bid,actor,PolicyWrite(expected_revision=1,idempotency_key=uuid4(),mode='test',first_party_measurement_acknowledged=True))
        assert not await activity.record_source(db,bid,source,sid,origin='inbound',is_new=True,test_evidence=True)
        assert (await db.get(ActivitySource,(bid,source,sid))).classification=='live'


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['historical','replay','missing_mid','wrong_kind'])
async def test_unproven_historical_or_replayed_sources_are_not_backfilled(sessions,monkeypatch,case):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async with sessions.begin() as db:
        sid=await inbound(db,bid,mid=case!='missing_mid',old=case=='historical')
        source='wa_inbound' if case=='wrong_kind' else 'instagram_ingress'
        assert not await activity.record_source(db,bid,source,sid,origin='inbound',is_new=case!='replay')
        assert await db.scalar(select(func.count()).select_from(ActivitySource))==0


@pytest.mark.asyncio
async def test_new_manual_and_known_test_outbound_cannot_become_live_automation(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async with sessions.begin() as db:
        manual=await inbound(db,bid,kind='outbound');automated=await inbound(db,bid,kind='outbound')
        assert await activity.record_source(db,bid,'wa_outbound',manual,origin='operator',is_new=True)
        assert await activity.record_source(db,bid,'wa_outbound',automated,origin='automated',is_new=True,test_evidence=True)
        assert (await db.get(ActivitySource,(bid,'wa_outbound',manual))).classification=='unknown'
        assert (await db.get(ActivitySource,(bid,'wa_outbound',automated))).classification=='test'
        with pytest.raises(ValueError):await activity.record_source(db,bid,'wa_outbound',manual,origin='inbound',is_new=True)
        with pytest.raises(ValueError):await activity.record_source(db,bid,'wa_outbound',manual,origin='automated',is_new=1)
    # Helper existence / a single tagged row is not installed producer coverage.
    async with sessions() as db:
        now=await activity.clock(db)
        report=await activity.report(db,bid,now.date(),now.date()+timedelta(days=1))
        assert report.channel_activity.enquiry_messages is None
        assert report.channel_activity.automation_outcomes is None
        assert report.channel_activity.reason=='producer_not_installed'


@pytest.mark.asyncio
async def test_competing_source_hooks_only_insert_once(sessions,monkeypatch):
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    async with sessions.begin() as db:sid=await inbound(db,bid)
    async def mark():
        async with sessions.begin() as db:return await activity.record_source(db,bid,'instagram_ingress',sid,origin='inbound',is_new=True)
    assert sorted(await asyncio.wait_for(asyncio.gather(mark(),mark()),5))==[False,True]


@pytest.mark.asyncio
async def test_channel_source_gate_is_separate_from_public_storefront(sessions,monkeypatch):
    from app.config import settings
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',False)
    async with sessions.begin() as db:
        sid=await inbound(db,bid)
        assert await activity.record_source(db,bid,'instagram_ingress',sid,origin='inbound',is_new=True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',False)
    async with sessions.begin() as db:
        sid=await inbound(db,bid)
        assert not await activity.record_source(db,bid,'instagram_ingress',sid,origin='inbound',is_new=True)


@pytest.mark.asyncio
async def test_comment_source_requires_both_action_and_event_tenant(sessions,monkeypatch):
    from app.models.comment_automation import CommentAction,CommentEvent
    bid,pid,sku,actor,context=await setup(sessions,monkeypatch)
    foreign,_,_=await seed(sessions)
    async with sessions.begin() as db:
        own_event=CommentEvent(seller_id=bid,comment_id=uuid4().hex,media_id='synthetic',actor_id='private',text='private-comment',status='queued')
        foreign_event=CommentEvent(seller_id=foreign,comment_id=uuid4().hex,media_id='synthetic',actor_id='private',text='private-comment',status='queued')
        db.add_all([own_event,foreign_event]);await db.flush()
        own=CommentAction(seller_id=bid,event_id=own_event.id,kind='private',body='private-reply-marker')
        db.add(own);await db.flush()
        # 0055 now prevents constructing a cross-tenant action in the first place.
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(CommentAction(seller_id=bid,event_id=foreign_event.id,kind='private',body='foreign-private-reply-marker'))
                await db.flush()
        foreign_action=CommentAction(seller_id=foreign,event_id=foreign_event.id,kind='private',body='foreign-private-reply-marker')
        db.add(foreign_action);await db.flush()
        assert await activity.record_source(db,bid,'comment_action',own.id,origin='automated',is_new=True)
        assert not await activity.record_source(db,bid,'comment_action',foreign_action.id,origin='automated',is_new=True)
