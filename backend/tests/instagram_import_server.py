"""Actual mounted app with synthetic owned-provider transport, no network providers."""
from tests.safety import install_test_safety
install_test_safety()
import hashlib,json
from datetime import timedelta
from uuid import UUID
from fastapi import Depends
from sqlalchemy import select
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_IMPORTS_ENABLED=False
settings.V1_INSTAGRAM_OWNED_MEDIA_ENABLED=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8158'
from app.main import app
from app.database import AsyncSessionLocal,get_db
from app.api.v1.session import require_v1_mutation
from app.services.identity import require_business_access
from app.models.seller import Seller
from app.models.channel_operator import ChannelConnectionState
from app.models.imports_v1 import ImportAsset
from app.services import imports_v1 as jobs,instagram_imports
from app.v1.imports.instagram_owned import OwnedResponse
ACCOUNT='178400000000071';MEDIA='180000000000071';CONTENT=b'\x89PNG\r\n\x1a\nsynthetic-exact-source-bytes'
assert sum(getattr(r,'path',None)=='/api/v1/businesses/{business_id}/imports/candidates/{candidate_id}/originals' for r in app.routes)==1
counts={'graph':0,'asset':0}
class Synthetic:
    async def request(self,request):
        from urllib.parse import urlsplit
        path=urlsplit(request.url).path
        if path.endswith('/me'):data={'user_id':ACCOUNT,'account_type':'BUSINESS'}
        elif path.endswith('/'+ACCOUNT+'/media'):data={'data':[{'id':MEDIA,'media_type':'IMAGE','media_url':'https://scontent.cdninstagram.com/original.png','caption':'Rs999 stock10 publish now'}]}
        else:
            assert request.url=='https://scontent.cdninstagram.com/original.png' and request.token is None
            counts['asset']+=1
            return OwnedResponse(200,{'content-type':'image/png'},CONTENT,request.pinned_ip)
        counts['graph']+=1
        return OwnedResponse(200,{'content-type':'application/json'},json.dumps(data).encode(),request.pinned_ip)
original_factory=instagram_imports.provider_for
def provider_for(sessions,claim):
    provider=original_factory(sessions,claim)
    async def resolve(_):return ('93.184.216.34',)
    provider.resolver=resolve;provider.transport=Synthetic()
    return provider
instagram_imports.provider_for=provider_for

@app.post('/__owned-test/businesses/{bid}/connect')
async def connect(bid:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,bid,'channels.connect')
    seller=await db.get(Seller,bid)
    seller.instagram_id=seller.instagram_page_id=seller.fb_page_id=ACCOUNT
    seller.instagram_token='synthetic-only';seller.instagram_token_expires_at=jobs.now()+timedelta(hours=1)
    db.add(ChannelConnectionState(business_id=bid,channel='instagram',version=1,provider_account_id=ACCOUNT,automation_enabled=False))
    return {'configured':True,'provider_verified':False}

@app.post('/__owned-test/businesses/{bid}/jobs/{jid}/run')
async def run(bid:UUID,jid:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,bid,'catalogue.write')
    return {'processed':await jobs.run_job(AsyncSessionLocal,bid,jid)}

@app.get('/__owned-test/status')
async def status():return {'synthetic_requests':counts,'sha256':hashlib.sha256(CONTENT).hexdigest(),'actual_mount':True}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8158,log_level='warning')
