"""Public storefront API and tenant-scoped seller commerce management."""
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dashboard_auth import current_seller_id
from app.database import get_db
from app.models.seller import Seller
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.commerce import Storefront, CommerceOrder, CommerceCustomer
from app.services.commerce import (StoreInput, CheckoutInput, TransitionInput, product_json,
    order_json, create_order, release_stock, authorize_order, expire_pending_orders)

seller_router = APIRouter(prefix='/commerce', tags=['commerce'])
public_router = APIRouter(prefix='/shop-api', tags=['storefront'])


def store_json(store):
    return {key: getattr(store, key) for key in StoreInput.model_fields}


async def get_public_store(db, slug, *, lock=False, published=True):
    stmt = select(Storefront).join(Seller, Seller.id == Storefront.seller_id).where(Storefront.slug == slug, Seller.is_active.is_(True))
    if published:
        stmt = stmt.where(Storefront.published.is_(True))
    if lock:
        stmt = stmt.with_for_update(of=Storefront)
    store = await db.scalar(stmt)
    if store is None:
        raise HTTPException(404, 'Store not found')
    return store


async def seller_order(db, seller_id, order_id, lock=False):
    stmt = select(CommerceOrder).where(CommerceOrder.id == order_id, CommerceOrder.seller_id == seller_id)
    if lock:
        stmt = stmt.with_for_update()
    order = await db.scalar(stmt)
    if not order:
        raise HTTPException(404, 'Order not found')
    return order


@seller_router.get('/store')
async def read_store(seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    store = await db.get(Storefront, seller_id)
    return store_json(store) if store else None


@seller_router.put('/store')
async def save_store(payload: StoreInput, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    seller = await db.scalar(select(Seller).where(Seller.id == seller_id, Seller.is_active.is_(True)).with_for_update())
    if not seller:
        raise HTTPException(404, 'Seller not found')
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == seller_id).with_for_update())
    if store and store.slug != payload.slug and await db.scalar(select(CommerceOrder.id).where(CommerceOrder.seller_id == seller_id).limit(1)):
        raise HTTPException(409, 'The store URL cannot change after receiving orders')
    if not store:
        store = Storefront(seller_id=seller.id)
        db.add(store)
    for key, value in payload.model_dump().items():
        setattr(store, key, value)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'This store URL is already taken')
    return store_json(store)


@public_router.get('/{slug}')
async def public_store(slug: str, db: AsyncSession = Depends(get_db)):
    store = await get_public_store(db, slug)
    data = store_json(store)
    data.pop('published')
    categories = (await db.scalars(select(ProductCategory).where(ProductCategory.seller_id == store.seller_id).order_by(ProductCategory.name))).all()
    data['categories'] = [{'id': str(c.id), 'name': c.name} for c in categories]
    return data


@public_router.get('/{slug}/products')
async def public_products(slug: str, q: str = Query('', max_length=200), category_id: UUID | None = None,
        page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    store = await get_public_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    where = [Product.seller_id == store.seller_id, Product.active.is_(True)]
    if q.strip():
        where.append(or_(Product.name.ilike('%' + q.strip() + '%'), Product.description.ilike('%' + q.strip() + '%')))
    if category_id:
        where.append(Product.category_id == category_id)
    total = await db.scalar(select(func.count()).select_from(Product).where(*where))
    products = (await db.scalars(select(Product).where(*where).order_by(Product.created_at.desc(), Product.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [product_json(p) for p in products], 'total': total, 'page': page, 'page_size': page_size}


@public_router.get('/{slug}/products/{product_id}')
async def public_product(slug: str, product_id: UUID, db: AsyncSession = Depends(get_db)):
    store = await get_public_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    product = await db.scalar(select(Product).where(Product.id == product_id, Product.seller_id == store.seller_id, Product.active.is_(True)))
    if product is None:
        raise HTTPException(404, 'Product not found')
    return product_json(product)


@public_router.post('/{slug}/checkout', status_code=201)
async def checkout(slug: str, payload: CheckoutInput, response: Response, db: AsyncSession = Depends(get_db)):
    store = await get_public_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    order, replay = await create_order(db, store, payload)
    if payload.payment_method == 'razorpay' and order.total < 100:
        raise HTTPException(422, 'Online payment requires a minimum order total of ₹1')
    response.status_code = 200 if replay else 201
    response.headers['Cache-Control'] = 'no-store'
    return order_json(order, include_token=True)


@public_router.get('/{slug}/orders/{order_id}')
async def public_order(slug: str, order_id: UUID, response: Response,
        authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    store = await get_public_store(db, slug, lock=True, published=False)
    order = await db.scalar(select(CommerceOrder).where(CommerceOrder.seller_id == store.seller_id, CommerceOrder.id == order_id))
    authorize_order(order, authorization)
    await expire_pending_orders(db, store.seller_id)
    response.headers['Cache-Control'] = 'no-store'
    return order_json(order)


@seller_router.get('/orders')
async def orders(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
        seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == seller_id).with_for_update())
    if store:
        await expire_pending_orders(db, store.seller_id)
    where = [CommerceOrder.seller_id == seller_id]
    if status:
        if status not in ('pending', 'confirmed', 'packed', 'shipped', 'delivered', 'cancelled'):
            raise HTTPException(422, 'Unknown fulfillment status')
        where.append(CommerceOrder.fulfillment_status == status)
    total = await db.scalar(select(func.count()).select_from(CommerceOrder).where(*where))
    rows = (await db.scalars(select(CommerceOrder).where(*where).order_by(CommerceOrder.created_at.desc(), CommerceOrder.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [order_json(o) for o in rows], 'total': total, 'page': page, 'page_size': page_size}


@seller_router.get('/orders/{order_id}')
async def order_detail(order_id: UUID, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == seller_id).with_for_update())
    if store:
        await expire_pending_orders(db, store.seller_id)
    return order_json(await seller_order(db, seller_id, order_id))


@seller_router.post('/orders/{order_id}/transition')
async def transition(order_id: UUID, payload: TransitionInput, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    # Lock store before order/product, the same order as checkout/expiry, to avoid deadlocks.
    await db.scalar(select(Storefront).where(Storefront.seller_id == seller_id).with_for_update())
    await expire_pending_orders(db, seller_id)
    order = await seller_order(db, seller_id, order_id, lock=True)
    current = order.fulfillment_status
    if current == payload.status:
        return order_json(order)
    if payload.status == 'cancelled':
        if current not in ('pending', 'confirmed', 'packed'):
            raise HTTPException(409, 'Shipped or delivered orders cannot be cancelled here')
        await release_stock(db, order)
        # Online paid cancellations require manual refund reconciliation; never silently
        # claim a refund. Root payment integration handles settlement authority.
        order.payment_status = 'review_required' if order.payment_status == 'paid' else 'cancelled'
    else:
        transitions = {'pending': 'confirmed', 'confirmed': 'packed', 'packed': 'shipped', 'shipped': 'delivered'}
        if transitions.get(current) != payload.status:
            raise HTTPException(409, 'Invalid order status transition')
        if order.payment_method == 'razorpay' and order.payment_status != 'paid':
            raise HTTPException(409, 'Online payment must be verified before fulfillment')
    if payload.status == 'shipped':
        order.carrier = payload.carrier
        order.tracking_number = payload.tracking_number
        order.tracking_url = payload.tracking_url
    order.fulfillment_status = payload.status
    await db.flush()
    return order_json(order)


@seller_router.post('/orders/{order_id}/collect-cod')
async def collect_cod(order_id: UUID, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    order = await seller_order(db, seller_id, order_id, lock=True)
    if order.payment_method != 'cod' or order.fulfillment_status != 'delivered':
        raise HTTPException(409, 'Only delivered COD orders can be marked collected')
    order.payment_status = 'collected'
    await db.flush()
    return order_json(order)


def customer_json(customer, orders):
    paid = [o for o in orders if o.payment_status in ('collected', 'paid')]
    return {'id': str(customer.id), 'name': customer.name, 'phone': customer.phone, 'email': customer.email,
            'order_count': len(orders), 'total_spent': sum(o.total for o in paid),
            'last_order_at': max((o.created_at for o in orders), default=None)}


@seller_router.get('/customers')
async def customers(q: str = Query('', max_length=200), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
        seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    where = [CommerceCustomer.seller_id == seller_id]
    if q.strip():
        where.append(or_(CommerceCustomer.name.ilike('%' + q.strip() + '%'), CommerceCustomer.phone.ilike('%' + q.strip() + '%'), CommerceCustomer.email.ilike('%' + q.strip() + '%')))
    total = await db.scalar(select(func.count()).select_from(CommerceCustomer).where(*where))
    rows = (await db.scalars(select(CommerceCustomer).where(*where).order_by(CommerceCustomer.created_at.desc(), CommerceCustomer.id).offset((page - 1) * page_size).limit(page_size))).all()
    order_rows = (await db.scalars(select(CommerceOrder).where(CommerceOrder.seller_id == seller_id, CommerceOrder.customer_id.in_([c.id for c in rows])))).all() if rows else []
    return {'items': [customer_json(c, [o for o in order_rows if o.customer_id == c.id]) for c in rows], 'total': total, 'page': page, 'page_size': page_size}


@seller_router.get('/customers/{customer_id}')
async def customer_detail(customer_id: UUID, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    customer = await db.scalar(select(CommerceCustomer).where(CommerceCustomer.id == customer_id, CommerceCustomer.seller_id == seller_id))
    if not customer:
        raise HTTPException(404, 'Customer not found')
    rows = (await db.scalars(select(CommerceOrder).where(CommerceOrder.customer_id == customer.id, CommerceOrder.seller_id == seller_id).order_by(CommerceOrder.created_at.desc()))).all()
    return {**customer_json(customer, rows), 'orders': [order_json(o) for o in rows]}
