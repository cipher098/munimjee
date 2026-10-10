"""Real HTTP/transaction tests against an isolated database ending commerce_test."""
import asyncio
import os
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.database import Base, get_db
import app.models
from app.models.seller import Seller
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.commerce import Storefront, CommerceOrder
from app.api.routes.commerce import public_router, seller_router
from app.api.dashboard_auth import _make_token


@pytest_asyncio.fixture
async def commerce():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url or not url.rsplit('/', 1)[-1].endswith('commerce_test'):
        pytest.skip('Set TEST_DATABASE_URL to an isolated database ending commerce_test')
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        sellers = [Seller(email=f'{i}@shop.test', password_hash='unused', business_name=f'Shop {i}') for i in range(2)]
        db.add_all(sellers)
        await db.flush()
        categories = [ProductCategory(seller_id=s.id, name='Kurtas') for s in sellers]
        db.add_all(categories)
        await db.flush()
        products = [Product(seller_id=s.id, category_id=c.id, name=f'Kurta {i}', listed_price=250000, floor_price=180000, description='Cotton', stock_quantity=5, photo_url='https://example.com/photo.jpg', photo_urls=['javascript:alert(1)', '/uploads/photo.jpg'], variants=[{'label':'Red', 'photo_urls':[]}]) for i,(s,c) in enumerate(zip(sellers,categories))]
        db.add_all(products)
        db.add_all([Storefront(seller_id=s.id, name=f'Shop {i}', slug=f'shop-{i}', published=True, shipping_fee=5000) for i,s in enumerate(sellers)])
        await db.commit()
        ids = {'sellers':[s.id for s in sellers], 'products':[p.id for p in products], 'categories':[c.id for c in categories]}
    app = FastAPI()
    app.include_router(public_router)
    app.include_router(seller_router)
    async def session():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, factory, ids
    await engine.dispose()


def auth(ids, n=0):
    return {'dashboard_session': _make_token('seller', str(ids['sellers'][n]), 'test')}


def payload(ids, **changes):
    data = {'idempotency_key':str(uuid4()), 'customer':{'name':'Test Customer','phone':'9876543210','email':'buyer@example.com'}, 'address':{'line1':'12 Test Street','city':'Jaipur','state':'Rajasthan','postal_code':'302001','country':'IN'}, 'items':[{'product_id':str(ids['products'][0]), 'quantity':1, 'variant_label':'Red'}]}
    data.update(changes)
    return data


async def place(client, ids, **changes):
    result = await client.post('/shop-api/shop-0/checkout', json=payload(ids, **changes))
    assert result.status_code == 201, result.text
    return result.json()


@pytest.mark.asyncio
async def test_public_whitelist_filters_and_visibility(commerce):
    client, factory, ids = commerce
    r = await client.get('/shop-api/shop-0/products?q=Kurta&category_id=' + str(ids['categories'][0]))
    assert r.status_code == 200
    assert r.json()['total'] == 1
    p = r.json()['items'][0]
    assert set(p) == {'id','name','description','category_id','price','photo_url','photo_urls','variants','in_stock','stock_quantity'}
    assert p['photo_urls'] == ['/uploads/photo.jpg']
    assert (await client.get('/shop-api/shop-0/products/' + str(ids['products'][1]))).status_code == 404
    assert (await client.get('/shop-api/shop-0/products?q=unknown')).json()['total'] == 0
    async with factory() as db:
        (await db.get(Product, ids['products'][0])).active = False
        await db.commit()
    assert (await client.get('/shop-api/shop-0/products')).json()['total'] == 0
    assert (await client.get('/shop-api/shop-0/products/' + str(ids['products'][0]))).status_code == 404
    async with factory() as db:
        (await db.get(Storefront, ids['sellers'][0])).published = False
        await db.commit()
    assert (await client.get('/shop-api/shop-0')).status_code == 404
    assert (await client.post('/shop-api/shop-0/checkout', json=payload(ids))).status_code == 404


@pytest.mark.asyncio
async def test_store_configuration_and_tenant_scope(commerce):
    client, factory, ids = commerce
    data = {'name':'My Boutique','slug':'my-boutique','published':True,'shipping_fee':6000}
    r = await client.put('/commerce/store', cookies=auth(ids), json=data)
    assert r.status_code == 200, r.text
    assert (await client.get('/commerce/store', cookies=auth(ids,1))).json()['slug'] == 'shop-1'
    assert (await client.put('/commerce/store', cookies=auth(ids,1), json=data)).status_code == 409
    assert (await client.put('/commerce/store', cookies=auth(ids), json={**data,'logo_url':'javascript:bad'})).status_code == 422
    assert (await client.put('/commerce/store', json=data)).status_code == 302


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['foreign','variant','missing_variant','price','negative','float','duplicate'])
async def test_invalid_cart_is_atomic(commerce, invalid):
    client, factory, ids = commerce
    data = payload(ids)
    item = data['items'][0]
    if invalid == 'foreign': item['product_id'] = str(ids['products'][1])
    if invalid == 'variant': item['variant_label'] = 'Blue'
    if invalid == 'missing_variant': item.pop('variant_label')
    if invalid == 'price': item['unit_price'] = 1
    if invalid == 'negative': item['quantity'] = -1
    if invalid == 'float': item['quantity'] = 1.5
    if invalid == 'duplicate': data['items'].append(dict(item))
    r = await client.post('/shop-api/shop-0/checkout', json=data)
    assert r.status_code in (404,422), r.text
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 5
        assert not (await db.scalars(select(CommerceOrder))).all()


@pytest.mark.asyncio
async def test_checkout_totals_immutable_snapshot_and_capability(commerce):
    client, factory, ids = commerce
    order = await place(client, ids)
    assert order['subtotal'] == 250000 and order['total'] == 255000
    assert order['payment_status'] == 'pending' and order['payment_method'] == 'cod'
    assert '_stock_reserved' not in order['items'][0]
    path = '/shop-api/shop-0/orders/' + order['id']
    assert (await client.get(path)).status_code == 404
    assert (await client.get(path, headers={'Authorization':'Bearer wrong'})).status_code == 404
    async with factory() as db:
        product = await db.get(Product, ids['products'][0])
        product.name = 'Renamed'
        product.listed_price = 999
        (await db.get(Storefront, ids['sellers'][0])).published = False
        await db.commit()
    r = await client.get(path, headers={'Authorization':'Bearer ' + order['access_token']})
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
    assert r.json()['items'][0]['name'] == 'Kurta 0' and r.json()['total'] == 255000
    assert (await client.get('/shop-api/shop-1/orders/' + order['id'], headers={'Authorization':'Bearer ' + order['access_token']})).status_code == 404
    assert (await client.get('/commerce/orders/' + order['id'], cookies=auth(ids,1))).status_code == 404
    assert (await client.get('/commerce/orders', cookies=auth(ids,1))).json()['total'] == 0
    assert (await client.get('/commerce/orders', cookies=auth(ids))).json()['total'] == 1
    customers = (await client.get('/commerce/customers', cookies=auth(ids))).json()['items']
    assert len(customers) == 1 and customers[0]['total_spent'] == 0
    assert (await client.get('/commerce/customers/' + customers[0]['id'], cookies=auth(ids,1))).status_code == 404


@pytest.mark.asyncio
async def test_retry_and_changed_payload_cannot_duplicate(commerce):
    client, factory, ids = commerce
    data = payload(ids)
    one, two = await asyncio.gather(client.post('/shop-api/shop-0/checkout', json=data), client.post('/shop-api/shop-0/checkout', json=data))
    assert sorted([one.status_code,two.status_code]) == [200,201]
    assert one.json()['id'] == two.json()['id'] and one.json()['access_token'] == two.json()['access_token']
    data['items'][0]['quantity'] = 2
    assert (await client.post('/shop-api/shop-0/checkout', json=data)).status_code == 409
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 4
        assert len((await db.scalars(select(CommerceOrder))).all()) == 1


@pytest.mark.asyncio
async def test_concurrent_checkout_cannot_oversell(commerce):
    client, factory, ids = commerce
    async with factory() as db:
        (await db.get(Product, ids['products'][0])).stock_quantity = 1
        await db.commit()
    results = await asyncio.gather(*(client.post('/shop-api/shop-0/checkout', json=payload(ids)) for _ in range(4)))
    assert sorted(r.status_code for r in results) == [201,409,409,409]
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 0


@pytest.mark.asyncio
async def test_cancel_releases_once_and_is_tenant_scoped(commerce):
    client, factory, ids = commerce
    order = await place(client, ids)
    path = '/commerce/orders/' + order['id'] + '/transition'
    assert (await client.post(path, cookies=auth(ids,1), json={'status':'cancelled'})).status_code == 404
    for _ in range(2):
        r = await client.post(path, cookies=auth(ids), json={'status':'cancelled'})
        assert r.status_code == 200 and r.json()['payment_status'] == 'cancelled'
    assert (await client.post(path, cookies=auth(ids), json={'status':'confirmed'})).status_code == 409
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 5


@pytest.mark.asyncio
async def test_fulfillment_does_not_falsely_collect_cod(commerce):
    client, factory, ids = commerce
    order = await place(client, ids)
    path = '/commerce/orders/' + order['id']
    assert (await client.post(path+'/collect-cod', cookies=auth(ids))).status_code == 409
    assert (await client.post(path+'/transition', cookies=auth(ids),json={'status':'delivered'})).status_code == 409
    for status in ('confirmed','packed','shipped','delivered'):
        r = await client.post(path+'/transition', cookies=auth(ids),json={'status':status, 'tracking_url':'https://carrier.test/track'})
        assert r.status_code == 200, r.text
        assert r.json()['payment_status'] == 'pending'
    assert (await client.post(path+'/transition', cookies=auth(ids),json={'status':'cancelled'})).status_code == 409
    assert (await client.post(path+'/collect-cod', cookies=auth(ids))).json()['payment_status'] == 'collected'
    assert (await client.get('/commerce/customers', cookies=auth(ids))).json()['items'][0]['total_spent'] == 255000


@pytest.mark.asyncio
async def test_expired_online_inventory_reclaimed_and_no_fulfillment(commerce):
    client, factory, ids = commerce
    order = await place(client, ids)
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order['id']))
        saved.payment_method = 'razorpay'
        saved.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    r = await client.get('/commerce/orders',cookies=auth(ids))
    assert r.json()['items'][0]['payment_status'] == 'expired'
    assert r.json()['items'][0]['fulfillment_status'] == 'cancelled'
    assert (await client.post('/commerce/orders/'+order['id']+'/transition', cookies=auth(ids),json={'status':'confirmed'})).status_code == 409
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 5


@pytest.mark.asyncio
async def test_cod_disabled_and_replays_survive_disable(commerce):
    client, factory, ids = commerce
    data = payload(ids)
    created = await client.post('/shop-api/shop-0/checkout', json=data)
    assert created.status_code == 201
    async with factory() as db:
        (await db.get(Storefront, ids['sellers'][0])).cod_enabled = False
        await db.commit()
    assert (await client.post('/shop-api/shop-0/checkout', json=payload(ids))).status_code == 409
    assert (await client.post('/shop-api/shop-0/checkout', json=data)).json()['id'] == created.json()['id']


@pytest.mark.asyncio
async def test_aggregate_variant_quantities_and_untracked_inventory(commerce):
    client, factory, ids = commerce
    async with factory() as db:
        product = await db.get(Product, ids['products'][0])
        product.variants = [{'label':'Red'},{'label':'Blue'}]
        await db.commit()
    data = payload(ids, items=[{'product_id':str(ids['products'][0]),'quantity':3,'variant_label':v} for v in ('Red','Blue')])
    assert (await client.post('/shop-api/shop-0/checkout', json=data)).status_code == 409
    async with factory() as db:
        product = await db.get(Product, ids['products'][0])
        assert product.stock_quantity == 5
        product.stock_quantity = None
        await db.commit()
    order = (await client.post('/shop-api/shop-0/checkout', json=data)).json()
    assert order['total'] == 1505000
    await client.post('/commerce/orders/'+order['id']+'/transition', cookies=auth(ids), json={'status':'cancelled'})
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity is None


@pytest.mark.asyncio
async def test_catalogue_refresh_reclaims_expired_stock(commerce):
    client, factory, ids = commerce
    async with factory() as db:
        (await db.get(Product, ids['products'][0])).stock_quantity = 1
        await db.commit()
    order = await place(client, ids)
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order['id']))
        saved.payment_method = 'razorpay'
        saved.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    r = await client.get('/shop-api/shop-0/products')
    assert r.json()['items'][0]['stock_quantity'] == 1 and r.json()['items'][0]['in_stock']
    await client.get('/shop-api/shop-0/products/' + str(ids['products'][0]))
    async with factory() as db:
        assert (await db.get(Product, ids['products'][0])).stock_quantity == 1


@pytest.mark.asyncio
async def test_pending_online_cannot_fulfill_or_collect_cod(commerce):
    client, factory, ids = commerce
    order = await place(client, ids)
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order['id']))
        saved.payment_method = 'razorpay'
        saved.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        await db.commit()
    path = '/commerce/orders/' + order['id']
    assert (await client.post(path+'/transition',cookies=auth(ids),json={'status':'confirmed'})).status_code == 409
    assert (await client.post(path+'/collect-cod',cookies=auth(ids))).status_code == 409


@pytest.mark.asyncio
async def test_inactive_seller_and_invalid_pagination(commerce):
    client, factory, ids = commerce
    assert (await client.get('/shop-api/shop-0/products?page=0')).status_code == 422
    assert (await client.get('/shop-api/shop-0/products?page_size=101')).status_code == 422
    async with factory() as db:
        (await db.get(Seller, ids['sellers'][0])).is_active = False
        await db.commit()
    assert (await client.get('/shop-api/shop-0')).status_code == 404
    assert (await client.post('/shop-api/shop-0/checkout',json=payload(ids))).status_code == 404


@pytest.mark.asyncio
async def test_store_slug_stable_after_orders_and_invalid_images(commerce):
    client, factory, ids = commerce
    await place(client, ids)
    assert (await client.put('/commerce/store',cookies=auth(ids),json={'name':'Renamed','slug':'new-url'})).status_code == 409
    assert (await client.put('/commerce/store',cookies=auth(ids),json={'name':'Renamed','slug':'shop-0','logo_url':'https://['})).status_code == 422
    async with factory() as db:
        product = await db.get(Product,ids['products'][0])
        product.photo_url = 'https://['
        product.photo_urls = ['/uploads/%2e%2e/private', 'javascript:alert(1)']
        await db.commit()
    r = await client.get('/shop-api/shop-0/products/' + str(ids['products'][0]))
    assert r.status_code == 200 and r.json()['photo_url'] is None and r.json()['photo_urls'] == []
