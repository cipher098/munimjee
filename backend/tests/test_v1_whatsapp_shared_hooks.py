"""No-network shared-hook boundary checks; actual0057 proof remains separate."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_reserved_test_interception_precedes_ordinary_identifier_and_transcript_work(monkeypatch):
    from app.services.whatsapp import ingest_message
    from app.services import whatsapp_test_authority
    seen=[]
    async def intercept(db,account,event):
        seen.append(event)
        return True
    monkeypatch.setattr(whatsapp_test_authority,'intercept_reserved',intercept)
    class NoOrdinaryReads:
        async def scalar(self,*args,**kwargs):
            raise AssertionError('Reserved packet entered ordinary processing')
    packet={'id':'malformed reserved packet','type':'image'}
    await ingest_message(NoOrdinaryReads(),SimpleNamespace(),{},packet)
    assert seen==[packet]


@pytest.mark.asyncio
@pytest.mark.parametrize('exact_fk',[False,True])
async def test_paused_account_requires_exact_authorization_not_a_test_shaped_key(monkeypatch,exact_fk):
    from app.workers.whatsapp import deliver_one
    from app.services import whatsapp as service, whatsapp_provider, whatsapp_test_authority
    message=SimpleNamespace(id=uuid4(),seller_id=uuid4(),contact_id=uuid4(),status='queued',
        idempotency_key='connection-test:looks-valid',phone_number_id='123',kind='text',text='fixed',
        payload={},provider_message_id=None,error=None)
    account=SimpleNamespace(phone_number_id='123',enabled=False,automation_enabled=False)
    contact=SimpleNamespace(opted_out=False)
    sessions=0; calls=[]
    class DB:
        def __init__(self,claim): self.claim=claim
        async def scalar(self,*args,**kwargs):
            return message if not self.claim or message.status=='queued' else None
        async def get(self,*args): return message
        async def commit(self): pass
    @asynccontextmanager
    async def factory():
        nonlocal sessions
        sessions+=1
        yield DB(sessions%2==1)
    async def account_for(*args,**kwargs):
        assert kwargs.get('lock') is True and not kwargs.get('enabled',False)
        return account
    async def contact_for(*args,**kwargs): return contact
    async def authority(*args): return object() if exact_fk else None
    async def send(*args): calls.append(message.id); return 'synthetic-receipt'
    monkeypatch.setattr(service,'account_for',account_for)
    monkeypatch.setattr(service,'contact_for',contact_for)
    monkeypatch.setattr(service,'window_open',lambda contact:True)
    monkeypatch.setattr(whatsapp_test_authority,'exact_test_authority',authority)
    monkeypatch.setattr(whatsapp_provider,'send',send)
    await deliver_one(message.id,factory)
    assert calls==([message.id] if exact_fk else [])
    assert message.status==('accepted' if exact_fk else 'failed')


@pytest.mark.asyncio
async def test_secret_cleanup_executes_with_rollouts_disabled_and_commits_only_its_session(monkeypatch):
    from app.config import settings
    from app.services import whatsapp_self_service
    from app.workers.whatsapp import cleanup_setup_secrets
    monkeypatch.setattr(settings,'V1_WHATSAPP_ONBOARDING_ENABLED',False)
    monkeypatch.setattr(settings,'V1_CHANNEL_TESTS_ENABLED',False)
    seen=[]
    class DB:
        async def commit(self): seen.append('commit')
    db=DB()
    @asynccontextmanager
    async def factory(): yield db
    async def cleanup(session,*,limit):
        assert session is db and limit==100
        seen.append('cleanup')
        return 2
    monkeypatch.setattr(whatsapp_self_service,'cleanup_provisional',cleanup)
    assert await cleanup_setup_secrets(factory)==2
    assert seen==['cleanup','commit']
