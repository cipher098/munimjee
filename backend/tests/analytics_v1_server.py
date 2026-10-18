"""Actual mounted application, synthetic credentials, no providers."""
from tests.safety import install_test_safety
install_test_safety()
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8163'
from app.main import app
from app.services import razorpay_payments
mounted=[route for route in app.routes if getattr(route,'path',None)=='/v1/businesses/{business_id}/analytics']
assert len(mounted)==1 and mounted[0].endpoint.__module__=='app.api.v1.analytics_v1'
provider_calls=[]
async def forbidden(*args,**kwargs):
    provider_calls.append(True)
    raise AssertionError('Analytics has no provider operations')
razorpay_payments.gateway_request=forbidden


@app.get('/__analytics-test/status')
async def status():return {'provider_calls':len(provider_calls),'synthetic':True,'actual_main_mount':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8163,log_level='warning')
