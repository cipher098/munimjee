"""Actual public bootstrap on8158; every gateway/SDK effect is synthetic."""
from tests.safety import install_test_safety
install_test_safety()
import sys
from cryptography.fernet import Fernet
from fastapi import HTTPException
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_STOREFRONT_ENABLED=True
settings.V1_PUBLIC_PAYMENTS_ENABLED=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8158'
settings.PAYMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()
from app.main import app
from app.services import razorpay_payments as payments
nonce=sys.argv[1]
orders={};captures={};calls=[];fault={'drop_next':False}


async def synthetic_gateway(account,method,path,data=None):
    calls.append((method,path))
    if method=='POST' and path=='orders':
        provider_id='order_'+data['receipt'].replace('-','')
        result={'id':provider_id,**data};orders[provider_id]=result
        if fault['drop_next']:
            fault['drop_next']=False
            raise HTTPException(502,'Synthetic committed provider response lost')
        return result
    if method=='GET' and path.startswith('payments/pay_'):
        provider_id='order_'+path.removeprefix('payments/pay_');row=orders[provider_id]
        payment=dict(id=path.removeprefix('payments/'),order_id=provider_id,amount=row['amount'],currency=row['currency'],status='captured',captured=True)
        captures[provider_id]=payment
        return payment
    if method=='GET' and path.startswith('orders/'):
        provider_id=path.split('/')[1]
        if path.endswith('/payments'):return {'items':[captures[provider_id]] if provider_id in captures else []}
        return orders[provider_id]
    raise AssertionError('Unexpected synthetic provider call')
payments.gateway_request=synthetic_gateway


@app.get('/__public_payment/nonce')
async def identify():return {'nonce':nonce}


@app.get('/__public_payment/counts')
async def counts():return {'provider_posts':sum(method=='POST' for method,_ in calls),'provider_orders':len(orders)}


@app.post('/__public_payment/drop-next')
async def drop_next():fault['drop_next']=True;return {'synthetic':True}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8158,log_level='warning')
