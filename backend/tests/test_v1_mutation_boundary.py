"""Actual-app native writes rollback if authority changes during a lock wait."""
import asyncio
from datetime import datetime,timezone
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,update,text,func
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.commerce import Storefront,CommerceOrder
from app.models.product import Product
from app.models.catalogue_v1 import CatalogueSKU,CatalogueProductMapping
from tests.test_v1_import_integration import api  # noqa:F401 actual app.main fixture
from tests.test_storefront_publication import setup,checkout


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['store','create','policy','activate','skus','metadata','review','backfill','transition','collect'])
@pytest.mark.parametrize('revocation',['role','session'])
async def test_native_mutation_final_guard_precedes_real_commit(api,operation,revocation):
    client,factory=api
    data=await setup(client,stock=3,publish=operation in ('transition','collect'),activate=operation not in ('activate','review'))
    prefix=data['prefix'];bid=data['bid'];pid=data['pid']
    before=(await client.get(prefix+f'/products/{pid}')).json()
    method='POST';path='';body={};lock_model=Storefront;lock_id=bid
    if operation=='store':method='PUT';path=prefix+'/storefront';body={**data['store'],'name':'Unauthorized changed shop','published':True}
    if operation=='create':
        path=prefix+'/products';body={'idempotency_key':str(uuid4()),'seller_reviewed':True,'name':'Unauthorized new dress',
            'skus':[dict(options={},price_minor=20000,currency='INR',stock_available=2,active=True)]}
    if operation=='policy':method='PUT';path=prefix+'/checkout-policy';body={'checkout_enabled':False}
    if operation=='activate':path=prefix+f'/products/{pid}/activate';body={'seller_reviewed':True,'expected_mapping_revision':before['mapping_revision'],'expected_legacy_fingerprint':before['legacy_fingerprint']}
    if operation=='skus':method='PUT';path=prefix+f'/products/{pid}/skus';body={'seller_reviewed':True,'expected_mapping_revision':before['mapping_revision'],'skus':[{**row,'stock_available':9} for row in before['skus']]}
    if operation=='metadata':method='PATCH';path=prefix+f'/products/{pid}';body={'seller_reviewed':True,'expected_mapping_revision':before['mapping_revision'],'name':'Unauthorized changed dress','description':'','photo_urls':[]}
    if operation=='review':method='PUT';path=prefix+f'/products/{pid}/review';body={'seller_reviewed':True,'expected_mapping_revision':before['mapping_revision'],'expected_legacy_fingerprint':before['legacy_fingerprint'],'skus':before['skus']}
    if operation=='backfill':
        pid=uuid4()
        async with factory.begin() as db:db.add(Product(id=pid,seller_id=bid,name='Legacy synthetic',listed_price=10000,floor_price=0,stock_quantity=1,active=True))
        path=prefix+f'/products/{pid}/backfill'
    if operation in ('transition','collect'):
        placed=await client.post(f"/api/v1/storefronts/{data['slug']}/checkout",json=checkout(data['sku']))
        assert placed.status_code==201,placed.text
        oid=UUID(placed.json()['id'])
        if operation=='transition':path=f'/api/v1/businesses/{bid}/orders/{oid}/transition';body={'status':'confirmed'}
        else:
            async with factory.begin() as db:await db.execute(update(CommerceOrder).where(CommerceOrder.id==oid).values(fulfillment_status='delivered'))
            path=f'/api/v1/businesses/{bid}/orders/{oid}/collect-cod';lock_model=CommerceOrder;lock_id=oid
    task=None
    try:
        async with factory() as holder:
            holder_pid=await holder.scalar(text('SELECT pg_backend_pid()'))
            clause=Storefront.seller_id==lock_id if lock_model is Storefront else CommerceOrder.id==lock_id
            await holder.scalar(select(lock_model).where(clause).with_for_update())
            task=asyncio.create_task(client.request(method,path,json=body,headers=data['headers']))
            for _ in range(200):
                await holder.execute(text('SELECT pg_stat_clear_snapshot()'))
                waiting=await holder.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))'),{'pid':holder_pid})
                if waiting:break
                await asyncio.sleep(.01)
            assert waiting
            if revocation=='role':await holder.execute(update(Membership).where(Membership.business_id==bid).values(role='viewer'))
            else:await holder.execute(update(UserSession).where(UserSession.user_id.in_(select(Membership.user_id).where(Membership.business_id==bid))).values(revoked_at=datetime.now(timezone.utc)))
            await holder.commit()
            response=await asyncio.wait_for(task,8)
            assert response.status_code==(403 if revocation=='role' else 401),response.text
        async with factory() as db:
            product=await db.get(Product,pid)
            if operation=='store':assert (await db.get(Storefront,bid)).name==data['store']['name']
            if operation=='create':assert await db.scalar(select(func.count()).select_from(Product).where(Product.seller_id==bid))==1
            if operation=='policy':
                from app.models.checkout_v1 import CatalogueStorePolicy
                assert (await db.get(CatalogueStorePolicy,bid)).checkout_enabled is True
            if operation=='activate':assert product.active is False
            if operation=='skus':assert (await db.get(CatalogueSKU,data['sku'])).stock_available==3
            if operation=='metadata':assert product.name=='Synthetic Indigo Dress'
            if operation=='review':assert (await db.get(CatalogueProductMapping,(bid,pid))).revision==before['mapping_revision']
            if operation=='backfill':assert await db.get(CatalogueProductMapping,(bid,pid)) is None
            if operation=='transition':assert (await db.get(CommerceOrder,oid)).fulfillment_status=='pending'
            if operation=='collect':assert (await db.get(CommerceOrder,oid)).payment_status=='pending'
    finally:
        if task is not None and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_store_save_and_manual_catalogue_create_do_not_deadlock(api):
    from app.services.checkout_v1 import lock_store,create_reviewed_product
    from app.schemas.checkout_v1 import ProductCreate
    from app.api.routes.commerce import save_store
    from app.services.commerce import StoreInput
    client,factory=api;data=await setup(client)
    task=None
    try:
        async with factory() as manual:
            pid=await manual.scalar(text('SELECT pg_backend_pid()'))
            await lock_store(manual,data['bid'])
            async def save():
                async with factory() as db:
                    result=await save_store(StoreInput.model_validate(data['store']),str(data['bid']),db)
                    await db.commit();return result
            task=asyncio.create_task(save())
            for _ in range(200):
                await manual.execute(text('SELECT pg_stat_clear_snapshot()'))
                waiting=await manual.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))'),{'pid':pid})
                if waiting:break
                await asyncio.sleep(.01)
            assert waiting
            await asyncio.wait_for(create_reviewed_product(manual,data['bid'],ProductCreate(seller_reviewed=True,
                idempotency_key=uuid4(),name='Concurrent draft',skus=[dict(options={},stock_available=1,price_minor=10000,currency='INR',active=True)])),5)
            await manual.commit()
        assert (await asyncio.wait_for(task,5))['slug']==data['slug']
    finally:
        if task is not None and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_native_payment_reconcile_defers_commit_until_final_authority_check(api,monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings
    from app.models.razorpay import RazorpayAccount
    from app.services import razorpay_payments as payments
    client,factory=api;data=await setup(client,stock=2)
    placed=await client.post(f"/api/v1/storefronts/{data['slug']}/checkout",json=checkout(data['sku']))
    assert placed.status_code==201,placed.text
    order=placed.json();oid=UUID(order['id'])
    monkeypatch.setattr(settings,'PAYMENT_ENCRYPTION_KEY',Fernet.generate_key().decode())
    async with factory.begin() as db:
        account=RazorpayAccount(seller_id=data['bid'],key_id='rzp_test_synthetic',key_secret=payments.encrypt('synthetic-secret'),
            webhook_secret=payments.encrypt('synthetic-webhook-secret'),mode='test',enabled=True)
        db.add(account)
        row=await db.get(CommerceOrder,oid);row.payment_method='razorpay';row.gateway_order_id='order_synthetic'
        row.gateway_credentials=payments.snapshot_account(account)
    calls=[]
    async def fake_provider(account,method,path,payload=None):
        calls.append((method,path))
        assert method=='GET' and path=='orders/order_synthetic/payments'
        async with factory.begin() as db:
            await db.execute(update(Membership).where(Membership.business_id==data['bid']).values(role='viewer'))
        return {'items':[dict(id='pay_synthetic',order_id='order_synthetic',amount=order['total'],currency='INR',status='captured',captured=True)]}
    monkeypatch.setattr(payments,'gateway_request',fake_provider)
    result=await client.post(f"/api/v1/businesses/{data['bid']}/orders/{oid}/reconcile-payment",headers=data['headers'])
    assert result.status_code==403,result.text
    assert len(calls)==1
    async with factory() as db:
        row=await db.get(CommerceOrder,oid)
        assert row.payment_status=='pending' and row.gateway_payment_id is None
