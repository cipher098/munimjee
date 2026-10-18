"""Actual main/router, synthetic account GETs, loopback-only nonce test fixtures."""
from tests.safety import install_test_safety
install_test_safety()
import secrets
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:8169'
settings.META_WEBHOOK_SECRET = 'synthetic-webhook'
settings.WHATSAPP_APP_SECRET = 'synthetic-webhook'
settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = 'synthetic-verify'
settings.CHANNEL_ENCRYPTION_KEY = Fernet.generate_key().decode()
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.auth_sessions import decode_native_token, request_auth_token
from app.services.identity import require_business_access
from app.services import channel_connections
from app.workers.instagram_ingress import process_instagram_ingress
process_instagram_ingress.apply_async = lambda **kwargs: None
nonce = sys.argv[1]
calls = {'synthetic_account_reads': 0, 'provider_sends': 0}
assert len([r for r in app.routes if getattr(r, 'path', '') == '/v1/businesses/{business_id}/channels']) == 1
assert next(r for r in app.routes if getattr(r, 'path', '') == '/v1/businesses/{business_id}/channels').endpoint.__module__ == 'app.api.v1.channel_operator'
async def ig_read(*args, **kwargs):
    calls['synthetic_account_reads'] += 1
    return {'user_id': '1234567', 'account_type': 'BUSINESS'}
async def wa_read(*args, **kwargs):
    calls['synthetic_account_reads'] += 1
    return {'id': '7654321', 'display_phone_number': '+910000000000'}
channel_connections.ig.fetch_ig_user = ig_read
channel_connections.whatsapp_provider.verify_connection = wa_read
async def forbidden_send(*args, **kwargs):
    calls['provider_sends'] += 1
    raise AssertionError('Mounted channel hardening never authorizes a provider send')
channel_connections.ig.InstagramClient.send_message = forbidden_send
channel_connections.whatsapp_provider.send = forbidden_send

def fixture(request):
    if not secrets.compare_digest(request.headers.get('X-Local-Fixture', ''), nonce):
        raise HTTPException(403)

@app.get('/__channel_qa/identify')
async def identify():
    return {'nonce': nonce, 'actual_main_router': True, **calls}

@app.post('/__channel_qa/seed/{business_id}')
async def seed(business_id: UUID, request: Request, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    fixture(request)
    await require_business_access(db, actor, business_id, 'channels.connect')
    if await db.scalar(select(InstagramIngress.id).where(InstagramIngress.seller_id == business_id).limit(1)):
        raise HTTPException(409)
    seller = await db.get(Seller, business_id)
    seller.instagram_page_id = seller.instagram_id = seller.fb_page_id = '1234567'
    seller.instagram_token = 'synthetic-never-real-ig-token'
    db.add(ChannelConnectionState(business_id=business_id, channel='instagram', automation_enabled=False,
        check_status='not_checked', provider_account_id='1234567'))
    identifier = uuid4()
    db.add(InstagramIngress(id=identifier, seller_id=business_id, account_id='1234567', customer_id='synthetic-customer-654321',
        event_key=uuid4().hex, provider_message_id='synthetic-never-real-mid',
        events=[{'type': 'text', 'text': 'Synthetic private customer question about a dress.'}],
        processed_indices=[], status='error', error_code='processing_failed_unknown_effect',
        attempts=1, available_at=datetime.now(timezone.utc), occurred_at=datetime.now(timezone.utc)))
    return {'receipt_id': str(identifier)}

@app.post('/__channel_qa/self/{business_id}/{action}')
async def self_change(business_id: UUID, action: str, request: Request, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    fixture(request)
    await require_business_access(db, actor, business_id, 'business.read')
    if action == 'revoke-session':
        session = await db.get(UserSession, UUID(decode_native_token(request_auth_token(request))['sid']))
        session.revoked_at = datetime.now(timezone.utc)
    elif action in {'viewer', 'owner'}:
        member = await db.scalar(select(Membership).where(Membership.business_id == business_id, Membership.user_id == actor.user_id))
        member.role = action
    else:
        raise HTTPException(422)
    return {'synthetic_self_fixture_only': True}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8169, log_level='warning')
