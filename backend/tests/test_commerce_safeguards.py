"""Real HTTP/DB regressions for account linking and payment authority."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock
from uuid import uuid4
import hashlib
import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select
from app.api.routes import auth
from app.api.dashboard_auth import _make_token
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Seller, Product, Conversation, ConversationProduct, Order, OrderItem
from app.models.commerce_safeguards import OAuthState, PaymentReview
from app.models.transaction import Transaction
from app.models.payment_method import PaymentMethod
from tests.conftest_db import db_session, patched_clients  # noqa

@pytest_asyncio.fixture
async def setup(db_session, monkeypatch):
    sellers = [Seller(email=f"{uuid4()}@example.com", password_hash="unused", is_active=True) for _ in range(2)]
    db_session.add_all(sellers)
    await db_session.flush()
    await db_session.commit()
    ids = [s.id for s in sellers]
    async def override():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
    app.dependency_overrides[get_db] = override
    exchange = AsyncMock(return_value={"access_token": "short", "user_id": "123"})
    monkeypatch.setattr(auth, "exchange_code_for_user_token", exchange)
    monkeypatch.setattr(auth, "exchange_for_long_lived_token", AsyncMock(return_value="long"))
    monkeypatch.setattr(auth, "fetch_ig_user", AsyncMock(return_value={"id": "123", "account_type": "BUSINESS"}))
    monkeypatch.setattr(auth, "subscribe_ig_user_to_messages", AsyncMock(return_value={}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        client.cookies.set("dashboard_session", _make_token("seller", str(ids[0]), "seller"))
        yield SimpleNamespace(db=db_session, client=client, sellers=ids, exchange=exchange)
    app.dependency_overrides.clear()

async def start(setup):
    response = await setup.client.get('/auth/instagram/oauth/start')
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers['location']).query)['state'][0]

@pytest.mark.asyncio
async def test_link_requires_authentication(setup):
    setup.client.cookies.clear()
    assert (await setup.client.get('/auth/instagram/oauth/start')).status_code == 401
    assert (await setup.client.post('/auth/seller/connect-instagram', json={"seller_id": str(setup.sellers[1]), "short_lived_token": "x"})).status_code == 401
    setup.exchange.assert_not_called()

@pytest.mark.asyncio
async def test_link_rejects_another_seller(setup):
    assert (await setup.client.get('/auth/instagram/oauth/start', params={"seller_id": str(setup.sellers[1])})).status_code == 403
    assert (await setup.client.post('/auth/seller/connect-instagram', json={"seller_id": str(setup.sellers[1]), "short_lived_token": "x"})).status_code == 403

@pytest.mark.asyncio
@pytest.mark.parametrize('attack', ['missing_cookie', 'wrong_cookie', 'wrong_seller', 'expired', 'tamper'])
async def test_oauth_callback_rejects_bad_sessions(setup, attack):
    state = await start(setup)
    if attack == 'missing_cookie': setup.client.cookies.delete(auth._OAUTH_COOKIE)
    elif attack == 'wrong_cookie':
        setup.client.cookies.delete(auth._OAUTH_COOKIE); setup.client.cookies.set(auth._OAUTH_COOKIE, 'wrong')
    elif attack == 'wrong_seller': setup.client.cookies.set('dashboard_session', _make_token('seller', str(setup.sellers[1]), 'other'))
    elif attack == 'expired':
        payload = jwt.get_unverified_claims(state); payload['exp'] = datetime.now(timezone.utc) - timedelta(seconds=1)
        state = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    elif attack == 'tamper': state = state[:-4] + 'xxxx'
    response = await setup.client.get('/auth/instagram/oauth/callback', params={'code': 'code', 'state': state})
    assert response.status_code == 400
    setup.exchange.assert_not_called()

@pytest.mark.asyncio
async def test_oauth_consumed_once_even_with_copied_cookie(setup):
    state = await start(setup); cookie = setup.client.cookies.get(auth._OAUTH_COOKIE)
    response = await setup.client.get('/auth/instagram/oauth/callback', params={'code': 'code', 'state': state})
    assert response.status_code == 302 and response.headers['location'].endswith('step=done')
    setup.client.cookies.set(auth._OAUTH_COOKIE, cookie)
    assert (await setup.client.get('/auth/instagram/oauth/callback', params={'code': 'code', 'state': state})).status_code == 400
    assert setup.exchange.await_count == 1
    assert (await setup.db.get(Seller, setup.sellers[0])).instagram_id == '123'
    assert (await setup.db.get(Seller, setup.sellers[1])).instagram_id is None

@pytest.mark.asyncio
async def test_signup_can_start_oauth_without_local_storage_token(setup):
    setup.client.cookies.clear()
    response = await setup.client.post('/auth/seller/signup', json={"email": "new@example.com", "password": "password123"})
    assert response.status_code == 200
    assert response.json()['instagram_oauth_url'] == '/auth/instagram/oauth/start'
    assert setup.client.cookies.get('seller_session')
    await start(setup)

@pytest.mark.asyncio
async def test_expired_database_nonce_rejected(setup):
    state = await start(setup); nonce = jwt.get_unverified_claims(state)['nonce']
    row = await setup.db.get(OAuthState, hashlib.sha256(nonce.encode()).hexdigest())
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await setup.db.commit()
    assert (await setup.client.get('/auth/instagram/oauth/callback', params={'code': 'code', 'state': state})).status_code == 400
    setup.exchange.assert_not_called()

@pytest_asyncio.fixture
async def payment(setup):
    db = setup.db
    product = Product(seller_id=setup.sellers[0], name='Dress', listed_price=10000, floor_price=9000)
    db.add(product); await db.flush()
    conv = Conversation(seller_id=setup.sellers[0], customer_instagram_id='customer', product_id=product.id, messages=[])
    db.add(conv); await db.flush()
    cp = ConversationProduct(conversation_id=conv.id, product_id=product.id, state='awaiting_payment', agreed_price=10000)
    method = PaymentMethod(seller_id=setup.sellers[0], category='upi', upi_id='shop@upi', account_name='Shop')
    db.add_all([cp, method]); await db.flush()
    order = Order(seller_id=setup.sellers[0], conversation_id=conv.id, customer_name='Customer', customer_instagram_id='customer', amount=10000, amount_paid=0, status='awaiting_payment', payment_method_id=method.id, payment_requested_at=datetime.now(timezone.utc)-timedelta(minutes=1))
    db.add(order); await db.flush()
    db.add(OrderItem(order_id=order.id, conversation_product_id=cp.id, quantity=1, unit_price=10000))
    await db.commit()
    return SimpleNamespace(**vars(setup), product=product.id, conversation=conv.id, cp=cp.id, order=order.id)

@pytest.mark.asyncio
@pytest.mark.parametrize('amount', [100, 50])
async def test_even_matching_payment_proof_never_marks_paid(payment, monkeypatch, patched_clients, amount):
    from app.bot.conversation import _handle_payment_screenshot_inner
    from app.integrations.claude import ClaudeClient
    from app.bot import conversation as bot
    class Download:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return httpx.Response(200, content=b'image', request=httpx.Request('GET', url))
    monkeypatch.setattr(bot.httpx, 'AsyncClient', lambda **kwargs: Download())
    monkeypatch.setattr(bot, '_save_payment_screenshot', lambda *args: '/uploads/proof.jpg')
    monkeypatch.setattr(ClaudeClient, 'extract_payment_details', AsyncMock(return_value={
        'utr': 'BANK123', 'amount_rupees': amount, 'payee_upi_id': 'shop@upi', 'payee_name': 'Shop',
        'datetime': datetime.now(timezone.utc).isoformat(), 'status_text': 'Paid'}))
    seller = await payment.db.get(Seller, payment.sellers[0]); conv = await payment.db.get(Conversation, payment.conversation)
    await _handle_payment_screenshot_inner(conv, seller, 'https://example.com/proof.jpg', payment.db)
    order = await payment.db.get(Order, payment.order)
    assert order.amount_paid == 0 and order.status == 'awaiting_payment'
    assert not (await payment.db.execute(select(Transaction))).scalars().all()
    review = (await payment.db.execute(select(PaymentReview))).scalar_one()
    assert review.status == 'pending' and review.extracted['utr'] == 'BANK123'
    assert (await payment.db.get(ConversationProduct, payment.cp)).state == 'manual_review'

async def add_review(payment):
    review = PaymentReview(seller_id=payment.sellers[0], conversation_id=payment.conversation,
                           order_id=payment.order, screenshot_url='/uploads/proof.jpg', extracted={'utr': 'BANK123'}, status='pending')
    payment.db.add(review); await payment.db.commit()
    return review.id

@pytest.mark.asyncio
async def test_manual_confirmation_is_explicit_and_idempotent(payment):
    rid = await add_review(payment); path = f'/manual-actions/payment-reviews/{rid}/review'
    body = {'approved': True, 'amount_paise': 10000, 'reference': 'BANK123'}
    for _ in range(2):
        response = await payment.client.post(path, json=body)
        assert response.status_code == 200, response.text
        assert response.json()['amount_paid'] == 10000
    assert len((await payment.db.execute(select(Transaction))).scalars().all()) == 1
    assert (await payment.db.get(Order, payment.order)).status == 'payment_confirmed'
    assert (await payment.db.get(ConversationProduct, payment.cp)).state == 'awaiting_address'
    assert (await payment.client.post(path, json={'approved': False})).status_code == 409

@pytest.mark.asyncio
async def test_partial_review_does_not_release_order(payment):
    rid = await add_review(payment)
    response = await payment.client.post(f'/manual-actions/payment-reviews/{rid}/review', json={'approved': True, 'amount_paise': 4000, 'reference': 'PARTIAL'})
    assert response.status_code == 200
    assert response.json()['amount_paid'] == 4000 and response.json()['order_status'] == 'awaiting_payment'

@pytest.mark.asyncio
async def test_cross_seller_review_hidden(payment):
    rid = await add_review(payment)
    payment.client.cookies.set('dashboard_session', _make_token('seller', str(payment.sellers[1]), 'other'))
    assert (await payment.client.get('/manual-actions/payment-reviews')).json() == []
    assert (await payment.client.post(f'/manual-actions/payment-reviews/{rid}/review', json={'approved': True, 'amount_paise': 10000, 'reference': 'BANK'})).status_code == 404

@pytest.mark.asyncio
async def test_reject_keeps_balance_unpaid(payment):
    rid = await add_review(payment)
    response = await payment.client.post(f'/manual-actions/payment-reviews/{rid}/review', json={'approved': False})
    assert response.status_code == 200
    assert response.json()['amount_paid'] == 0 and response.json()['order_status'] == 'awaiting_payment'

@pytest.mark.asyncio
async def test_bank_reference_cannot_be_counted_twice(payment):
    first = await add_review(payment); second = await add_review(payment)
    body = {'approved': True, 'amount_paise': 4000, 'reference': 'BANK-SAME'}
    assert (await payment.client.post(f'/manual-actions/payment-reviews/{first}/review', json=body)).status_code == 200
    assert (await payment.client.post(f'/manual-actions/payment-reviews/{second}/review', json=body)).status_code == 409
    assert (await payment.db.get(Order, payment.order)).amount_paid == 4000

@pytest.mark.asyncio
async def test_pending_review_holds_bot_without_confirming(payment, monkeypatch):
    from app.bot.conversation import _advance_conversation_inner
    from app.bot import responder
    await add_review(payment)
    reply = AsyncMock()
    monkeypatch.setattr(responder, 'generate_bot_reply', reply)
    conv = await payment.db.get(Conversation, payment.conversation)
    seller = await payment.db.get(Seller, payment.sellers[0])
    await _advance_conversation_inner(conv, seller, 'Here is my address', payment.db, True, False, None)
    reply.assert_not_called()
    assert conv.messages[-1]['content'] == 'Here is my address'
    assert (await payment.db.get(Order, payment.order)).status == 'awaiting_payment'

@pytest.mark.asyncio
async def test_failed_exchange_still_consumes_nonce(setup):
    state = await start(setup)
    setup.exchange.side_effect = RuntimeError('provider unavailable')
    response = await setup.client.get('/auth/instagram/oauth/callback', params={'state': state, 'code': 'code'})
    assert response.headers['location'].endswith('token_exchange_failed')
    response = await setup.client.get('/auth/instagram/oauth/callback', params={'state': state, 'code': 'code'})
    assert response.status_code == 400
    assert setup.exchange.await_count == 1

@pytest.mark.asyncio
async def test_oauth_requires_same_login_session(setup):
    state = await start(setup)
    # Same seller, different signed login session.
    setup.client.cookies.set('dashboard_session', _make_token('seller', str(setup.sellers[0]), 'new-session'))
    assert (await setup.client.get('/auth/instagram/oauth/callback', params={'state': state, 'code': 'code'})).status_code == 400
    setup.exchange.assert_not_called()

@pytest.mark.asyncio
async def test_payment_evidence_private_to_own_seller(payment, monkeypatch, tmp_path):
    from app.api.routes import private_media
    monkeypatch.setattr(private_media, 'UPLOAD_DIR', tmp_path)
    folder = tmp_path / 'payment_screenshots' / 'received'; folder.mkdir(parents=True)
    (folder / 'proof.jpg').write_bytes(b'private screenshot')
    rid = await add_review(payment)
    review = await payment.db.get(PaymentReview, rid)
    review.screenshot_url = '/uploads/payment_screenshots/received/proof.jpg'
    await payment.db.commit()
    path = review.screenshot_url
    response = await payment.client.get(path)
    assert response.status_code == 200 and response.content == b'private screenshot'
    assert 'no-store' in response.headers['cache-control']
    payment.client.cookies.set('dashboard_session', _make_token('seller', str(payment.sellers[1]), 'other'))
    assert (await payment.client.get(path)).status_code == 404
    payment.client.cookies.clear()
    assert (await payment.client.get(path)).status_code == 302

@pytest.mark.asyncio
async def test_public_upload_fallback_cannot_serve_private_files(tmp_path):
    from app.api.routes.private_media import PublicUploads
    from fastapi import FastAPI
    private_folder = tmp_path / 'payment_screenshots' / 'received'; private_folder.mkdir(parents=True)
    (private_folder / 'proof.jpg').write_bytes(b'private')
    (tmp_path / 'training').mkdir(); (tmp_path / 'training' / 'sample.jpg').write_bytes(b'training')
    (tmp_path / 'product.jpg').write_bytes(b'public catalogue image')
    isolated = FastAPI(); isolated.mount('/uploads', PublicUploads(directory=str(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(isolated), base_url='http://test') as client:
        for path in ['payment_screenshots/received/proof.jpg', 'training/sample.jpg', 'TRAINING/sample.jpg', 'payment_screenshots/received/not-a-file.jpg']:
            assert (await client.get('/uploads/' + path)).status_code == 404
        assert (await client.get('/uploads/product.jpg')).status_code == 200

@pytest.mark.asyncio
async def test_private_media_rejects_symlinks(payment, monkeypatch, tmp_path):
    from app.api.routes import private_media
    monkeypatch.setattr(private_media, 'UPLOAD_DIR', tmp_path)
    folder = tmp_path / 'payment_screenshots' / 'received'; folder.mkdir(parents=True)
    external = tmp_path / 'secret.txt'; external.write_text('private other file')
    (folder / 'proof.jpg').symlink_to(external)
    rid = await add_review(payment)
    review = await payment.db.get(PaymentReview, rid)
    review.screenshot_url = '/uploads/payment_screenshots/received/proof.jpg'
    await payment.db.commit()
    assert (await payment.client.get(review.screenshot_url)).status_code == 404

@pytest.mark.asyncio
async def test_bearer_link_uses_its_own_session_not_stale_dashboard(setup):
    setup.client.cookies.clear()
    setup.client.cookies.set('dashboard_session', _make_token('seller', str(setup.sellers[0]), 'old-session'), domain='test.local')
    token = auth._create_token({'sub': str(setup.sellers[1]), 'role': 'seller'})
    response = await setup.client.get('/auth/instagram/oauth/start', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 302
    state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
    response = await setup.client.get('/auth/instagram/oauth/callback', params={'state': state, 'code': 'code'})
    assert response.status_code == 302 and response.headers['location'].endswith('step=done')
    assert (await setup.db.get(Seller, setup.sellers[1])).instagram_id == '123'
    assert (await setup.db.get(Seller, setup.sellers[0])).instagram_id is None

@pytest.mark.asyncio
async def test_dashboard_rejects_inactive_seller_at_login_and_on_existing_session(setup):
    seller = await setup.db.get(Seller, setup.sellers[0])
    seller.password_hash = auth._hash_password('safe-test-password')
    seller.is_active = False
    email = seller.email
    await setup.db.commit()
    response = await setup.client.post('/dashboard-auth/login', data={'identifier': email, 'password': 'safe-test-password'})
    assert response.status_code == 403
    assert not any(h.startswith('dashboard_session=') for h in response.headers.get_list('set-cookie'))
    # The previously valid signed JWT cannot access the seller dashboard either.
    response = await setup.client.get('/dashboard-auth/me')
    assert response.status_code == 302 and response.headers['location'] == '/dashboard-auth/login'

@pytest.mark.asyncio
@pytest.mark.parametrize('password', ['changeme', '', '  '])
async def test_dashboard_default_or_empty_admin_password_disabled(setup, monkeypatch, password):
    monkeypatch.setattr(settings, 'DASHBOARD_PASSWORD', password)
    monkeypatch.setattr(settings, 'DASHBOARD_ALLOWED_PHONES', ['1234567890'])
    response = await setup.client.post('/dashboard-auth/login', data={'identifier': '1234567890', 'password': password})
    assert response.status_code in (403, 422)
    assert not any(h.startswith('dashboard_session=') for h in response.headers.get_list('set-cookie'))

@pytest.mark.asyncio
async def test_dashboard_configured_admin_login_remains_available(setup, monkeypatch):
    monkeypatch.setattr(settings, 'DASHBOARD_PASSWORD', 'explicit-test-admin-secret')
    monkeypatch.setattr(settings, 'DASHBOARD_ALLOWED_PHONES', ['1234567890'])
    response = await setup.client.post('/dashboard-auth/login', data={'identifier': '+91 1234567890', 'password': 'explicit-test-admin-secret'})
    assert response.status_code == 303 and response.headers['location'] == '/dashboard/admin'
    token = response.cookies.get('dashboard_session')
    assert jwt.get_unverified_claims(token)['role'] == 'admin'
    assert (await setup.client.post('/dashboard-auth/login', data={'identifier': '0000000000', 'password': 'explicit-test-admin-secret'})).status_code == 403

@pytest.mark.asyncio
@pytest.mark.parametrize('request_url,public_base,secure', [
    ('http://test/dashboard-auth/login', '', False),
    ('https://test/dashboard-auth/login', '', True),
    ('http://test/dashboard-auth/login', 'https://shop.example.com', True),
])
async def test_dashboard_session_cookie_secure_on_https(setup, monkeypatch, request_url, public_base, secure):
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', public_base)
    seller = await setup.db.get(Seller, setup.sellers[0])
    seller.password_hash = auth._hash_password('safe-test-password')
    email = seller.email
    await setup.db.commit()
    response = await setup.client.post(request_url, data={'identifier': email, 'password': 'safe-test-password'})
    assert response.status_code == 303
    cookie = next(h for h in response.headers.get_list('set-cookie') if h.startswith('dashboard_session='))
    assert ('Secure' in cookie) is secure
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie

@pytest.mark.asyncio
async def test_connect_instagram_does_not_return_provider_exception_contents(setup, monkeypatch):
    monkeypatch.setattr(auth, 'exchange_for_long_lived_token', AsyncMock(side_effect=RuntimeError('request access_token=VERY_PRIVATE_TOKEN')))
    response = await setup.client.post('/auth/seller/connect-instagram', json={'short_lived_token': 'private-input-token'})
    assert response.status_code == 400
    assert 'VERY_PRIVATE_TOKEN' not in response.text and 'private-input-token' not in response.text
