"""Real native setup, migrated SKU publication and canonical COD; no providers."""
import json
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api.v1.auth import router as auth_router
from app.api.v1.catalogue import router as catalogue_router
from app.api.v1.storefront import create_router
from app.config import settings
from app.database import get_db
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, SKUReservation, SKUPaymentAttempt
from app.models.commerce import Storefront, CommerceOrder, CommerceCustomer
from app.models.identity import Business
from app.models.product import Product
from app.models.seller import Seller
from app.services.storefront_publication import published_storefront_provider, PublishedStorefrontProvider


@pytest_asyncio.fixture
async def public_api(migrated_engine,monkeypatch):
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','http://store.test')
    app=FastAPI();app.include_router(auth_router);app.include_router(catalogue_router)
    app.include_router(create_router(canonical_base='https://configured.example.test',provider_dependency=published_storefront_provider))
    factory=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:yield db;await db.commit()
            except Exception:await db.rollback();raise
    app.dependency_overrides[get_db]=database
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://store.test',headers={'Origin':'http://store.test'}) as client:
        yield client,factory


async def setup(client,*,stock=2,publish=True,activate=True):
    owner=await client.post('/api/v1/auth/signup',json={'email':f'{uuid4().hex}@example.com','password':'synthetic-store-password','business_name':'Synthetic SKU boutique'})
    assert owner.status_code==201,owner.text
    bid=owner.json()['businesses'][0]['id'];prefix=f'/api/v1/businesses/{bid}/catalogue';slug='synthetic-'+uuid4().hex[:10]
    headers={'X-CSRF-Token':client.cookies['v1_csrf']}
    store={'name':'Synthetic SKU boutique','slug':slug,'description':'Reviewed synthetic catalogue','currency':'INR','shipping_fee':5000,'cod_enabled':True,'published':publish,'shipping_policy':'Delivery terms supplied by the synthetic shop.','return_policy':'Contact this synthetic shop before a return.'}
    saved=await client.put(prefix+'/storefront',json=store,headers=headers);assert saved.status_code==200,saved.text
    created=await client.post(prefix+'/products',headers=headers,json={'idempotency_key':str(uuid4()),'seller_reviewed':True,'name':'Synthetic Indigo Dress','description':'Approved medium indigo dress','photo_urls':[],'skus':[{'options':{'Size':'M'},'price_minor':129950,'currency':'INR','stock_available':stock,'active':True}]})
    assert created.status_code==201,created.text
    draft=created.json();pid=draft['product']['product_id'];sku=draft['skus'][0]['sku_id']
    if activate:
        result=await client.post(prefix+f'/products/{pid}/activate',headers=headers,json={'seller_reviewed':True,'expected_mapping_revision':draft['mapping_revision'],'expected_legacy_fingerprint':draft['legacy_fingerprint']})
        assert result.status_code==200,result.text
    assert (await client.put(prefix+'/checkout-policy',json={'checkout_enabled':True},headers=headers)).status_code==200
    return {'bid':UUID(bid),'pid':UUID(pid),'sku':UUID(sku),'slug':slug,'prefix':prefix,'headers':headers,'store':store}


def checkout(sku):
    return {'idempotency_key':str(uuid4()),'customer':{'name':'Synthetic Buyer','phone':'9876543210','email':None},'address':{'line1':'Synthetic Street','line2':'','city':'Bengaluru','state':'Karnataka','postal_code':'560001','country':'IN'},'items':[{'sku_id':str(sku),'quantity':1}],'note':'','payment_method':'cod','whatsapp_updates_opt_in':False}


@pytest.mark.asyncio
async def test_native_setup_published_activated_sku_ssr_and_cod_replay(public_api):
    client,factory=public_api;data=await setup(client,stock=1)
    record=(await client.get(data['prefix']+f"/products/{data['pid']}")).json()
    writes=record['skus'];writes[0]['price_minor']=239950
    edited=await client.put(data['prefix']+f"/products/{data['pid']}/skus",headers=data['headers'],json={'seller_reviewed':True,'expected_mapping_revision':record['mapping_revision'],'skus':writes})
    assert edited.status_code==200,edited.text
    response=await client.get(f"/stores/{data['slug']}/products/{data['pid']}")
    assert response.status_code==200,response.text
    assert 'Synthetic Indigo Dress' in response.text and '₹2,399.50 INR' in response.text and '₹1,299.50 INR' not in response.text and 'In stock' in response.text
    for secret in ('99000000','88000000','floor_price','stock_quantity','password_hash','access_token'):
        assert secret not in response.text
    assert 'https://configured.example.test/stores/' in response.text and 'store.test/stores/' not in response.text
    body=checkout(data['sku']);path=f"/api/v1/storefronts/{data['slug']}/checkout"
    placed=await client.post(path,json=body);assert placed.status_code==201,placed.text
    order=placed.json();assert order['total']==244950 and order['payment_status']=='pending'
    replay=await client.post(path,json=body);assert replay.status_code==200 and replay.json()==order
    status=f"/api/v1/storefronts/{data['slug']}/orders/{order['id']}"
    assert (await client.get(status)).status_code==404
    assert (await client.get(status,params={'token':order['access_token']})).status_code==404
    assert (await client.get(status,headers={'Authorization':'Bearer '+order['access_token']})).status_code==200
    async with factory() as db:
        assert (await db.get(CatalogueSKU,data['sku'])).stock_available==0
        assert await db.scalar(select(func.count()).select_from(CommerceOrder))==1
        assert await db.scalar(select(func.count()).select_from(SKUReservation))==1
    shell=await client.get(f"/stores/{data['slug']}/orders/{order['id']}")
    assert shell.status_code==200 and shell.headers['cache-control']=='no-store' and shell.headers['x-robots-tag']=='noindex, nofollow'
    assert order['access_token'] not in shell.text and 'Synthetic Buyer' not in shell.text


@pytest.mark.asyncio
@pytest.mark.parametrize('gate',['unpublished','inactive_seller','inactive_business','unactivated','inactive_product','inactive_sku'])
async def test_publication_never_falls_back_to_drafts_or_legacy(public_api,gate):
    client,factory=public_api;data=await setup(client)
    async with factory.begin() as db:
        if gate=='unpublished':(await db.get(Storefront,data['bid'])).published=False
        elif gate=='inactive_seller':(await db.get(Seller,data['bid'])).is_active=False
        elif gate=='inactive_business':(await db.get(Business,data['bid'])).is_active=False
        elif gate=='unactivated':await db.delete(await db.get(CatalogueActivation,(data['bid'],data['pid'])))
        elif gate=='inactive_product':(await db.get(Product,data['pid'])).active=False
        else:(await db.get(CatalogueSKU,data['sku'])).active=False
    response=await client.get(f"/stores/{data['slug']}/products/{data['pid']}")
    assert response.status_code==404 and response.headers['x-robots-tag']=='noindex, nofollow'
    assert 'Synthetic Indigo Dress' not in response.text


@pytest.mark.asyncio
async def test_typed_stock_rejection_has_no_order_customer_reservation_or_token(public_api):
    client,factory=public_api;data=await setup(client,stock=0)
    result=await client.post(f"/api/v1/storefronts/{data['slug']}/checkout",json=checkout(data['sku']))
    assert result.status_code==409 and result.json()=={'detail':{'code':'sku_out_of_stock','message':'Selected quantity is no longer available.'}}
    assert 'access_token' not in result.text
    async with factory() as db:
        for model in (CommerceOrder,CommerceCustomer,SKUReservation,SKUPaymentAttempt):
            assert await db.scalar(select(func.count()).select_from(model))==0
        assert (await db.get(CatalogueSKU,data['sku'])).stock_available==0


@pytest.mark.asyncio
async def test_all_three_presentations_use_identical_canonical_publication(public_api):
    client,factory=public_api;data=await setup(client)
    from app.v1.storefront.rendering import render_storefront
    async with factory() as db:
        for theme in ('catalogue','editorial','video'):
            store=await PublishedStorefrontProvider(db,theme=theme).public_store(data['slug'])
            html=render_storefront(store,'https://configured.example.test')
            assert f'data-theme="{theme}"' in html and 'Synthetic Indigo Dress' in html
            assert store.payment_methods==('cod',) and store.checkout_enabled


@pytest.mark.asyncio
async def test_seller_store_link_uses_enabled_publication_and_configured_origin(public_api, monkeypatch):
    client,factory=public_api;data=await setup(client)
    path=data['prefix']+'/storefront'
    assert (await client.get(path)).json()['public_storefront_url'] is None
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','https://configured.example')
    response=await client.get(path,headers={'Host':'untrusted.example'})
    assert response.status_code==200
    assert response.json()['public_storefront_url']=='https://configured.example/stores/'+data['slug']
    async with factory.begin() as db:
        (await db.get(Storefront,data['bid'])).published=False
    assert (await client.get(path)).json()['public_storefront_url'] is None


@pytest.mark.asyncio
async def test_gateway_only_store_never_advertises_unimplemented_browser_payment(public_api, monkeypatch):
    client,factory=public_api;data=await setup(client)
    from app.models.razorpay import RazorpayAccount
    from app.services import razorpay_payments as payments
    from app.api.routes.razorpay import payment_options
    monkeypatch.setattr(payments,'cipher',lambda: object())  # configuration only; no provider I/O
    async with factory.begin() as db:
        (await db.get(Storefront,data['bid'])).cod_enabled=False
        db.add(RazorpayAccount(seller_id=data['bid'],key_id='rzp_test_synthetic',key_secret='synthetic-unused',webhook_secret='synthetic-unused',mode='test',enabled=True))
    async with factory() as db:
        assert (await payment_options(data['slug'],db))['razorpay_enabled'] is True
        store=await PublishedStorefrontProvider(db).public_store(data['slug'])
        assert store.payment_methods==() and store.checkout_enabled is False
    response=await client.get(f"/stores/{data['slug']}")
    assert response.status_code==200
    bootstrap=json.loads(response.text.split('<script id="storefront-data" type="application/json">')[1].split('</script>')[0])
    assert bootstrap['store']['payment_methods']==[] and bootstrap['capabilities']['sku_checkout'] is False
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(CommerceOrder))==0
