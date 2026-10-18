"""Prepared actual-PG gates; run only under the allocated P01 serial lease.

Transport-free domain calls are real; no provider acceptance is fabricated by
these tests. Separate sender regressions own the canonical outcome transitions.
"""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import func,select,text
from app.models.activity_v1 import ActivityPolicy,ActivityPolicyCommand,ActivitySource
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppMessage
from app.services import activity_v1 as activity,activity_producers as hooks,instagram_ingress,whatsapp
from app.services.identity import legacy_owner_id
from tests.test_v1_checkout import sessions,seed
from tests.test_v1_activity_sources import inbound
from tests.test_v1_native_completion_import_http import native_import


async def prepared(sessions,monkeypatch,*,policy_age=timedelta(hours=1)):
    from app.config import settings
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',True)
    monkeypatch.setattr(settings,'APP_ENV','production')
    bid,pid,skus=await seed(sessions)
    async with sessions.begin() as db:
        at=await activity.clock(db)-policy_age
        db.add(ActivityPolicy(business_id=bid,mode='live',revision=1,updated_at=at))
        db.add(ActivityPolicyCommand(business_id=bid,idempotency_key=uuid4(),actor_user_id=legacy_owner_id(bid),
            request_hash='a'*64,mode='live',revision=1,notice_version='first-party.v1',created_at=at))
        seller=await db.get(Seller,bid);seller.instagram_page_id='synthetic-account'
        db.add(WhatsAppAccount(seller_id=bid,phone_number_id='synthetic-phone',waba_id='synthetic-waba',
            access_token='unused-synthetic-ciphertext',enabled=True,automation_enabled=False))
    return bid


@pytest.mark.asyncio
async def test_real_sql_ledger_failure_cannot_drop_ig_ack_or_create_duplicate(sessions,monkeypatch):
    bid=await prepared(sessions,monkeypatch)
    async def ledger_error(db,*args,**kwargs):await db.execute(text('SELECT 1/0'))
    monkeypatch.setattr(activity,'record_source',ledger_error)
    event={'sender':{'id':'synthetic-customer'},'recipient':{'id':'synthetic-account'},
        'message':{'mid':'synthetic-mid','text':'private-marker'}}
    for _ in range(2):
        async with sessions() as db:
            receipt=await instagram_ingress.persist_message(db,event)
            assert receipt.seller_id==bid
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(InstagramIngress))==1
        assert await db.scalar(select(func.count()).select_from(ActivitySource))==0


@pytest.mark.asyncio
@pytest.mark.parametrize('channel',['instagram','whatsapp'])
async def test_signed_actual_main_ack_survives_real_ledger_sql_error(native_import,sessions,monkeypatch,channel):
    import hashlib,hmac,json
    from app.config import settings
    from app.database import get_db
    from app.main import app
    from app.workers.instagram_ingress import process_instagram_ingress
    j=native_import;bid=await prepared(sessions,monkeypatch)
    # Match production get_db: explicit durable webhook commits are permitted,
    # followed by outer cleanup. Do not wrap the whole handler in sessions.begin.
    async def database():
        async with j.sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
    app.dependency_overrides[get_db]=database
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','synthetic-signature-secret')
    monkeypatch.setattr(settings,'WHATSAPP_APP_SECRET','synthetic-signature-secret')
    monkeypatch.setattr(process_instagram_ingress,'apply_async',lambda *a,**kw:None)
    async def ledger_error(db,*args,**kwargs):await db.execute(text('SELECT 1/0'))
    monkeypatch.setattr(activity,'record_source',ledger_error)
    if channel=='instagram':
        payload={'object':'instagram','entry':[{'id':'synthetic-account','messaging':[
            {'sender':{'id':'synthetic-customer'},'recipient':{'id':'synthetic-account'},
             'message':{'mid':'synthetic-mid','text':'private-marker'}}]}]}
        model=InstagramIngress
    else:
        payload={'object':'whatsapp_business_account','entry':[{'id':'synthetic-waba','changes':[
            {'field':'messages','value':{'metadata':{'phone_number_id':'synthetic-phone'},'messages':[
                {'id':'synthetic-mid','from':'919876543210','timestamp':str(int(whatsapp.now().timestamp())),
                 'type':'text','text':{'body':'private-marker'}}]}}]}]}
        model=WhatsAppMessage
    raw=json.dumps(payload).encode()
    signature='sha256='+hmac.new(b'synthetic-signature-secret',raw,hashlib.sha256).hexdigest()
    for _ in range(2):
        response=await j.client.post('/webhooks/'+channel,content=raw,headers={'x-hub-signature-256':signature})
        assert response.status_code==200 and response.json()=={'status':'ok'}
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(model).where(model.seller_id==bid))==1
        assert await db.scalar(select(func.count()).select_from(ActivitySource))==0


@pytest.mark.asyncio
async def test_real_sql_ledger_failure_preserves_wa_inbound_and_outbox_exact_replay(sessions,monkeypatch):
    bid=await prepared(sessions,monkeypatch)
    async def ledger_error(db,*args,**kwargs):await db.execute(text('SELECT 1/0'))
    monkeypatch.setattr(activity,'record_source',ledger_error)
    event={'id':'synthetic-mid','from':'919876543210','timestamp':str(int(whatsapp.now().timestamp())),
        'type':'text','text':{'body':'private-marker'}}
    async with sessions.begin() as db:
        previous=(await db.execute(text("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"))).one()
        account=await db.get(WhatsAppAccount,bid)
        await whatsapp.ingest_message(db,account,{},event)
        await whatsapp.ingest_message(db,account,{},event)
        contact=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id==bid))
        first=await whatsapp.queue_message(db,account,contact,key='synthetic-exact-key',text='private-outbound',
            activity_producer=hooks.AutomatedWhatsAppProducer.INBOUND_REPLY)
        second=await whatsapp.queue_message(db,account,contact,key='synthetic-exact-key',text='private-outbound',
            activity_producer=hooks.AutomatedWhatsAppProducer.INBOUND_REPLY)
        assert first.id==second.id
        assert (await db.execute(text("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"))).one()==previous
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==2
        assert await db.scalar(select(func.count()).select_from(ActivitySource))==0


@pytest.mark.asyncio
async def test_owner_policy_lock_contention_cannot_block_durable_outbox_commit(sessions,monkeypatch):
    import asyncio
    bid=await prepared(sessions,monkeypatch)
    async with sessions.begin() as blocker:
        await blocker.scalar(select(ActivityPolicy).where(ActivityPolicy.business_id==bid).with_for_update())
        async def queue_while_locked():
            async with sessions.begin() as db:
                previous=(await db.execute(text("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"))).one()
                account=await db.get(WhatsAppAccount,bid)
                contact=WhatsAppContact(seller_id=bid,phone='919876543210',last_inbound_at=whatsapp.now())
                db.add(contact);await db.flush()
                row=await whatsapp.queue_message(db,account,contact,key='policy-contention',text='private-marker',
                    activity_producer=hooks.AutomatedWhatsAppProducer.ORDER_UPDATE)
                assert (await db.execute(text("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"))).one()==previous
                return row.id
        mid=await asyncio.wait_for(queue_while_locked(),2)
        # Independent observer sees the committed domain fact while the owner
        # still holds its policy lock. Measurement may be absent, never retried.
        async with sessions() as db:
            assert (await db.get(WhatsAppMessage,mid)).status=='queued'
            assert await db.scalar(select(func.count()).select_from(ActivitySource))==0


@pytest.mark.asyncio
async def test_installed_hooks_record_only_new_rows_and_do_not_backfill_lost_measurements(sessions,monkeypatch):
    bid=await prepared(sessions,monkeypatch)
    event={'sender':{'id':'synthetic-customer'},'recipient':{'id':'synthetic-account'},
        'message':{'mid':'synthetic-mid','text':'private-marker'}}
    for _ in range(2):
        async with sessions() as db:await instagram_ingress.persist_message(db,event)
    async with sessions.begin() as db:
        account=await db.get(WhatsAppAccount,bid)
        contact=WhatsAppContact(seller_id=bid,phone='919876543210',last_inbound_at=whatsapp.now())
        db.add(contact);await db.flush()
        for _ in range(2):
            await whatsapp.queue_message(db,account,contact,key='synthetic-auto',text='private-marker',
                activity_producer=hooks.AutomatedWhatsAppProducer.INBOUND_REPLY)
        await whatsapp.queue_message(db,account,contact,key='auto:misleading-manual-prefix',text='private-marker')
    async with sessions() as db:
        rows=(await db.scalars(select(ActivitySource))).all()
        assert sorted((r.source_kind,r.classification) for r in rows)==[
            ('instagram_ingress','live'),('wa_outbound','live'),('wa_outbound','unknown')]


@pytest.mark.asyncio
async def test_delayed_inbound_uses_documented_per_source_time_and_replay_never_moves_cohort(sessions,monkeypatch):
    bid=await prepared(sessions,monkeypatch,policy_age=timedelta(days=3))
    old=whatsapp.now()-timedelta(days=1)
    event={'id':'delayed-wa-mid','from':'919876543210','timestamp':str(int(old.timestamp())),
        'type':'text','text':{'body':'private-marker'}}
    for _ in range(2):
        async with sessions.begin() as db:
            await whatsapp.ingest_message(db,await db.get(WhatsAppAccount,bid),{},event)
    ig={'sender':{'id':'synthetic-customer'},'recipient':{'id':'synthetic-account'},
        'timestamp':int(old.timestamp()*1000),'message':{'mid':'delayed-ig-mid','text':'private-marker'}}
    for _ in range(2):
        async with sessions() as db:await instagram_ingress.persist_message(db,ig)
    async with sessions() as db:
        at=await activity.clock(db)
        today=await activity.report(db,bid,at.date(),at.date()+timedelta(days=1))
        prior=await activity.report(db,bid,old.date(),old.date()+timedelta(days=1))
        assert today.channel_activity.included_source_kinds==['instagram_ingress']
        assert today.channel_activity.enquiry_messages==1
        assert prior.channel_activity.included_source_kinds==['wa_inbound']
        assert prior.channel_activity.enquiry_messages==1
        assert await db.scalar(select(func.count()).select_from(ActivitySource))==2


@pytest.mark.asyncio
async def test_report_uses_guarded_source_cohort_current_canonical_states_and_excludes_test_manual(sessions,monkeypatch):
    bid=await prepared(sessions,monkeypatch)
    async with sessions.begin() as db:
        ids=[await inbound(db,bid,kind='outbound') for _ in range(5)]
        for sid in ids[:3]:assert await activity.record_source(db,bid,'wa_outbound',sid,origin='automated',is_new=True)
        assert await activity.record_source(db,bid,'wa_outbound',ids[3],origin='operator',is_new=True)
        assert await activity.record_source(db,bid,'wa_outbound',ids[4],origin='automated',is_new=True,test_evidence=True)
        messages=[await db.get(WhatsAppMessage,sid) for sid in ids]
        messages[1].status='unknown'
        messages[2].status='unknown';messages[2].provider_message_id='synthetic-canonical-receipt'
        marker=await db.get(ActivitySource,(bid,'wa_outbound',ids[0]))
        assert marker.created_at==messages[0].created_at
        assert marker.retained_until-marker.created_at==timedelta(days=90)
    async with sessions() as db:
        at=await activity.clock(db)
        value=await activity.report(db,bid,at.date(),at.date()+timedelta(days=1))
        channel=value.channel_activity
        assert channel.reason=='partial_coverage' and channel.included_source_kinds==['wa_outbound']
        assert channel.enquiry_messages is None
        assert channel.excluded_test==1 and channel.excluded_unclassified==1
        assert channel.automation_outcomes.model_dump()==dict(queued=1,sending=0,accepted=1,failed=0,unknown=1,
            instagram_sends=None,resolved_enquiries=None)
        encoded=value.model_dump_json()
        for secret in ('private-marker','private-source-body-marker','synthetic-canonical-receipt','synthetic-phone'):
            assert secret not in encoded
