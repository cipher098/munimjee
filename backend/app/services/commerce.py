"""Checkout primitives. Prices and inventory are authoritative in PostgreSQL."""
import hashlib
import hmac
import json
from urllib.parse import urlsplit, unquote
from uuid import UUID
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from app.config import settings
from app.models.commerce import CommerceOrder, CommerceCustomer
from app.models.product import Product


def safe_url(value):
    if not value or not isinstance(value, str) or any(c in value for c in ('\\', '\r', '\n', '\x00')):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme == 'https' and hostname and not parsed.username and not parsed.password:
        return value
    if value.startswith('/uploads/') and '..' not in unquote(parsed.path) and not parsed.netloc:
        return value
    return None


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class StoreInput(Input):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r'^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$')
    description: str = Field(default='', max_length=3000)
    logo_url: str | None = Field(default=None, max_length=2000)
    contact_email: str = Field(default='', max_length=254)
    contact_phone: str = Field(default='', max_length=30)
    shipping_policy: str = Field(default='', max_length=5000)
    return_policy: str = Field(default='', max_length=5000)
    currency: Literal['INR'] = 'INR'
    shipping_fee: int = Field(default=0, ge=0, le=10000000, strict=True)
    cod_enabled: bool = True
    published: bool = False

    @field_validator('logo_url')
    @classmethod
    def valid_logo(cls, value):
        if not value:
            return None
        if not safe_url(value):
            raise ValueError('Use an HTTPS image URL or an uploaded image')
        return value


class CustomerInput(Input):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=10, max_length=20)
    email: str | None = Field(default=None, max_length=254)

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        value = value.replace(' ', '').replace('-', '')
        if value.startswith('+91'):
            value = value[3:]
        if len(value) != 10 or not value.isascii() or not value.isdigit() or value[0] not in '6789':
            raise ValueError('Enter a valid 10 digit Indian mobile number')
        return '+91' + value

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        if value and ('@' not in value or '.' not in value.rsplit('@', 1)[-1] or ' ' in value):
            raise ValueError('Enter a valid email address')
        return value or None


class AddressInput(Input):
    line1: str = Field(min_length=3, max_length=200)
    line2: str = Field(default='', max_length=200)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(pattern=r'^[1-9][0-9]{5}$')
    country: Literal['IN'] = 'IN'


class ItemInput(Input):
    product_id: UUID
    quantity: int = Field(ge=1, le=20, strict=True)
    variant_label: str | None = Field(default=None, max_length=200)


class CheckoutInput(Input):
    idempotency_key: UUID
    customer: CustomerInput
    address: AddressInput
    items: list[ItemInput] = Field(min_length=1, max_length=50)
    note: str = Field(default='', max_length=2000)
    payment_method: Literal['cod', 'razorpay'] = 'cod'
    whatsapp_updates_opt_in: bool = Field(default=False, strict=True)


class TransitionInput(Input):
    status: Literal['confirmed', 'packed', 'shipped', 'delivered', 'cancelled']
    carrier: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=200)
    tracking_url: str | None = Field(default=None, max_length=2000)

    @field_validator('tracking_url')
    @classmethod
    def valid_tracking(cls, value):
        if value and (not safe_url(value) or not value.startswith('https://')):
            raise ValueError('Tracking URL must use HTTPS')
        return value or None


def product_json(product):
    variants = []
    for variant in product.variants or []:
        if isinstance(variant, dict) and isinstance(variant.get('label'), str) and variant['label'].strip():
            variants.append({'label': variant['label'], 'photo_urls': [u for u in (variant.get('photo_urls') or []) if safe_url(u)]})
    return {'id': str(product.id), 'name': product.name, 'description': product.description or '',
            'category_id': str(product.category_id) if product.category_id else None,
            'price': product.listed_price, 'photo_url': safe_url(product.photo_url),
            'photo_urls': [u for u in (product.photo_urls or []) if safe_url(u)], 'variants': variants,
            'in_stock': product.stock_quantity is None or product.stock_quantity > 0,
            'stock_quantity': product.stock_quantity}


def order_token(order):
    # Domain separation prevents using an order capability as an auth/OAuth token.
    message = f'commerce-order-v1:{order.seller_id}:{order.id}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def order_json(order, include_token=False):
    result = {k: getattr(order, k) for k in ('customer', 'address', 'note', 'subtotal', 'shipping_fee', 'total', 'currency', 'payment_method', 'payment_status', 'fulfillment_status', 'carrier', 'tracking_number', 'tracking_url', 'created_at', 'updated_at', 'expires_at')}
    result.update(id=str(order.id), number='MJ-' + order.id.hex[:12].upper(),
                  items=[{k: v for k, v in item.items() if not k.startswith('_')} for item in order.items])
    if include_token:
        result['access_token'] = order_token(order)
    return result


async def create_order(db, store, payload):
    """Caller MUST hold the storefront row lock until commit. Returns (order, replay).

    Store lock serializes idempotency/customer creation per seller. Product locks are
    acquired in stable UUID order, including against concurrent inventory edits.
    This uses aggregate product stock: variants do not have independent inventory.
    """
    details = payload.model_dump(mode='json', exclude={'idempotency_key'})
    # Preserve hashes for pre-opt-in checkouts; true is an intentional change.
    if not details['whatsapp_updates_opt_in']:
        details.pop('whatsapp_updates_opt_in')
    digest = hashlib.sha256(json.dumps(details, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    existing = await db.scalar(select(CommerceOrder).where(CommerceOrder.seller_id == store.seller_id, CommerceOrder.idempotency_key == payload.idempotency_key))
    if existing:
        if not hmac.compare_digest(existing.request_hash, digest):
            raise HTTPException(409, 'This checkout key was already used for different order details')
        return existing, True
    if payload.payment_method == 'razorpay':
        from app.services.razorpay_payments import require_gateway
        await require_gateway(db, store.seller_id)
    if payload.payment_method == 'cod' and not store.cod_enabled:
        raise HTTPException(409, 'Cash on delivery is unavailable')
    ids = sorted({item.product_id for item in payload.items}, key=str)
    products = (await db.scalars(select(Product).where(Product.seller_id == store.seller_id, Product.active.is_(True), Product.id.in_(ids)).order_by(Product.id).with_for_update())).all()
    by_id = {p.id: p for p in products}
    if len(by_id) != len(ids):
        raise HTTPException(404, 'A product is no longer available')
    quantities = {}
    snapshots = []
    seen = set()
    for item in payload.items:
        product = by_id[item.product_id]
        key = (item.product_id, item.variant_label)
        if key in seen:
            raise HTTPException(422, 'Combine duplicate cart items into one quantity')
        seen.add(key)
        variants = product_json(product)['variants']
        labels = {v['label'] for v in variants}
        if (labels and item.variant_label not in labels) or (not labels and item.variant_label is not None):
            raise HTTPException(422, f'Select an available option for {product.name}')
        if product.listed_price < 0 or product.listed_price > 100000000:
            raise HTTPException(409, 'A product price is unavailable')
        quantities[product.id] = quantities.get(product.id, 0) + item.quantity
        variant = next((v for v in variants if v['label'] == item.variant_label), None)
        photo = (variant['photo_urls'][0] if variant and variant['photo_urls'] else safe_url(product.photo_url))
        snapshots.append({'product_id': str(product.id), 'name': product.name, 'variant_label': item.variant_label,
                          'quantity': item.quantity, 'unit_price': product.listed_price,
                          'line_total': product.listed_price * item.quantity, 'photo_url': photo,
                          '_stock_reserved': product.stock_quantity is not None})
    for pid, quantity in quantities.items():
        product = by_id[pid]
        if quantity > 20:
            raise HTTPException(422, 'Maximum 20 units per product')
        if product.stock_quantity is not None:
            if product.stock_quantity < quantity:
                raise HTTPException(409, f'Insufficient stock for {product.name}')
            product.stock_quantity -= quantity
    customer = await db.scalar(select(CommerceCustomer).where(CommerceCustomer.seller_id == store.seller_id, CommerceCustomer.phone == payload.customer.phone))
    if customer is None:
        customer = CommerceCustomer(seller_id=store.seller_id, **payload.customer.model_dump())
        db.add(customer)
        await db.flush()
    # Existing customer identity is not overwritten by unverified public checkout.
    # Every order has its own submitted contact snapshot for seller review.
    subtotal = sum(item['line_total'] for item in snapshots)
    if subtotal + store.shipping_fee > 2000000000:
        raise HTTPException(422, 'Order total exceeds the supported maximum')
    order = CommerceOrder(seller_id=store.seller_id, customer_id=customer.id,
        idempotency_key=payload.idempotency_key, request_hash=digest,
        customer=payload.customer.model_dump(), address=payload.address.model_dump(), items=snapshots,
        note=payload.note, subtotal=subtotal, shipping_fee=store.shipping_fee, total=subtotal + store.shipping_fee,
        currency='INR', payment_method=payload.payment_method, whatsapp_updates_opt_in=payload.whatsapp_updates_opt_in,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=20)) if payload.payment_method == 'razorpay' else None)
    db.add(order)
    await db.flush()
    return order, False


async def release_stock(db, order):
    """Caller must lock the order. Repeated cancellation/expiry restores stock once."""
    if order.stock_released:
        return
    quantities = {}
    for item in order.items:
        if item.get('_stock_reserved'):
            pid = UUID(item['product_id'])
            quantities[pid] = quantities.get(pid, 0) + item['quantity']
    if quantities:
        products = (await db.scalars(select(Product).where(Product.seller_id == order.seller_id, Product.id.in_(quantities)).order_by(Product.id).with_for_update())).all()
        for product in products:
            # If the merchant intentionally stopped tracking this product, leave it untracked.
            if product.stock_quantity is not None:
                product.stock_quantity += quantities[product.id]
    order.stock_released = True


async def expire_pending_orders(db, seller_id):
    """Caller holds storefront lock; reclaim expired reservations before new checkout."""
    orders = (await db.scalars(select(CommerceOrder).where(
        CommerceOrder.seller_id == seller_id, CommerceOrder.payment_method == 'razorpay',
        CommerceOrder.payment_status == 'pending', CommerceOrder.expires_at <= datetime.now(timezone.utc),
        CommerceOrder.fulfillment_status == 'pending').order_by(CommerceOrder.id).with_for_update())).all()
    for order in orders:
        await release_stock(db, order)
        order.payment_status = 'expired'
        order.fulfillment_status = 'cancelled'
    await db.flush()


def authorize_order(order, authorization):
    if not order or not authorization or not authorization.startswith('Bearer ') or not hmac.compare_digest(authorization[7:].encode(), order_token(order).encode()):
        raise HTTPException(404, 'Order not found')
    return order
