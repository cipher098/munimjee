"""Real0052/P01 service state, uniqueness and current account proofs; no sends."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import DBAPIError
from app.config import settings
from app.models.customer_links import Customer, CustomerLinkChallenge as Challenge, CustomerLinkProof as Proof, CustomerAssociation as Association, CustomerLinkAudit as Audit
from app.models.seller import Seller
from app.models.identity import Business, User, Membership
from app.models.conversation import Conversation
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.services.identity import Actor
from app.services import customer_links as service
from app.schemas.customer_links import Start, Finish, Unlink


@pytest_asyncio.fixture
async def customer_lane(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, 'V1_CUSTOMER_LINKS_ENABLED', True)
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    bid, uid, conversation, contact = (uuid4() for _ in range(4))
    async with sessions.begin() as db:
        db.add(Seller(id=bid,email=f'{uuid4()}@example.com',password_hash='synthetic',is_active=True,
            instagram_id=uuid4().hex,instagram_page_id=uuid4().hex,instagram_token='synthetic-never-provider-token'))
        await db.flush()
        db.add_all([Business(id=bid,name='Synthetic linked accounts',is_active=True),User(id=uid,is_active=True,auth_version=0)])
        await db.flush()
        db.add_all([Membership(business_id=bid,user_id=uid,role='owner',is_active=True),
            Conversation(id=conversation,seller_id=bid,customer_instagram_id='synthetic-ig-subject',customer_name='Same synthetic name',messages=[{'role':'customer','content':'historic synthetic enquiry'}]),
            WhatsAppAccount(seller_id=bid,phone_number_id=uuid4().hex,waba_id=uuid4().hex,access_token='synthetic-encrypted-token',enabled=False),
            WhatsAppContact(id=contact,seller_id=bid,phone='919876543210',name='Same synthetic name',utility_opt_in=False,marketing_opt_in=False)])
    return SimpleNamespace(sessions=sessions,bid=bid,uid=uid,conversation=conversation,contact=contact,actor=Actor(uid,'v1_user'))


async def create(j):
    body=Start(idempotency_key=uuid4(),conversation_id=j.conversation,contact_id=j.contact,scope_confirmed=True)
    async with j.sessions.begin() as db:
        row=await service.start(db,j.actor,j.bid,body)
        cid,command=row.id,f'LINK {service.secret_for(row)} I CONSENT'
    return cid,command,body


async def proof(j,cid,command,channel,**override):
    async with j.sessions.begin() as db:
        row=await service.challenge_for(db,j.bid,cid)
        account,subject=(row.instagram_account,row.instagram_subject) if channel=='instagram' else (row.whatsapp_account,row.whatsapp_subject)
        arguments=dict(business_id=j.bid,channel=channel,account_id=account,subject_id=subject,mid=uuid4().hex,provider_at=service.now(),content=command)
        arguments.update(override)
        assert await service.capture(db,**arguments)


async def final_body(j,cid):
    async with j.sessions() as db:
        row=await service.challenge_for(db,j.bid,cid)
        return Finish(idempotency_key=uuid4(),expected_fingerprint=await service.fingerprint(db,row),confirmed=True)


@pytest.mark.asyncio
async def test_real_chain_and_hash_only_proofs_explicit_finalize_and_unlink_preserve_history(customer_lane):
    j=customer_lane;cid,command,body=await create(j)
    async with j.sessions() as db:
        assert await db.scalar(text('select version_num from alembic_version'))=='0052_v1_customer_links'
        row=await service.challenge_for(db,j.bid,cid)
        assert command.split()[1] not in str(row.__dict__)
        assert not (await service.view(db,row))['proofs']
        assert await service.verified_customer_id(db,j.bid,'instagram',row.instagram_account,row.instagram_subject) is None
    await proof(j,cid,command,'instagram');pending=await final_body(j,cid)
    with pytest.raises(HTTPException) as exc:
        async with j.sessions.begin() as db:await service.finish(db,j.actor,j.bid,cid,pending)
    assert exc.value.status_code==409
    await proof(j,cid,command,'whatsapp');complete=await final_body(j,cid)
    async with j.sessions.begin() as db:
        result=await service.finish(db,j.actor,j.bid,cid,complete)
        customer=UUID(result['customer_id'])
    async with j.sessions.begin() as db:
        assert await service.finish(db,j.actor,j.bid,cid,complete)==result
        row=await service.challenge_for(db,j.bid,cid)
        assert await service.verified_customer_id(db,j.bid,'instagram',row.instagram_account,row.instagram_subject)==customer
        fp,_=await service.association_fingerprint(db,j.bid,customer)
        unlink=Unlink(idempotency_key=uuid4(),expected_fingerprint=fp,confirmed=True,reason='Synthetic customer requested account separation')
        await service.unlink(db,j.actor,j.bid,customer,unlink)
    async with j.sessions() as db:
        assert await service.verified_customer_id(db,j.bid,'instagram',row.instagram_account,row.instagram_subject) is None
        assert (await db.get(Conversation,j.conversation)).messages==[{'role':'customer','content':'historic synthetic enquiry'}]
        contact=await db.get(WhatsAppContact,j.contact)
        assert not contact.utility_opt_in and not contact.marketing_opt_in
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0
        assert await db.scalar(select(func.count()).select_from(Proof))==2
        assert await db.scalar(select(func.count()).select_from(Audit))==3


@pytest.mark.asyncio
@pytest.mark.parametrize('bad',['wrong_sender','wrong_account','old','future','attachments','nonexact','expired','changed_config'])
async def test_invalid_proof_never_establishes_control(customer_lane,bad,monkeypatch):
    j=customer_lane;cid,command,_=await create(j);override={}
    if bad=='wrong_sender':override['subject_id']='other-subject'
    if bad=='wrong_account':override['account_id']='other-account'
    if bad=='old':override['provider_at']=service.now()-timedelta(minutes=1)
    if bad=='future':override['provider_at']=service.now()+timedelta(minutes=2)
    if bad=='attachments':override['attachments']=True
    if bad=='nonexact':override['content']=command+'\n'
    if bad=='expired':monkeypatch.setattr(service,'now',lambda:base+timedelta(minutes=11)) if (base:=service.now()) else None
    if bad=='changed_config':
        async with j.sessions.begin() as db:await db.execute(update(Seller).where(Seller.id==j.bid).values(instagram_token='reconnected-new-token'))
    await proof(j,cid,command,'instagram',**override)
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(Proof))==0


@pytest.mark.asyncio
async def test_signed_event_ledger_dedupes_and_cancelled_proof_cannot_be_reused(customer_lane):
    j=customer_lane;cid,command,_=await create(j);mid=uuid4().hex
    await proof(j,cid,command,'instagram',mid=mid);await proof(j,cid,command,'instagram',mid=mid)
    cancel=await final_body(j,cid)
    async with j.sessions.begin() as db:await service.finish(db,j.actor,j.bid,cid,cancel,cancel=True)
    second,command2,_=await create(j)
    await proof(j,second,command2,'instagram',mid=mid)
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Proof))==1
        assert not await service.proofs_for(db,await service.challenge_for(db,j.bid,second))


@pytest.mark.asyncio
async def test_two_concurrent_finalizations_of_same_endpoints_have_one_customer(customer_lane):
    j=customer_lane;one,c1,_=await create(j);two,c2,_=await create(j)
    for cid,command in [(one,c1),(two,c2)]:
        await proof(j,cid,command,'instagram');await proof(j,cid,command,'whatsapp')
    bodies=[await final_body(j,one),await final_body(j,two)]
    async def finish(cid,body):
        try:
            async with j.sessions.begin() as db:await service.finish(db,j.actor,j.bid,cid,body)
            return 'verified'
        except HTTPException as exc:return exc.status_code
    results=await asyncio.wait_for(asyncio.gather(finish(one,bodies[0]),finish(two,bodies[1])),10)
    assert sorted(map(str,results))==['409','verified']
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customer))==1
        assert await db.scalar(select(func.count()).select_from(Association))==2


@pytest.mark.asyncio
async def test_proof_and_audit_immutable_and_tenant_fk_enforced(customer_lane):
    j=customer_lane;cid,command,_=await create(j);await proof(j,cid,command,'instagram')
    for table in ['v1_customer_link_proofs','v1_customer_link_audits']:
        with pytest.raises(DBAPIError):
            async with j.sessions.begin() as db:await db.execute(text(f'DELETE FROM {table}'))
    with pytest.raises(DBAPIError):
        async with j.sessions.begin() as db:
            db.add(Proof(business_id=uuid4(),challenge_id=cid,channel='instagram',account_id='a',subject_id='s',provider_message_id='m',provider_at=service.now(),received_at=service.now()));await db.flush()
