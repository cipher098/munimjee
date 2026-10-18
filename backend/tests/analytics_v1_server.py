"""Actual application plus the new owned router, synthetic credentials, no providers."""
from tests.safety import install_test_safety
install_test_safety()
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8163'
from app.main import app
from app.api.v1.analytics_v1 import router
from app.services import razorpay_payments
if not any(getattr(route,'path',None)=='/v1/businesses/{business_id}/analytics' for route in app.routes):
    app.include_router(router)
provider_calls=[]
async def forbidden(*args,**kwargs):
    provider_calls.append(True)
    raise AssertionError('Analytics has no provider operations')
razorpay_payments.gateway_request=forbidden


@app.get('/__analytics-test/status')
async def status():return {'provider_calls':len(provider_calls),'synthetic':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8163,log_level='warning')
