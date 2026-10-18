"""Actual main; synthetic Meta only, nonce-bound loopback QA operations.

No real SDK/provider requests or sends are permitted by this harness.
"""
from tests.safety import install_test_safety
install_test_safety()
import secrets
import sys
from datetime import datetime, timezone
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select

from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_WHATSAPP_ONBOARDING_ENABLED = False
settings.V1_CHANNEL_TESTS_ENABLED = False
settings.PUBLIC_BASE_URL = 'https://127.0.0.1:8171'
settings.WHATSAPP_EMBEDDED_APP_ID = '123'
settings.WHATSAPP_EMBEDDED_CONFIG_ID = '789'
settings.WHATSAPP_EMBEDDED_GRAPH_VERSION = 'v26.0'
settings.WHATSAPP_EMBEDDED_APP_SECRET = settings.WHATSAPP_APP_SECRET = 'synthetic-matching-app-secret'
settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = 'synthetic-verify-only'
settings.CHANNEL_ENCRYPTION_KEY = Fernet.generate_key().decode()

from app.main import app
from app.api.v1.whatsapp_self_service import provider_dependency
from app.api.v1.session import require_v1_mutation
from app.database import get_db, worker_session
from app.models.identity import Membership
from app.models.whatsapp import WhatsAppMessage
from app.models.whatsapp_self_service import WhatsAppSignupAttempt, WhatsAppConnectionTest, WhatsAppTestAuthorization
from app.services import whatsapp_provider
from app.services.identity import require_business_access
from app.services.whatsapp_test_protocol import FIXED_REPLY
from app.workers.whatsapp import deliver_one
from tests.whatsapp_self_service_fixture import SyntheticSignupProvider

nonce = sys.argv[3]
provider = SyntheticSignupProvider()
app.dependency_overrides[provider_dependency] = lambda: provider
provider_sends = []
assert len([r for r in app.routes if getattr(r, 'path', None) == '/v1/businesses/{business_id}/channels/whatsapp/setup']) == 1

async def synthetic_send(account, contact, message):
    assert message.text == FIXED_REPLY and message.payload == {} and message.kind == 'text'
    # The actual installed worker must independently authorize this exact FK.
    provider_sends.append(message.id)
    return 'synthetic-outbound-' + str(message.id)

whatsapp_provider.send = synthetic_send

def fixture(request):
    if not secrets.compare_digest(request.headers.get('X-Local-Fixture', ''), nonce):
        raise HTTPException(403)

@app.get('/__wa_setup/identify')
async def identify():
    return {'nonce': nonce, 'actual_main_router': True, 'synthetic_provider': True,
            'provider_sends': len(provider_sends), 'operations': dict(provider.calls)}

@app.post('/__wa_setup/{business_id}/{action}')
async def command(business_id: UUID, action: str, request: Request,
                  actor=Depends(require_v1_mutation), db=Depends(get_db)):
    fixture(request)
    access = await require_business_access(db, actor, business_id, 'business.read')
    if access.role != 'owner':
        raise HTTPException(403)
    if action == 'enable-synthetic':
        settings.V1_WHATSAPP_ONBOARDING_ENABLED = settings.V1_CHANNEL_TESTS_ENABLED = True
    elif action == 'viewer':
        member = await db.scalar(select(Membership).where(Membership.business_id == business_id,
                                                        Membership.user_id == actor.user_id))
        member.role = 'viewer'
    elif action == 'snapshot':
        return {'attempts': await db.scalar(select(func.count()).select_from(WhatsAppSignupAttempt).where(
                    WhatsAppSignupAttempt.business_id == business_id)),
                'tests': await db.scalar(select(func.count()).select_from(WhatsAppConnectionTest).where(
                    WhatsAppConnectionTest.business_id == business_id)),
                'authorizations': await db.scalar(select(func.count()).select_from(WhatsAppTestAuthorization).where(
                    WhatsAppTestAuthorization.business_id == business_id)),
                'provider_sends': len(provider_sends), 'operations': dict(provider.calls)}
    else:
        raise HTTPException(422)
    return {'synthetic_fixture_only': True}

@app.post('/__wa_setup/{business_id}/deliver/{test_id}')
async def deliver(business_id: UUID, test_id: UUID, request: Request,
                  actor=Depends(require_v1_mutation), db=Depends(get_db)):
    fixture(request)
    access = await require_business_access(db, actor, business_id, 'business.read')
    if access.role != 'owner':
        raise HTTPException(403)
    mid = await db.scalar(select(WhatsAppTestAuthorization.outbound_message_id).where(
        WhatsAppTestAuthorization.test_id == test_id, WhatsAppTestAuthorization.business_id == business_id))
    if mid is None:
        raise HTTPException(404)
    # Release the read transaction before the canonical worker's own lock scope.
    await db.rollback()
    await deliver_one(mid, worker_session)
    return {'synthetic_provider_sends': len(provider_sends)}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8171, log_level='warning',
                ssl_certfile=sys.argv[1], ssl_keyfile=sys.argv[2])
