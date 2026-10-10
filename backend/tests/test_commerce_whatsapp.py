"""Real checkout consent, replay, and order-notification regression tests."""
import hashlib
import json
from uuid import UUID
import pytest
from sqlalchemy import select
from tests.test_commerce import commerce, payload, auth
from app.models.commerce import CommerceOrder
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services.commerce import CheckoutInput

async def configure(factory, seller_id):
    async with factory() as db:
        db.add(WhatsAppAccount(seller_id=seller_id, phone_number_id='123', waba_id='456', access_token='not-used-in-request', enabled=True, order_templates={event:{'name':'order_update','language':'en'} for event in ('placed','confirmed','shipped','delivered')}))
        db.add(WhatsAppTemplate(seller_id=seller_id, name='order_update', language='en', status='APPROVED', category='UTILITY', components=[{'type':'BODY','text':'Hello {{1}}, order {{2}}: {{3}}'}]))
        await db.commit()

@pytest.mark.asyncio
async def test_order_opt_in_per_order_and_replay(commerce):
    client, factory, ids = commerce
    await configure(factory, ids['sellers'][0])
    data = payload(ids, whatsapp_updates_opt_in=True)
    r = await client.post('/shop-api/shop-0/checkout', json=data)
    assert r.status_code == 201, r.text
    assert (await client.post('/shop-api/shop-0/checkout', json=data)).status_code == 200
    async with factory() as db:
        messages = (await db.scalars(select(WhatsAppMessage))).all()
        assert len(messages) == 1 and messages[0].status == 'queued'
        assert messages[0].payload['parameters'][1] == r.json()['number']
        contact = await db.scalar(select(WhatsAppContact))
        assert contact.utility_opt_in and not contact.marketing_opt_in
    for _ in range(2):
        result = await client.post(f'/commerce/orders/{r.json()["id"]}/transition', cookies=auth(ids), json={'status':'confirmed'})
        assert result.status_code == 200, result.text
    unchecked = await client.post('/shop-api/shop-0/checkout', json=payload(ids))
    assert unchecked.status_code == 201
    async with factory() as db:
        assert len((await db.scalars(select(WhatsAppMessage))).all()) == 2
        assert not (await db.get(CommerceOrder, UUID(unchecked.json()['id']))).whatsapp_updates_opt_in
    assert (await client.post('/shop-api/shop-0/checkout', json={**data,'whatsapp_updates_opt_in':False})).status_code == 409

@pytest.mark.asyncio
async def test_checkout_respects_stop_and_missing_channel(commerce):
    client, factory, ids = commerce
    assert (await client.post('/shop-api/shop-0/checkout', json=payload(ids, whatsapp_updates_opt_in=True))).status_code == 201
    await configure(factory, ids['sellers'][0])
    async with factory() as db:
        db.add(WhatsAppContact(seller_id=ids['sellers'][0], phone='919876543210', opted_out=True))
        await db.commit()
    assert (await client.post('/shop-api/shop-0/checkout', json=payload(ids, whatsapp_updates_opt_in=True))).status_code == 201
    async with factory() as db:
        contact = await db.scalar(select(WhatsAppContact))
        assert contact.opted_out and not contact.utility_opt_in
        assert not (await db.scalars(select(WhatsAppMessage))).all()

@pytest.mark.asyncio
async def test_legacy_checkout_hash_replay(commerce):
    client, factory, ids = commerce
    data = payload(ids)
    r = await client.post('/shop-api/shop-0/checkout', json=data)
    assert r.status_code == 201
    legacy = CheckoutInput.model_validate(data).model_dump(mode='json', exclude={'idempotency_key','whatsapp_updates_opt_in'})
    digest = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    async with factory() as db:
        assert (await db.get(CommerceOrder, UUID(r.json()['id']))).request_hash == digest
    assert (await client.post('/shop-api/shop-0/checkout', json=data)).status_code == 200
