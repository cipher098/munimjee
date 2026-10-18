"""Synthetic local collection context, real mounted native/API/domain + PG16.

The public module's visibility hooks are invoked by the browser harness, not
claimed to be integrated into the shared storefront shell by this test.
"""
from tests.safety import install_test_safety
install_test_safety()
import sys
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_STOREFRONT_ENABLED=True
settings.V1_ACTIVITY_ENABLED=True
settings.V1_ACTIVITY_RETENTION_READY=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8168'
# Synthetic server classification fixture, never production configuration.
settings.APP_ENV='production'
from app.main import app
from app.api.v1.activity_v1 import router
from app.services import razorpay_payments
if not any(getattr(route,'path',None)=='/api/v1/businesses/{business_id}/analytics/activity' for route in app.routes):
    app.include_router(router)
nonce=sys.argv[1]
calls=[]
async def forbidden(*args,**kwargs):
    calls.append(True);raise AssertionError('No provider calls in measurement')
razorpay_payments.gateway_request=forbidden


@app.get('/__activity/identify')
async def identify():return {'nonce':nonce,'provider_calls':len(calls),'synthetic_classification':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8168,log_level='warning')
