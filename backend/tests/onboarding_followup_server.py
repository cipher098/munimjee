"""Owned local fixture: production app.main routes, guarded PG, no providers."""
from tests.safety import install_test_safety
install_test_safety()
import sys
from uuid import UUID
from fastapi import Header, HTTPException
from sqlalchemy import text, update
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_STOREFRONT_ENABLED = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:8170'
from app.main import app
from app.database import AsyncSessionLocal
from app.models.identity import Membership

from app.services import channel_connections, razorpay_payments
provider_calls = []
async def forbidden_provider(*args, **kwargs):
    provider_calls.append(True)
    raise AssertionError('Native onboarding authorizes no provider request')
channel_connections.ig.InstagramClient.send_message = forbidden_provider
channel_connections.whatsapp_provider.graph = forbidden_provider
channel_connections.whatsapp_provider.send = forbidden_provider
razorpay_payments.gateway_request = forbidden_provider
nonce = sys.argv[1]
assert len([r for r in app.routes if getattr(r, 'path', '') == '/api/v1/businesses/{business_id}/onboarding']) == 1


@app.get('/__onboarding/identify')
async def identify():
    async with AsyncSessionLocal() as db:
        revision = await db.scalar(text('SELECT version_num FROM alembic_version'))
    return {'nonce': nonce, 'revision': revision, 'mounted': 'app.main', 'provider_calls': len(provider_calls)}


@app.post('/__onboarding/viewer')
async def viewer(business_id: UUID, user_id: UUID, x_fixture_nonce: str = Header('')):
    if x_fixture_nonce != nonce:
        raise HTTPException(404)
    async with AsyncSessionLocal.begin() as db:
        await db.execute(update(Membership).where(Membership.business_id == business_id,
            Membership.user_id == user_id).values(role='viewer'))
    return {'role': 'viewer'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8170, log_level='warning')
