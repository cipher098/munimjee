"""Only the versioned local-readiness gate can advertise online payment."""
import json
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet
from app.config import settings
from app.models.commerce import Storefront
from app.models.razorpay import RazorpayAccount
from app.services import razorpay_payments as payments
from app.services.storefront_publication import PublishedStorefrontProvider
from tests.test_storefront_publication import public_api,setup  # noqa:F401


@pytest.mark.asyncio
async def test_public_api_and_ssr_advertise_only_locally_usable_enabled_gateway(public_api,monkeypatch):
    client,factory=public_api;data=await setup(client)
    monkeypatch.setattr(settings,'PAYMENT_ENCRYPTION_KEY',Fernet.generate_key().decode())
    async def forbidden(*args,**kwargs):raise AssertionError('Publication must not contact payment provider')
    monkeypatch.setattr(payments,'gateway_request',forbidden)
    async with factory.begin() as db:
        db.add(RazorpayAccount(seller_id=data['bid'],key_id='rzp_test_synthetic',key_secret=payments.encrypt('synthetic-key'),
            webhook_secret=payments.encrypt('synthetic-webhook-key'),mode='test',enabled=True))
        (await db.get(Storefront,data['bid'])).cod_enabled=False
    path=f"/api/v1/storefronts/{data['slug']}"
    assert (await client.get(path)).json()['payment_options']['razorpay_enabled'] is False
    async with factory() as db:
        assert (await PublishedStorefrontProvider(db).public_store(data['slug'])).payment_methods==()
    monkeypatch.setattr(settings,'V1_PUBLIC_PAYMENTS_ENABLED',True)
    ready=(await client.get(path)).json()
    assert ready['payment_options']==dict(cod_enabled=False,razorpay_enabled=True,razorpay_mode='test')
    response=await client.get('/stores/'+data['slug'])
    bootstrap=json.loads(response.text.split('id="storefront-data" type="application/json">')[1].split('</script>')[0])
    assert bootstrap['store']['payment_methods']==['razorpay'] and bootstrap['capabilities']['sku_checkout'] is True
    policy=response.headers['content-security-policy']
    assert 'script-src \'self\' https://checkout.razorpay.com https://cdn.razorpay.com;' in policy
    assert 'frame-src https://api.razorpay.com;' in policy and 'unsafe-inline' not in policy and '*' not in policy
    for private in ('synthetic-key','synthetic-webhook-key','key_secret','webhook_secret','gateway_credentials'):
        assert private not in response.text
    # Misconfigured/rotated local ciphertext withholds new purchase advertisement.
    async with factory.begin() as db:(await db.get(RazorpayAccount,data['bid'])).key_secret='invalid-local-ciphertext'
    assert (await client.get(path)).json()['payment_options']['razorpay_enabled'] is False
    async with factory() as db:
        assert (await PublishedStorefrontProvider(db).public_store(data['slug'])).checkout_enabled is False
