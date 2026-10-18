"""Actual mounted native imports; local worker hooks only, no source/provider I/O."""
from tests.safety import install_test_safety
install_test_safety()
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy import select, update
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_IMPORT_BRIDGE_ENABLED=True
settings.V1_IMPORTS_ENABLED=False  # Explicit local worker hook, not a fake queue.
settings.PUBLIC_BASE_URL='http://127.0.0.1:8165'
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import AsyncSessionLocal, get_db
from app.models.identity import Membership
from app.models.product import Product
from app.models.checkout_v1 import CatalogueActivation
from app.services.identity import require_business_access
from app.services.imports_v1 import run_job
from app.services import razorpay_payments

assert sum(getattr(r,'path',None)=='/v1/businesses/{business_id}/imports' for r in app.routes)==1
assert sum(getattr(r,'path',None)=='/api/v1/businesses/{business_id}/imports/uploads' for r in app.routes)==1
provider_calls=[]
async def forbidden(*args,**kwargs):
    provider_calls.append(True)
    raise AssertionError('CSV must not call external providers')
razorpay_payments.gateway_request=forbidden

class NoNetwork:
    async def fetch(self,*args,**kwargs):return await forbidden()


@app.post('/__csv-test/businesses/{business_id}/jobs/{job_id}/run')
async def process(business_id:UUID,job_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'catalogue.write')
    return {'processed':await run_job(AsyncSessionLocal,business_id,job_id,fetcher=NoNetwork())}


@app.post('/__csv-test/businesses/{business_id}/downgrade')
async def downgrade(business_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'business.write')
    await db.execute(update(Membership).where(Membership.business_id==business_id,Membership.user_id==actor.user_id).values(role='viewer'))
    return {'changed':True}


@app.get('/__csv-test/businesses/{business_id}/products/{product_id}')
async def state(business_id:UUID,product_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'catalogue.read')
    product=await db.get(Product,product_id)
    if product is None or product.seller_id!=business_id:raise HTTPException(404)
    return {'active':product.active,'activated':await db.get(CatalogueActivation,(business_id,product_id)) is not None}


@app.get('/__csv-test/status')
async def status():return {'provider_calls':len(provider_calls),'actual_mount':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8165,log_level='warning')
