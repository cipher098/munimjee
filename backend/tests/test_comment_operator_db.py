"""Prepared real0056 tests; run ONLY after explicit P01 lane allocation.

The new router is explicitly mounted in this test fixture until central owns its
production registration. This is not a claim about shared production composition.
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment_automation import CommentAction, CommentEvent, CommentRule
from app.models.comment_operator import CommentOperatorCommand, CommentOperatorReview, WhatsAppEnquiryReview
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.product import Product
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from tests.test_v1_native_completion_import_http import native_import


@pytest_asyncio.fixture
async def operator(native_import):
    from app.main import app
    from app.api.v1.comment_operator import router
    original = list(app.router.routes)
    if not any(getattr(route, 'path', None) == '/api/v1/businesses/{business_id}/comment-automation' for route in original):
        app.include_router(router)
    j = native_import
    j.base = f'/api/v1/businesses/{j.bid}/comment-automation'
    try:
        yield j
    finally:
        app.router.routes[:] = original


async def seed_event(j, status='unknown'):
    eid, pid, rid = uuid4(), uuid4(), uuid4()
    async with j.sessions.begin() as db:
        db.add(Product(id=pid, seller_id=j.bid, name='Synthetic dress', active=True, listed_price=10000, floor_price=4000))
        await db.flush()
        db.add(CommentRule(id=rid, seller_id=j.bid, name='Synthetic scoped rule', enabled=False,
            media_id='300', product_id=pid, keywords=['price'], private_reply='Saved synthetic reply'))
        await db.flush()
        db.add(CommentEvent(id=eid, seller_id=j.bid, comment_id=uuid4().hex, media_id='300', actor_id='400',
            text='Synthetic comment price?', commented_at=datetime.now(timezone.utc), status='review_required',
            reason='legacy_binding_unverified', rule_id=rid))
        await db.flush()
        db.add(CommentAction(id=uuid4(), seller_id=j.bid, event_id=eid, kind='private', body='Saved original copy', status=status))
    return eid, pid, rid


async def close(j, eid, *, key=None, fingerprint=None):
    view = await j.client.get(j.base + f'/events/{eid}')
    assert view.status_code == 200, view.text
    body = {'idempotency_key': str(key or uuid4()), 'confirmed': True,
        'reason': 'Checked original conversation without another send', 'expected_fingerprint': fingerprint or view.json()['fingerprint']}
    return body, await j.client.post(j.base + f'/events/{eid}/reviews', headers=j.csrf, json=body)


@pytest.mark.asyncio
async def test_unknown_review_replay_preserves_effect_and_exact_receipt(operator):
    j = operator
    eid, _, _ = await seed_event(j)
    body, response = await close(j, eid)
    assert response.status_code == 200, response.text
    first = response.json()
    # Delivery facts may evolve independently; exact receipt precedes stale check.
    async with j.sessions.begin() as db:
        await db.execute(update(CommentEvent).where(CommentEvent.id == eid).values(reason='later_review_reason'))
    replay = await j.client.post(j.base + f'/events/{eid}/reviews', headers=j.csrf, json=body)
    assert replay.status_code == 200 and replay.json() == {**first, 'replayed': True}
    assert response.headers['cache-control'] == 'no-store'
    async with j.sessions() as db:
        action = await db.scalar(select(CommentAction).where(CommentAction.event_id == eid))
        assert action.status == 'unknown' and action.provider_id is None and action.claim_token is None
        assert await db.scalar(select(func.count()).select_from(CommentOperatorReview)) == 1
        assert await db.scalar(select(func.count()).select_from(CommentOperatorCommand)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['pending', 'sending'])
async def test_pending_or_sending_cannot_be_closed(operator, state):
    j = operator
    eid, _, _ = await seed_event(j, state)
    _, response = await close(j, eid)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'comment_operator_context_changed'
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CommentOperatorCommand)) == 0


@pytest.mark.asyncio
async def test_concurrent_review_closures_record_only_one_decision(operator):
    j = operator
    eid, _, _ = await seed_event(j)
    responses = await asyncio.gather(close(j, eid), close(j, eid))
    assert sorted(response.status_code for _, response in responses) == [200, 409]
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CommentOperatorReview)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('revoke', ['session', 'role'])
async def test_review_lock_wait_rechecks_current_native_authority(operator, monkeypatch, revoke):
    j = operator
    eid, _, _ = await seed_event(j)
    data = (await j.client.get(j.base + f'/events/{eid}')).json()
    waiting = asyncio.Event()
    original = AsyncSession.execute
    async def execute(db, query, *args, **kwargs):
        if getattr(query, '_for_update_arg', None) is not None and 'comment_events' in str(query):
            waiting.set()
        return await original(db, query, *args, **kwargs)
    async with j.sessions() as blocker:
        await blocker.begin()
        await blocker.scalar(select(CommentEvent).where(CommentEvent.id == eid).with_for_update())
        monkeypatch.setattr(AsyncSession, 'execute', execute)
        task = asyncio.create_task(j.client.post(j.base + f'/events/{eid}/reviews', headers=j.csrf,
            json={'idempotency_key': str(uuid4()), 'confirmed': True, 'reason': 'This must roll back after access ends', 'expected_fingerprint': data['fingerprint']}))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            async with j.sessions.begin() as db:
                if revoke == 'session':
                    await db.execute(update(UserSession).where(UserSession.user_id == j.uid).values(revoked_at=datetime.now(timezone.utc)))
                else:
                    await db.execute(update(Membership).where(Membership.business_id == j.bid, Membership.user_id == j.uid).values(role='viewer'))
            await blocker.commit()
            response = await task
        finally:
            if not task.done():
                task.cancel()
    assert response.status_code == (401 if revoke == 'session' else 403), response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CommentOperatorReview)) == 0
        assert await db.scalar(select(func.count()).select_from(CommentOperatorCommand)) == 0


@pytest.mark.asyncio
async def test_session_revoke_after_staged_review_flush_rolls_back_every_receipt(operator, monkeypatch):
    j = operator
    eid, _, _ = await seed_event(j)
    original, changed = AsyncSession.flush, False
    async def flush(db, *args, **kwargs):
        nonlocal changed
        trigger = not changed and any(isinstance(row, CommentOperatorReview) for row in db.new)
        await original(db, *args, **kwargs)
        if trigger:
            changed = True
            async with j.sessions.begin() as other:
                await other.execute(update(UserSession).where(UserSession.user_id == j.uid).values(revoked_at=datetime.now(timezone.utc)))
    monkeypatch.setattr(AsyncSession, 'flush', flush)
    _, response = await close(j, eid)
    assert changed and response.status_code == 401, response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CommentOperatorReview)) == 0
        assert await db.scalar(select(func.count()).select_from(CommentOperatorCommand)) == 0


@pytest.mark.asyncio
async def test_rule_expected_fingerprint_and_exact_lost_response_replay(operator):
    j = operator
    _, pid, rid = await seed_event(j)
    row = (await j.client.get(j.base + f'/rules/{rid}')).json()
    facts = {key: row[key] for key in ('name', 'enabled', 'media_id', 'keywords', 'product_id', 'private_reply', 'public_reply')}
    facts['name'] = 'Unicode साड़ी 👗'
    body = {'idempotency_key': str(uuid4()), 'facts': facts, 'expected_fingerprint': row['fingerprint']}
    response = await j.client.put(j.base + f'/rules/{rid}', headers=j.csrf, json=body)
    assert response.status_code == 200, response.text
    replay = await j.client.put(j.base + f'/rules/{rid}', headers=j.csrf, json=body)
    assert replay.status_code == 200 and replay.json() == {**response.json(), 'replayed': True}
    stale_body = {**body, 'idempotency_key': str(uuid4())}
    rejected = await j.client.put(j.base + f'/rules/{rid}', headers=j.csrf, json=stale_body)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'comment_operator_context_changed'


@pytest.mark.asyncio
async def test_native_viewer_foreign_scope_and_csrf_are_not_operator_authority(operator):
    j = operator
    eid, _, _ = await seed_event(j)
    _, response = await close(j, eid, fingerprint='a' * 64)
    assert response.status_code == 409
    denied = await j.client.post(j.base + f'/events/{eid}/reviews', json={'idempotency_key': str(uuid4()),
        'confirmed': True, 'reason': 'No CSRF must not change anything', 'expected_fingerprint': 'a' * 64})
    assert denied.status_code == 403
    assert (await j.client.get(f'/api/v1/businesses/{uuid4()}/comment-automation/events')).status_code == 404
    async with j.sessions.begin() as db:
        await db.execute(update(Membership).where(Membership.business_id == j.bid, Membership.user_id == j.uid).values(role='viewer'))
    data = (await j.client.get(j.base + f'/events/{eid}')).json()
    assert data['can_close'] is False
    _, denied = await close(j, eid)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_new_receipts_are_immutable_and_all_new_foreign_keys_validated(operator):
    j = operator
    eid, _, _ = await seed_event(j)
    _, response = await close(j, eid)
    assert response.status_code == 200, response.text
    async with j.sessions() as db:
        command_id = await db.scalar(select(CommentOperatorCommand.id))
        constraints = (await db.execute(text("SELECT convalidated FROM pg_constraint WHERE contype='f' AND conrelid::regclass::text IN ('comment_operator_commands','comment_operator_reviews','whatsapp_enquiry_reviews','whatsapp_enquiry_closures')"))).scalars().all()
        assert len(constraints) >= 8 and all(constraints)
    async with j.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(update(CommentOperatorCommand).where(CommentOperatorCommand.id == command_id).values(result={'resource_id': str(eid), 'fingerprint': 'b' * 64}))
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(delete(CommentOperatorReview).where(CommentOperatorReview.event_id == eid))


@pytest.mark.asyncio
async def test_signed_inferred_followup_has_one_visible_enquiry_and_no_second_send(operator, monkeypatch):
    from app.config import settings
    from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
    from app.models.checkout_v1 import CatalogueActivation
    from app.models.commerce import Storefront
    j = operator
    _, pid, _ = await seed_event(j)
    monkeypatch.setattr(settings, 'V1_SKU_FACT_REPLIES_ENABLED', True)
    monkeypatch.setattr(settings, 'WHATSAPP_APP_SECRET', 'synthetic-enquiry-signature')
    send = AsyncMock(side_effect=AssertionError('Ingestion/review must never call the provider sender'))
    monkeypatch.setattr('app.services.whatsapp_provider.send', send)
    async with j.sessions.begin() as db:
        await db.execute(update(Product).where(Product.id == pid).values(reel_urls=['https://www.instagram.com/reel/Enquiry_case/']))
        await db.execute(update(Storefront).where(Storefront.seller_id == j.bid).values(published=True))
        db.add(WhatsAppAccount(seller_id=j.bid, phone_number_id='100', waba_id='200', access_token='synthetic-unused-no-provider',
            enabled=True, automation_enabled=True, reel_replies_enabled=True))
        db.add(CatalogueProductMapping(business_id=j.bid, product_id=pid, state='reviewed', revision=1,
            legacy_fingerprint='a' * 64, issues=[], legacy_variants=[]))
        await db.flush()
        db.add_all([CatalogueActivation(business_id=j.bid, product_id=pid, reviewed_revision=1, legacy_fingerprint='a' * 64, actor_id=j.uid),
            CatalogueSKU(business_id=j.bid, product_id=pid, options={}, price_minor=12345, currency='INR', stock_available=None, active=True)])
    async def inbound(mid, body, seconds_ago):
        event = {'id': mid, 'from': '919876543210', 'type': 'text', 'text': {'body': body},
            'timestamp': str(int((datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).timestamp()))}
        raw = json.dumps({'object': 'whatsapp_business_account', 'entry': [{'id': '200', 'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': '100'}, 'contacts': [{'wa_id': event['from'], 'profile': {'name': 'Synthetic enquiry buyer'}}], 'messages': [event]}}]}]}).encode()
        signature = 'sha256=' + hmac.new(b'synthetic-enquiry-signature', raw, hashlib.sha256).hexdigest()
        return await j.client.post('/webhooks/whatsapp', content=raw, headers={'X-Hub-Signature-256': signature})
    first = await inbound('synthetic-explicit', 'https://www.instagram.com/reel/Enquiry_case/', 10)
    assert first.status_code == 200, first.text
    duplicate = await asyncio.gather(inbound('synthetic-followup', 'price?', 5), inbound('synthetic-followup', 'price?', 5))
    assert all(response.status_code == 200 for response in duplicate)
    async with j.sessions() as db:
        row = await db.scalar(select(WhatsAppEnquiryReview).where(WhatsAppEnquiryReview.business_id == j.bid))
        assert row and row.reason == 'activated_inferred_context' and row.phone_number_id == '100'
        assert await db.scalar(select(func.count()).select_from(WhatsAppEnquiryReview)) == 1
        message = await db.get(WhatsAppMessage, row.inbound_message_id)
        assert message.text == 'price?' and message.contact_id == row.contact_id and message.direction == 'inbound'
        assert (message.payload['reel_context']['source']) == 'recent_message'
        assert not await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.idempotency_key == 'auto:reel:synthetic-followup'))
        row_id = row.id
    wa_base = f'/api/v1/businesses/{j.bid}/whatsapp/enquiries'
    detail = await j.client.get(wa_base + '/' + str(row_id))
    assert detail.status_code == 200 and detail.json()['message'] == 'price?' and detail.json()['can_close']
    body = {'idempotency_key': str(uuid4()), 'confirmed': True, 'reason': 'Reviewed inferred follow-up without a customer send',
        'expected_fingerprint': detail.json()['fingerprint']}
    closed = await j.client.post(wa_base + f'/{row_id}/close', headers=j.csrf, json=body)
    assert closed.status_code == 200, closed.text
    async with j.sessions() as db:
        contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id == j.bid))
        assert contact.utility_opt_in is contact.marketing_opt_in is False
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.direction == 'outbound')) == 1
    send.assert_not_awaited()
