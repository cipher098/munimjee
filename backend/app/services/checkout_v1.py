"""One explicit SKU writer; existing commerce order/payment authority is retained."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, or_
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueCreation, CatalogueStorePolicy, SKUReservation
from app.models.commerce import CommerceCustomer, CommerceOrder, Storefront
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.schemas.catalogue_v1 import SKURead
from app.schemas.checkout_v1 import ProductRead
from app.services.catalogue_v1 import legacy_fingerprint, serialize_preview, validate_review, CatalogueConflict
from app.services.commerce import safe_url


ENGINE = "sku.v1"


def conflict(message):
    raise HTTPException(409, message)


def request_hash(payload):
    data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    # Preserve every historical financial hash; only the new nullable field is omitted.
    if data.get("activity_context_id") is None:
        data.pop("activity_context_id", None)
    return hashlib.sha256(json.dumps(data,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def lock_store(db, business_id):
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == business_id).with_for_update())
    if store is None:
        conflict("Configure the storefront before catalogue operations")
    if store.currency != "INR":
        conflict("This catalogue supports INR only")
    return store


async def is_product_activated(db, business_id, product_id):
    return await db.get(CatalogueActivation, (business_id, product_id)) is not None


async def require_legacy_products(db, business_id, product_ids):
    activated = await db.scalar(select(CatalogueActivation.product_id).where(
        CatalogueActivation.business_id == business_id, CatalogueActivation.product_id.in_(product_ids)).limit(1))
    if activated is not None:
        conflict("Select a SKU using the current storefront; legacy checkout is disabled for this product")


async def rows_for_product(db, business_id, product_id):
    product = await db.scalar(select(Product).where(Product.seller_id == business_id,
        Product.id == product_id).with_for_update())
    if product is None:
        raise HTTPException(404, "Product not found")
    mapping = await db.scalar(select(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id == business_id,
        CatalogueProductMapping.product_id == product_id).with_for_update())
    if mapping is None:
        conflict("Backfill and review this product first")
    skus = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == business_id,
        CatalogueSKU.product_id == product_id).order_by(CatalogueSKU.id).with_for_update())).all()
    return product, mapping, skus


def validate_sku_set(skus):
    keys = [json.dumps({k.casefold(): v.casefold() for k, v in s.options.items()}, sort_keys=True) for s in skus]
    if len(set(keys)) != len(keys):
        conflict("SKU option combinations must be unique")
    dimensions = [{k.casefold() for k in s.options} for s in skus]
    if any(d != dimensions[0] for d in dimensions):
        conflict("Every SKU must use the same option dimensions")
    if any(s.currency != "INR" for s in skus):
        conflict("This catalogue supports INR only")


async def create_reviewed_product(db, business_id, payload):
    await lock_store(db, business_id)
    digest = request_hash(payload)
    command = await db.get(CatalogueCreation, (business_id, payload.idempotency_key))
    if command:
        if not hmac.compare_digest(command.request_hash, digest):
            conflict("This catalogue key was used for different facts")
        return command.product_id, True
    validate_sku_set(payload.skus)
    if any(s.sku_id is not None or s.legacy_variant_index is not None for s in payload.skus):
        conflict("New product SKU identities are assigned by the server")
    tracked = [s.stock_available is not None for s in payload.skus]
    if any(tracked) and not all(tracked):
        conflict("A new product must use consistently tracked or untracked stock")
    stock = sum(s.stock_available for s in payload.skus) if all(tracked) else None
    if stock is not None and stock > 2_000_000_000:
        conflict("Aggregate stock exceeds the supported maximum")
    if payload.category_id and not await db.scalar(select(ProductCategory.id).where(
            ProductCategory.id == payload.category_id, ProductCategory.seller_id == business_id)):
        raise HTTPException(404, "Category not found")
    if any(not safe_url(url) for url in payload.photo_urls):
        raise HTTPException(422, "Use approved HTTPS or upload image URLs")
    variants = None if len(payload.skus) == 1 and not payload.skus[0].options else [
        {"label": " / ".join(s.options.values()), "photo_urls": []} for s in payload.skus]
    product = Product(id=uuid4(), seller_id=business_id, name=payload.name,
        description=payload.description, category_id=payload.category_id, floor_price=0,
        listed_price=min(s.price_minor for s in payload.skus), stock_quantity=stock, active=False,
        variants=variants, photo_url=payload.photo_urls[0] if payload.photo_urls else None,
        photo_urls=payload.photo_urls[1:])
    db.add(product)
    await db.flush()
    db.add(CatalogueProductMapping(business_id=business_id, product_id=product.id, state="reviewed",
        revision=1, legacy_fingerprint=legacy_fingerprint(product, "INR"), issues=[],
        legacy_variants=[{"index": i, "value": v} for i, v in enumerate(variants or [])]))
    for index, s in enumerate(payload.skus):
        db.add(CatalogueSKU(id=uuid4(), business_id=business_id, product_id=product.id,
            **s.model_dump(exclude={"sku_id", "legacy_variant_index"}),
            legacy_variant_index=index if variants else None))
    db.add(CatalogueCreation(business_id=business_id, idempotency_key=payload.idempotency_key,
        request_hash=digest, product_id=product.id))
    await db.flush()
    return product.id, False


async def activate_product(db, business_id, product_id, actor_id, payload):
    store = await lock_store(db, business_id)
    product, mapping, skus = await rows_for_product(db, business_id, product_id)
    if await is_product_activated(db, business_id, product_id):
        return
    if mapping.state != "reviewed" or mapping.revision != payload.expected_mapping_revision:
        conflict("Seller review and current catalogue revision are required")
    fingerprint = legacy_fingerprint(product, store.currency)
    if mapping.legacy_fingerprint != fingerprint or payload.expected_legacy_fingerprint != fingerprint:
        conflict("Legacy inventory changed; reconcile and review again")
    if not skus or not any(s.active for s in skus):
        conflict("An active reviewed SKU is required")
    from app.schemas.catalogue_v1 import CatalogueReviewWrite, SKUWrite
    review = CatalogueReviewWrite(expected_mapping_revision=mapping.revision,
        expected_legacy_fingerprint=fingerprint, seller_reviewed=True,
        skus=[SKUWrite(sku_id=s.id, options=s.options, price_minor=s.price_minor, currency=s.currency,
            stock_available=s.stock_available, active=s.active, legacy_variant_index=s.legacy_variant_index) for s in skus])
    validate_sku_set(review.skus)
    try:
        validate_review(product, business_id, store.currency, review)
    except CatalogueConflict as exc:
        conflict(str(exc))
    # Reversible legacy decrements must finish on their original writer before
    # activation. Paid/shipped immutable sales are not subtracted a second time.
    pending = await db.scalar(select(CommerceOrder.id).where(
        CommerceOrder.seller_id == business_id, CommerceOrder.stock_released.is_(False),
        CommerceOrder.items.contains([{"product_id": str(product_id), "_stock_reserved": True}]),
        or_(CommerceOrder.fulfillment_status.in_(("pending", "confirmed", "packed")),
            CommerceOrder.payment_status.in_(("pending", "review_required")))).limit(1))
    if pending is not None:
        conflict("Resolve reversible or uncertain legacy orders before SKU activation")
    # Approved creates are private inactive drafts until this explicit operation.
    # This is product activation, not store publication or payment enablement.
    product.active = True
    mapping.legacy_fingerprint = legacy_fingerprint(product, store.currency)
    db.add(CatalogueActivation(business_id=business_id, product_id=product_id,
        reviewed_revision=mapping.revision, legacy_fingerprint=mapping.legacy_fingerprint, actor_id=actor_id))
    await db.flush()


async def update_operational_skus(db, business_id, product_id, payload):
    await lock_store(db, business_id)
    _, mapping, skus = await rows_for_product(db, business_id, product_id)
    if not await is_product_activated(db, business_id, product_id):
        conflict("Use legacy allocation review before activation")
    if mapping.revision != payload.expected_mapping_revision:
        conflict("Inventory changed; refresh before applying edits")
    validate_sku_set(payload.skus)
    by_id = {s.id: s for s in skus}
    if {s.sku_id for s in payload.skus} != set(by_id) or len(payload.skus) != len(skus):
        conflict("Include every existing SKU exactly once")
    for write in payload.skus:
        existing = by_id[write.sku_id]
        if write.options != existing.options or write.legacy_variant_index != existing.legacy_variant_index:
            conflict("SKU option identities cannot be changed")
    # Explicit available-stock edits run under the same locks and revision used by
    # checkout/release; an old page cannot overwrite an intervening reservation.
    for write in payload.skus:
        existing = by_id[write.sku_id]
        for name in ("price_minor", "currency", "stock_available", "active"):
            setattr(existing, name, getattr(write, name))
    mapping.revision += 1
    await db.flush()


async def update_product_metadata(db, business_id, product_id, payload):
    store = await lock_store(db, business_id)
    product, mapping, _ = await rows_for_product(db, business_id, product_id)
    if mapping.revision != payload.expected_mapping_revision:
        conflict("Catalogue changed; refresh before applying edits")
    active = await is_product_activated(db, business_id, product_id)
    if payload.active is True and not active:
        conflict("Use explicit reconciled activation before listing this product")
    if payload.category_id and not await db.scalar(select(ProductCategory.id).where(
            ProductCategory.id == payload.category_id, ProductCategory.seller_id == business_id)):
        raise HTTPException(404, "Category not found")
    if any(not safe_url(url) for url in payload.photo_urls):
        raise HTTPException(422, "Use approved HTTPS or upload image URLs")
    product.name, product.description, product.category_id = payload.name, payload.description, payload.category_id
    product.photo_url = payload.photo_urls[0] if payload.photo_urls else None
    product.photo_urls = payload.photo_urls[1:]
    if payload.active is not None:
        product.active = payload.active
    mapping.revision += 1
    mapping.legacy_fingerprint = legacy_fingerprint(product, store.currency)
    await db.flush()


def public_product(product, skus, enabled):
    images = [product.photo_url] + (product.photo_urls if isinstance(product.photo_urls, list) else [])
    return ProductRead(business_id=product.seller_id, product_id=product.id, name=product.name,
        description=product.description or "", category_id=product.category_id,
        photo_urls=list(dict.fromkeys(u for raw in images if (u := safe_url(raw)))),
        checkout_enabled=bool(enabled and product.active and any(s.active for s in skus)),
        skus=[SKURead(sku_id=s.id, product_id=s.product_id,
            options=s.options, price_minor=s.price_minor, currency=s.currency,
            stock_available=s.stock_available, active=s.active) for s in skus if s.active])


async def create_sku_order(db, store, payload):
    """Caller holds Storefront lock. No side effects outside PostgreSQL."""
    digest = request_hash(payload)
    existing = await db.scalar(select(CommerceOrder).where(CommerceOrder.seller_id == store.seller_id,
        CommerceOrder.idempotency_key == payload.idempotency_key))
    if existing:
        if not hmac.compare_digest(existing.request_hash, digest) or any(
                i.get("_inventory_engine") != ENGINE for i in existing.items):
            conflict("This checkout key was used for different order details")
        return existing, True
    policy = await db.get(CatalogueStorePolicy, store.seller_id)
    if policy is None or not policy.checkout_enabled:
        conflict("SKU checkout is not enabled for this storefront")
    if payload.payment_method == "cod" and not store.cod_enabled:
        conflict("Cash on delivery is unavailable")
    if payload.payment_method == "razorpay":
        from app.services.checkout_sessions import require_public_gateway
        await require_public_gateway(db, store.seller_id)
    ids = [item.sku_id for item in payload.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Combine duplicate SKU quantities")
    candidates = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == store.seller_id,
        CatalogueSKU.id.in_(ids)))).all()
    if len(candidates) != len(ids):
        raise HTTPException(404, "SKU unavailable")
    pids = {s.product_id for s in candidates}
    products = (await db.scalars(select(Product).where(Product.seller_id == store.seller_id,
        Product.id.in_(pids), Product.active.is_(True)).order_by(Product.id).with_for_update())).all()
    if len(products) != len(pids):
        raise HTTPException(404, "Product unavailable")
    activations = (await db.scalars(select(CatalogueActivation).where(
        CatalogueActivation.business_id == store.seller_id, CatalogueActivation.product_id.in_(pids)))).all()
    if len(activations) != len(pids):
        conflict("A product has not completed SKU activation")
    mappings = (await db.scalars(select(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id == store.seller_id,
        CatalogueProductMapping.product_id.in_(pids)).order_by(CatalogueProductMapping.product_id).with_for_update())).all()
    locked = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == store.seller_id,
        CatalogueSKU.id.in_(ids)).order_by(CatalogueSKU.id).with_for_update()
        .execution_options(populate_existing=True))).all()
    by_sku, by_product = {s.id: s for s in locked}, {p.id: p for p in products}
    snapshots, per_product = [], {}
    for item in payload.items:
        sku = by_sku[item.sku_id]
        product = by_product[sku.product_id]
        if not sku.active or sku.currency != store.currency:
            conflict("SKU unavailable")
        per_product[sku.product_id] = per_product.get(sku.product_id, 0) + item.quantity
        if per_product[sku.product_id] > 20:
            raise HTTPException(422, "Maximum 20 units per product")
        if sku.stock_available is not None and sku.stock_available < item.quantity:
            raise HTTPException(409, {"code": "sku_out_of_stock", "message": "Selected quantity is no longer available."})
        snapshots.append({"product_id": str(product.id), "sku_id": str(sku.id),
            "name": product.name, "options": deepcopy(sku.options), "currency": sku.currency,
            "quantity": item.quantity, "unit_price": sku.price_minor,
            "line_total": sku.price_minor * item.quantity, "photo_url": safe_url(product.photo_url),
            "_inventory_engine": ENGINE, "_stock_reserved": sku.stock_available is not None})
    subtotal = sum(s["line_total"] for s in snapshots)
    total = subtotal + store.shipping_fee
    if total > 2_000_000_000 or (payload.payment_method == "razorpay" and total < 100):
        raise HTTPException(422, "Order total is outside supported payment bounds")
    customer = await db.scalar(select(CommerceCustomer).where(CommerceCustomer.seller_id == store.seller_id,
        CommerceCustomer.phone == payload.customer.phone))
    if customer is None:
        customer = CommerceCustomer(id=uuid4(), seller_id=store.seller_id, **payload.customer.model_dump())
        db.add(customer)
        await db.flush()
    order = CommerceOrder(id=uuid4(), seller_id=store.seller_id, customer_id=customer.id,
        idempotency_key=payload.idempotency_key, request_hash=digest, customer=payload.customer.model_dump(),
        address=payload.address.model_dump(), items=snapshots, note=payload.note,
        subtotal=subtotal, shipping_fee=store.shipping_fee, total=total, currency=store.currency,
        payment_method=payload.payment_method, whatsapp_updates_opt_in=payload.whatsapp_updates_opt_in,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=20) if payload.payment_method == "razorpay" else None)
    db.add(order)
    await db.flush()
    for item in payload.items:
        sku = by_sku[item.sku_id]
        tracked = sku.stock_available is not None
        if tracked:
            sku.stock_available -= item.quantity
        db.add(SKUReservation(business_id=store.seller_id, order_id=order.id, product_id=sku.product_id,
            sku_id=sku.id, quantity=item.quantity, tracked=tracked))
    for mapping in mappings:
        mapping.revision += 1
    await db.flush()
    return order, False


async def release_sku_stock(db, order):
    """Caller locks order; stock_released is the shared once-only release guard."""
    if order.stock_released:
        return
    rows = (await db.scalars(select(SKUReservation).where(SKUReservation.business_id == order.seller_id,
        SKUReservation.order_id == order.id).order_by(SKUReservation.sku_id))).all()
    expected = {UUID(i["sku_id"]): i for i in order.items}
    if len(rows) != len(expected) or {r.sku_id for r in rows} != set(expected):
        conflict("SKU reservation ledger requires reconciliation")
    pids = {r.product_id for r in rows}
    await db.scalars(select(Product).where(Product.seller_id == order.seller_id,
        Product.id.in_(pids)).order_by(Product.id).with_for_update())
    mappings = (await db.scalars(select(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id == order.seller_id,
        CatalogueProductMapping.product_id.in_(pids)).order_by(CatalogueProductMapping.product_id).with_for_update())).all()
    skus = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == order.seller_id,
        CatalogueSKU.id.in_(expected)).order_by(CatalogueSKU.id).with_for_update())).all()
    by_id = {s.id: s for s in skus}
    rows = (await db.scalars(select(SKUReservation).where(SKUReservation.business_id == order.seller_id,
        SKUReservation.order_id == order.id).order_by(SKUReservation.sku_id).with_for_update())).all()
    for row in rows:
        snapshot = expected[row.sku_id]
        if row.quantity != snapshot["quantity"] or row.tracked != snapshot["_stock_reserved"] or row.released:
            conflict("SKU reservation ledger requires reconciliation")
        sku = by_id[row.sku_id]
        if row.tracked and sku.stock_available is not None:
            if sku.stock_available + row.quantity > 2_000_000_000:
                conflict("Inventory release exceeds supported bounds")
            sku.stock_available += row.quantity
        row.released, row.released_at = True, datetime.now(timezone.utc)
    for mapping in mappings:
        mapping.revision += 1
    order.stock_released = True
    await db.flush()
