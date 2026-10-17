"""Dedicated8157 native API/module harness, strictly synthetic Razorpay transport.

This tests the owned payment module before the separately owned public shell is
composed. It is not a real gateway test or a customer-facing checkout UI.
"""
from tests.safety import install_test_safety
install_test_safety()
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_PUBLIC_PAYMENTS_ENABLED = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:8157'
settings.PAYMENT_ENCRYPTION_KEY = Fernet.generate_key().decode()
from app.main import app
from app.api.v1.checkout_sessions import router, configuration_router
from app.services import razorpay_payments as payments
app.include_router(router)
app.include_router(configuration_router)
app.mount('/payment-test-assets', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'frontend/storefront/src'))
orders, calls = {}, []
fault = {'next_post': False}


async def synthetic_gateway(account, method, path, data=None):
    calls.append((method, path))
    if method == 'POST' and path == 'orders':
        provider_id = 'order_' + data['receipt'].replace('-', '')
        result = {'id': provider_id, **data}
        orders[provider_id] = result
        if fault['next_post']:
            fault['next_post'] = False
            raise HTTPException(502, 'Synthetic committed provider response lost')
        return result
    if method == 'GET' and path.startswith('orders/'):
        provider_id = path.split('/')[1]
        return orders[provider_id]
    if method == 'GET' and path.startswith('payments/pay_'):
        provider_id = 'order_' + path.removeprefix('payments/pay_')
        order = orders[provider_id]
        return {'id': path.removeprefix('payments/'), 'order_id': provider_id,
            'amount': order['amount'], 'currency': order['currency'], 'status': 'captured', 'captured': True}
    raise AssertionError('Unexpected synthetic provider call')

payments.gateway_request = synthetic_gateway


@app.get('/__payment_test')
async def harness():
    return HTMLResponse('<title>Synthetic payment module harness</title><h1>Synthetic payment module harness</h1><p>Fake SDK and provider only. Not a real payment.</p><button id="open">Open test checkout</button><output id="result"></output>')


@app.post('/__payment_test/drop-next-provider-response')
async def drop_next():
    fault['next_post'] = True
    return {'synthetic': True}


@app.get('/__payment_test/counts')
async def counts():
    return {'provider_posts': sum(method == 'POST' for method, _ in calls), 'synthetic': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8157, log_level='warning')
