"""Canonical facts on actual migrated PostgreSQL, no provider transport or metadata DDL."""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import update, event
from app.api.v1.analytics_v1 import router
from app.models.commerce import CommerceCustomer, CommerceOrder
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.schemas.analytics_v1 import Filters
from app.services import analytics_v1 as domain
from tests.test_v1_checkout_api import api, actor  # noqa:F401
from tests.test_v1_checkout import seed


@pytest_asyncio.fixture
async def analytics(api):
    client,factory=api;client._transport.app.include_router(router)
    bid,_,_=await seed(factory)
    headers,token,csrf,sid=await actor(factory,bid)
    return client,factory,bid,headers,token,csrf,sid


def path(bid):return f'/api/v1/businesses/{bid}/analytics'
RANGE={'from_date':'2026-10-18','to_date':'2026-10-19'}


async def fact(factory,bid,*,amount=100,currency='INR',method='cod',payment='pending',fulfillment='pending',
               captured=False,mode=None,created='2026-10-18T10:00:00+00:00'):
    async with factory.begin() as db:
        customer=CommerceCustomer(id=uuid4(),seller_id=bid,name='Private customer marker',phone=str(uuid4())[:20])
        db.add(customer);await db.flush()
        oid=uuid4()
        db.add(CommerceOrder(id=oid,seller_id=bid,customer_id=customer.id,idempotency_key=uuid4(),request_hash='a'*64,
            customer={'name':'Private customer marker'},address={'line1':'Private address marker'},items=[],note='Private note marker',
            subtotal=amount-1,shipping_fee=1,total=amount,currency=currency,payment_method=method,payment_status=payment,
            fulfillment_status=fulfillment,gateway_payment_id='pay_'+oid.hex if captured else None,
            gateway_credentials={'mode':mode,'key_secret':'PRIVATE-CREDENTIAL-MARKER','webhook_secret':'PRIVATE-WEBHOOK-MARKER'} if mode else None,
            created_at=datetime.fromisoformat(created)))
        return oid


@pytest.mark.asyncio
async def test_exact_current_state_cohort_currency_test_exclusion_and_private_allowlist(analytics):
    client,factory,bid,headers,*_=analytics
    await fact(factory,bid,amount=10,method='razorpay',payment='paid',captured=True,mode='live')
    await fact(factory,bid,amount=50,method='razorpay',payment='paid')  # Not captured evidence.
    await fact(factory,bid,amount=20,payment='collected',fulfillment='delivered')
    await fact(factory,bid,amount=30,method='razorpay',payment='review_required',captured=True,mode='live',fulfillment='cancelled')
    await fact(factory,bid,amount=40)
    await fact(factory,bid,amount=5,payment='cancelled',fulfillment='cancelled')
    await fact(factory,bid,amount=7,method='razorpay',payment='expired',fulfillment='cancelled')
    await fact(factory,bid,amount=99,method='razorpay',payment='paid',captured=True,mode='test')
    await fact(factory,bid,amount=11,currency='USD')
    await fact(factory,bid,amount=888,created='2026-10-19T00:00:00+00:00')
    foreign,_,_=await seed(factory);await fact(factory,foreign,amount=999)
    response=await client.get(path(bid),headers=headers,params=RANGE)
    assert response.status_code==200,response.text
    data=response.json();assert data['counts']==dict(placed=8,online_paid=1,cod_collected=1,payment_review=1,cancelled=3,expired=1,unclassified_test_activity=6)
    assert data['currency_totals']==[
        dict(currency='INR',placed_order_value_minor='162',online_paid_minor='10',cod_collected_minor='20',captured_review_minor='30'),
        dict(currency='USD',placed_order_value_minor='11',online_paid_minor='0',cod_collected_minor='0',captured_review_minor='0')]
    assert data['known_gateway_test_excluded']==1 and data['daily']==[dict(date='2026-10-18',placed=8,cancelled=3)]
    assert all(v is None for v in data['unavailable'].values())
    assert response.headers['cache-control']=='no-store'
    for marker in ('Private customer','Private address','Private note','PRIVATE-CREDENTIAL','PRIVATE-WEBHOOK','pay_','gateway_credentials','customer_id'):
        assert marker not in response.text
    assert all(set(order)=={'order_id','created_at','currency','total_minor','payment_method','payment_status','fulfillment_status','test_classification'} for order in data['orders'])
    included=(await client.get(path(bid),headers=headers,params={**RANGE,'include_gateway_test':'true'})).json()
    assert included['counts']['placed']==9 and included['counts']['online_paid']==2 and included['known_gateway_test_excluded']==0
    assert included['currency_totals'][0]['online_paid_minor']=='109'


@pytest.mark.asyncio
async def test_utc_midnight_bounds_filters_and_stable_pagination(analytics):
    client,factory,bid,headers,*_=analytics
    before=await fact(factory,bid,created='2026-10-18T05:29:59+05:30')
    first=await fact(factory,bid,created='2026-10-18T05:30:00+05:30')
    last=await fact(factory,bid,payment='collected',created='2026-10-19T05:29:59+05:30')
    outside=await fact(factory,bid,created='2026-10-19T05:30:00+05:30')
    one=(await client.get(path(bid),headers=headers,params={**RANGE,'page_size':1})).json()
    two=(await client.get(path(bid),headers=headers,params={**RANGE,'page_size':1,'page':2})).json()
    assert one['orders'][0]['order_id']==str(last) and two['orders'][0]['order_id']==str(first)
    assert one['has_next'] is True and two['has_next'] is False
    assert one['counts']['placed']==two['counts']['placed']==2
    selected=(await client.get(path(bid),headers=headers,params={**RANGE,'payment_status':'collected'})).json()
    assert selected['counts']['placed']==1 and selected['orders'][0]['order_id']==str(last)
    assert str(before) not in str(one) and str(outside) not in str(one)


@pytest.mark.asyncio
async def test_empty_and_invalid_filters_are_explicit(analytics):
    client,_,bid,headers,*_=analytics
    response=await client.get(path(bid),headers=headers,params=RANGE)
    assert response.status_code==200 and response.json()['counts']['placed']==0
    assert response.json()['currency_totals']==[] and response.json()['daily']==[dict(date='2026-10-18',placed=0,cancelled=0)]
    for params in ({'from_date':'2020-01-01','to_date':'2026-01-01'},{'from_date':'2026-10-19','to_date':'2026-10-19'},
                   {'payment_status':'refunded'},{'currency':'INR'},{'page_size':51},{'page':1001},
                   [('page','1'),('page','2')]):
        assert (await client.get(path(bid),headers=headers,params=params)).status_code==422


@pytest.mark.asyncio
@pytest.mark.parametrize('role,status',[('owner',200),('manager',200),('viewer',200),('staff',403)])
async def test_native_capability_tenant_shell_and_cookies(analytics,role,status):
    client,factory,bid,_,*_=analytics
    headers,token,csrf,_=await actor(factory,bid,role)
    assert (await client.get(path(bid),headers=headers,params=RANGE)).status_code==status
    shell=await client.get(f'/v1/businesses/{bid}/analytics',headers=headers)
    assert shell.status_code==200 and shell.headers['x-robots-tag']=='noindex, nofollow'
    foreign,_,_=await seed(factory)
    assert (await client.get(path(foreign),headers=headers,params=RANGE)).status_code==404
    client.cookies.set('v1_session',token);client.cookies.set('v1_csrf',csrf)
    assert (await client.get(path(bid),params=RANGE)).status_code==status


@pytest.mark.asyncio
@pytest.mark.parametrize('change,status',[('session',401),('role',403)])
async def test_final_native_read_guard_discards_result_after_authority_change(analytics,monkeypatch,change,status):
    client,factory,bid,headers,token,csrf,sid=analytics
    await fact(factory,bid)
    original=domain.report
    async def changed(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with factory.begin() as other:
            session=await other.get(UserSession,sid)
            if change=='session':session.revoked_at=datetime.now(timezone.utc)
            else:await other.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==session.user_id).values(role='staff'))
        return result
    monkeypatch.setattr(domain,'report',changed)
    response=await client.get(path(bid),headers=headers,params=RANGE)
    assert response.status_code==status and 'currency_totals' not in response.text


@pytest.mark.asyncio
async def test_single_statement_and_large_exact_totals(analytics):
    client,factory,bid,headers,*_=analytics
    for _ in range(3):await fact(factory,bid,amount=2000000000)
    async with factory() as db:
        statements=[]
        def observe(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        event.listen(db.bind.sync_engine,'before_cursor_execute',observe)
        try:
            value=await domain.report(db,bid,Filters(from_date='2026-10-18',to_date='2026-10-19',payment_method=None,
                payment_status=None,fulfillment_status=None,include_gateway_test=False,page=1,page_size=25))
        finally:event.remove(db.bind.sync_engine,'before_cursor_execute',observe)
    assert len(statements)==1 and value.currency_totals[0].placed_order_value_minor=='6000000000'


@pytest.mark.asyncio
@pytest.mark.parametrize('association',[None,''])
@pytest.mark.parametrize('payment',['paid','review_required'])
async def test_missing_or_empty_payment_association_is_not_confirmed_capture(analytics,association,payment):
    client,factory,bid,headers,*_=analytics
    oid=await fact(factory,bid,amount=25,method='razorpay',payment=payment,mode='live')
    async with factory.begin() as db:
        await db.execute(update(CommerceOrder).where(CommerceOrder.id==oid).values(gateway_payment_id=association))
    result=(await client.get(path(bid),headers=headers,params=RANGE)).json()
    assert result['counts']['placed']==1 and result['counts']['online_paid']==0
    assert result['currency_totals'][0]['online_paid_minor']=='0'
    assert result['currency_totals'][0]['captured_review_minor']=='0'
