"""Local mounted application, synthetic encryption, zero allowed provider calls."""
from tests.safety import install_test_safety
install_test_safety()
from cryptography.fernet import Fernet
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_PUBLIC_PAYMENTS_ENABLED=False
settings.PUBLIC_BASE_URL='http://127.0.0.1:8162'
settings.PAYMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()
from app.main import app
from app.api.v1.payment_settings import router
from app.services import razorpay_payments
# The integration owner registers this router in main. Avoid duplicate test mounts
# once that shared registration is consumed.
if not any(getattr(route,'path',None)=='/v1/businesses/{business_id}/payments' for route in app.routes):
    app.include_router(router)
provider_calls=[]
async def forbidden(*args,**kwargs):
    provider_calls.append(True)
    raise AssertionError('Payment settings must not call a provider')
razorpay_payments.gateway_request=forbidden


@app.get('/__payment-settings-test/status')
async def status():
    return {'provider_calls':len(provider_calls),'public_payments_enabled':settings.V1_PUBLIC_PAYMENTS_ENABLED,'synthetic':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8162,log_level='warning')
