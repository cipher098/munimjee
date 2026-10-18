"""Native configuration CAS, privacy and transactional authority on actual DDL."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from cryptography.fernet import Fernet
import pytest
import pytest_asyncio
from sqlalchemy import select, update
from app.api.v1.checkout_sessions import configuration_router
from app.api.v1.payment_settings import router as page_router
from app.config import settings
from app.models.identity_auth import UserSession
from app.models.razorpay import RazorpayAccount
from app.services import checkout_sessions as service, razorpay_payments as payments
from tests.test_v1_checkout_api import api, actor  # noqa:F401
from tests.test_v1_checkout import seed


@pytest_asyncio.fixture
async def configuration(api, monkeypatch):
    client, factory = api
    client._transport.app.include_router(configuration_router)
    client._transport.app.include_router(page_router)
    monkeypatch.setattr(settings, 'PAYMENT_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:8162')
    async def forbidden(*args, **kwargs):
        raise AssertionError('Configuration must not call Razorpay')
    monkeypatch.setattr(payments, 'gateway_request', forbidden)
    bid, _, _ = await seed(factory)
    headers, token, csrf, sid = await actor(factory, bid)
    return client, factory, bid, headers, token, csrf, sid


def payload(**changes):
    return {**dict(key_id='rzp_test_synthetic', key_secret='synthetic-api-secret',
        webhook_secret='synthetic-webhook-secret', mode='test', enabled=False), **changes}


def path(bid):
    return f'/api/v1/businesses/{bid}/payments/razorpay'


@pytest.mark.asyncio
async def test_absent_revision_is_tenant_bound_and_full_response_never_contains_secrets(configuration):
    client, factory, bid, headers, *_ = configuration
    empty=(await client.get(path(bid),headers=headers)).json()
    assert not empty['configured'] and len(empty['configuration_revision'])==64
    async with factory() as db:
        assert await service.gateway_configuration_view(db,bid,type('Request',(),{'base_url':'http://127.0.0.1:8162/'})())
        assert service.gateway_configuration_revision(bid,None)!=service.gateway_configuration_revision(uuid4(),None)
    made=await client.put(path(bid),headers=headers,json={**payload(),'expected_revision':empty['configuration_revision']})
    assert made.status_code==200,made.text
    assert made.headers['cache-control']=='no-store'
    assert made.json()['configuration_revision']!=empty['configuration_revision']
    assert made.json()==(await client.get(path(bid),headers=headers)).json()
    assert made.json()['connection_verification']=='not_performed'
    assert 'synthetic-api-secret' not in made.text and 'synthetic-webhook-secret' not in made.text
    assert 'key_secret' not in made.text


@pytest.mark.asyncio
async def test_competing_same_revision_secret_replacements_have_one_winner(configuration):
    client, factory, bid, headers, *_ = configuration
    revision=(await client.get(path(bid),headers=headers)).json()['configuration_revision']
    bodies=[{**payload(),'expected_revision':revision,'key_secret':f'synthetic-api-{i}'} for i in (1,2)]
    responses=await asyncio.wait_for(asyncio.gather(*(client.put(path(bid),headers=headers,json=body) for body in bodies)),10)
    assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
    stale=next(r for r in responses if r.status_code==409)
    assert stale.json()['detail']['code']=='gateway_config_stale'
    winner=bodies[next(i for i,r in enumerate(responses) if r.status_code==200)]
    async with factory() as db:
        stored=await db.get(RazorpayAccount,bid)
        assert payments.decrypt(stored.key_secret)==winner['key_secret']


@pytest.mark.asyncio
async def test_held_old_request_cannot_overwrite_newer_reviewed_replacement(configuration, monkeypatch):
    client, factory, bid, headers, *_ = configuration
    revision=(await client.get(path(bid),headers=headers)).json()['configuration_revision']
    entered,release=asyncio.Event(),asyncio.Event()
    # Pause the old HTTP command before its lock, after validation. The request
    # body/credentials stay in memory, as a delayed real request would.
    from app.api.v1 import checkout_sessions as routes
    old_task=None
    original_access=routes.require_business_access
    first=True
    async def pause(db,actor,business_id,capability):
        nonlocal first
        result=await original_access(db,actor,business_id,capability)
        if first and capability=='business.write':
            first=False;entered.set();await release.wait()
        return result
    monkeypatch.setattr(routes,'require_business_access',pause)
    try:
        old_task=asyncio.create_task(client.put(path(bid),headers=headers,json={**payload(),'expected_revision':revision,'key_secret':'synthetic-old-request'}))
        await asyncio.wait_for(entered.wait(),5)
        replacement=await client.put(path(bid),headers=headers,json={**payload(),'expected_revision':revision,'key_secret':'synthetic-new-replacement'})
        assert replacement.status_code==200,replacement.text
        release.set();old=await asyncio.wait_for(old_task,5)
        assert old.status_code==409 and old.json()['detail']['code']=='gateway_config_stale'
        async with factory() as db:assert payments.decrypt((await db.get(RazorpayAccount,bid)).key_secret)=='synthetic-new-replacement'
    finally:
        release.set()
        if old_task is not None and not old_task.done():old_task.cancel();await asyncio.gather(old_task,return_exceptions=True)


@pytest.mark.asyncio
async def test_final_native_session_revocation_rolls_back_local_config_change(configuration, monkeypatch):
    client, factory, bid, headers, token, csrf, sid = configuration
    from app.api.routes import razorpay as routes
    original=routes.update_settings
    async def revoke(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with factory.begin() as other:
            await other.execute(update(UserSession).where(UserSession.id==sid).values(revoked_at=datetime.now(timezone.utc)))
        return result
    monkeypatch.setattr(routes,'update_settings',revoke)
    revision=(await client.get(path(bid),headers=headers)).json()['configuration_revision']
    response=await client.put(path(bid),headers=headers,json={**payload(),'expected_revision':revision})
    assert response.status_code==401,response.text
    async with factory() as db:assert await db.get(RazorpayAccount,bid) is None


@pytest.mark.asyncio
async def test_revision_and_view_use_current_scalars_not_retained_account(configuration):
    client, factory, bid, headers, *_ = configuration
    await client.put(path(bid),headers=headers,json=payload())
    request=type('Request',(),{'base_url':'http://127.0.0.1:8162/'})()
    async with factory() as retained:
        cached=await retained.get(RazorpayAccount,bid)
        before=await service.gateway_configuration_view(retained,bid,request)
        async with factory.begin() as other:
            account=await other.get(RazorpayAccount,bid)
            account.enabled=True;account.key_secret=payments.encrypt('synthetic-rotated-api')
        after=await service.gateway_configuration_view(retained,bid,request)
        assert cached.enabled is False and after.enabled is True
        assert after.configuration_revision!=before.configuration_revision
        assert before.configuration_revision!=service.gateway_configuration_revision(bid,type('Account',(),dict(key_id=cached.key_id,mode=cached.mode,enabled=cached.enabled,key_secret=cached.key_secret,webhook_secret=payments.encrypt('another-synthetic-webhook')))())


@pytest.mark.asyncio
async def test_shell_native_access_and_config_cookie_csrf_remain_protected(configuration):
    client, factory, bid, headers, token, csrf, sid = configuration
    page=f'/v1/businesses/{bid}/payments'
    assert (await client.get(page,headers=headers)).status_code==200
    foreign, _, _=await seed(factory)
    assert (await client.get(f'/v1/businesses/{foreign}/payments',headers=headers)).status_code==404
    client.cookies.set('v1_session',token);client.cookies.set('v1_csrf',csrf)
    revision=(await client.get(path(bid))).json()['configuration_revision']
    assert (await client.put(path(bid),json={**payload(),'expected_revision':revision})).status_code==403
    assert (await client.put(path(bid),json={**payload(),'expected_revision':revision},headers={'Origin':'https://foreign.invalid','X-CSRF-Token':csrf})).status_code==403
    for role in ('staff','viewer'):
        operator,*_=await actor(factory,bid,role)
        assert (await client.get(page,headers=operator)).status_code==200
        assert (await client.get(path(bid),headers=operator)).status_code==403
        assert (await client.put(path(bid),headers=operator,json=payload())).status_code==403


@pytest.mark.asyncio
async def test_noop_revision_is_stable_but_same_plaintext_replacement_invalidates_old_commands(configuration):
    client, factory, bid, headers, *_ = configuration
    first=await client.put(path(bid),headers=headers,json=payload())
    assert first.status_code==200
    revision=first.json()['configuration_revision']
    noop=await client.put(path(bid),headers=headers,json=payload(key_secret=None,webhook_secret=None,expected_revision=revision))
    assert noop.status_code==200 and noop.json()['configuration_revision']==revision
    replaced=await client.put(path(bid),headers=headers,json=payload(expected_revision=revision))
    assert replaced.status_code==200 and replaced.json()['configuration_revision']!=revision
    old=await client.put(path(bid),headers=headers,json=payload(enabled=True,key_secret=None,webhook_secret=None,expected_revision=revision))
    assert old.status_code==409 and old.json()['detail']['code']=='gateway_config_stale'


@pytest.mark.asyncio
async def test_pending_online_order_blocks_rotation_without_changing_configuration(configuration, monkeypatch):
    client, factory, bid, headers, *_ = configuration
    from tests.test_v1_checkout_api import online_order
    business, _, order, _ = await online_order((client,factory),monkeypatch)
    owner,*_=await actor(factory,business)
    before=(await client.get(path(business),headers=owner)).json()
    response=await client.put(path(business),headers=owner,json=payload(expected_revision=before['configuration_revision']))
    assert response.status_code==409 and not isinstance(response.json()['detail'],dict)
    assert (await client.get(path(business),headers=owner)).json()==before
