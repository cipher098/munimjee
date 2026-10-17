"""Only local native browser fixture; existing app routes/auth remain authoritative."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio,json,sys
from pathlib import Path
from uuid import UUID,uuid4
from fastapi import Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_PARCEL_ENABLED=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8156'
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.services.identity import Actor,require_business_access
from app.models.parcel_tracking import ParcelConnector
from app.models.commerce import CommerceOrder
from app.services.parcel_connector import ParcelAdapter
from app.services import parcel_tracking as service
from tests.parcel_transport import NodeConnectorTransport

class BridgeAdapter(ParcelAdapter):
    def __init__(self,connector):super().__init__(connector,transport=NodeConnectorTransport())
original_process,original_preview=service.process_link,service.preview
async def process(db,link_id,**kwargs):return await original_process(db,link_id,adapter_factory=BridgeAdapter,**kwargs)
async def preview(*args,**kwargs):return await original_preview(*args,adapter_factory=BridgeAdapter,**kwargs)
service.process_link,service.preview=process,preview

@app.post('/__synthetic/businesses/{business_id}/parcel-connector')
async def provision(business_id:UUID,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    access=await require_business_access(db,actor,business_id,'channels.connect')
    if access.role!='owner':raise HTTPException(403,'Synthetic owner required')
    # Test-only equivalent of explicit operator provisioning; no customer/provider
    # credentials are used, and this endpoint is never registered in production.
    instance=uuid4();config={'business_id':str(business_id),'instance_id':str(instance),'secret':'synthetic-parcel-machine-secret-at-least32characters'}
    Path(sys.argv[1]).write_text(json.dumps(config))
    settings.V1_PARCEL_ALLOWED_ORIGINS=['http://127.0.0.1:8155']
    settings.V1_PARCEL_CONNECTORS_JSON=json.dumps({'synthetic':{**config,'origin':'http://127.0.0.1:8155','key_id':'synthetic','enabled':True}})
    db.add(ParcelConnector(business_id=business_id,instance_id=instance,origin='http://127.0.0.1:8155',credential_ref='synthetic',enabled=True))
    return {'configured':True}

@app.get('/__synthetic/businesses/{business_id}/orders/{order_id}/remote')
async def remote_id(business_id:UUID,order_id:UUID,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    await service.access_order(db,actor,business_id,order_id,write=True)
    from app.models.parcel_tracking import OrderParcelLink
    row=await db.scalar(select(OrderParcelLink).where(OrderParcelLink.business_id==business_id,OrderParcelLink.order_id==order_id))
    return {'remote_id':str(row.remote_id) if row and row.remote_id else None}
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8156,log_level='warning')
