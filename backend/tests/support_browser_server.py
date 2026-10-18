"""Actual mounted app.main; test-only provisioning of synthetic native subject."""
from tests.safety import install_test_safety
install_test_safety()
import secrets,sys
from uuid import UUID
from fastapi import Depends,HTTPException,Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_SUPPORT_GRANTS_ENABLED=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8164'
from app.main import app
from app.database import get_db
from app.api.v1.session import require_v1_mutation
from app.services.identity import Actor
nonce=sys.argv[1]
assert len([r for r in app.routes if getattr(r,'path','')=='/v1/support'])==1
assert next(r for r in app.routes if getattr(r,'path','')=='/v1/support').endpoint.__module__=='app.api.v1.support_grants'

@app.post('/__support_fixture/provision')
async def provision(request:Request,actor:Actor=Depends(require_v1_mutation)):
    if not secrets.compare_digest(request.headers.get('X-Local-Fixture',''),nonce):raise HTTPException(403)
    if actor.auth_method!='v1_user':raise HTTPException(401)
    settings.V1_SUPPORT_OPERATOR_IDS=[*settings.V1_SUPPORT_OPERATOR_IDS,actor.user_id]
    return {'provisioned_synthetic_subject':str(actor.user_id)}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8164,log_level='warning')
