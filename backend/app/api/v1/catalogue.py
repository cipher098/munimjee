"""Authorized catalogue management and published operational SKU storefront API."""
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation, business_mutation
from app.api.routes import commerce as legacy, razorpay as gateway
from app.database import get_db
from app.config import settings
from app.models.identity import Business
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.models.product import Product
from app.schemas.catalogue_v1 import CatalogueReviewWrite
from app.schemas.checkout_v1 import ActivationWrite, CheckoutWrite, OperationalSKUWrite, ProductCreate, StorePolicyWrite, ProductRead, PaymentReconcileWrite, ProductMetadataWrite
from app.services import catalogue_v1 as drafts, checkout_v1 as sku
from app.services.commerce import StoreInput, TransitionInput, expire_pending_orders, order_json
from app.services.identity import Actor, require_business_access

router = APIRouter(prefix="/api/v1", tags=["v1-catalogue-checkout"])


async def catalogue_result(operation):
    try:
        return await operation
    except drafts.CatalogueConflict as exc:
        raise HTTPException(409, str(exc))
    except drafts.CatalogueNotFound:
        raise HTTPException(404, "Product not found")


async def seller_product(db, business_id, product_id):
    store = await sku.lock_store(db, business_id)
    product, mapping, skus = await sku.rows_for_product(db, business_id, product_id)
    active = await sku.is_product_activated(db, business_id, product_id)
    policy = await db.get(CatalogueStorePolicy, business_id)
    if active:
        data = sku.public_product(product, skus, bool(policy and policy.checkout_enabled)).model_dump(mode="json")
    else:
        data = drafts.serialize_preview(product, business_id, store.currency, mapping, skus)[0].model_dump(mode="json")
    return {"product": data, "inventory_mode": "sku" if active else "legacy",
        "mapping_revision": mapping.revision, "legacy_fingerprint": drafts.legacy_fingerprint(product, store.currency),
        "issues": list(mapping.issues), "skus": [dict(sku_id=str(s.id), options=s.options,
            price_minor=s.price_minor, currency=s.currency, stock_available=s.stock_available,
            active=s.active, legacy_variant_index=s.legacy_variant_index) for s in skus]}


def settings_view(data):
    if data is None:
        return None
    url = None
    if settings.V1_STOREFRONT_ENABLED and data["published"]:
        from app.v1.storefront.rendering import canonical_origin
        url = canonical_origin(settings.PUBLIC_BASE_URL) + "/stores/" + data["slug"]
    return {**data, "public_storefront_url": url}


@router.get("/businesses/{business_id}/catalogue/storefront")
async def read_settings(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.read")
    return settings_view(await legacy.read_store(str(business_id), db))


@router.put("/businesses/{business_id}/catalogue/storefront")
async def save_settings(business_id: UUID, payload: StoreInput,
        actor: Actor = Depends(business_mutation("business.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "business.write")
    return settings_view(await legacy.save_store(payload, str(business_id), db))


@router.get("/businesses/{business_id}/catalogue/checkout-policy")
async def read_policy(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.read")
    policy = await db.get(CatalogueStorePolicy, business_id)
    return {"checkout_enabled": bool(policy and policy.checkout_enabled)}


@router.put("/businesses/{business_id}/catalogue/checkout-policy")
async def save_policy(business_id: UUID, payload: StorePolicyWrite,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await sku.lock_store(db, business_id)
    policy = await db.get(CatalogueStorePolicy, business_id)
    if policy is None:
        policy = CatalogueStorePolicy(business_id=business_id)
        db.add(policy)
    policy.checkout_enabled = payload.checkout_enabled
    await db.flush()
    return payload


@router.get("/businesses/{business_id}/catalogue/products")
async def products(business_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.read")
    await sku.lock_store(db, business_id)
    total = await db.scalar(select(func.count()).select_from(Product).where(Product.seller_id == business_id))
    ids = (await db.scalars(select(Product.id).where(Product.seller_id == business_id).order_by(Product.id)
        .offset((page - 1) * page_size).limit(page_size))).all()
    items = []
    for pid in ids:
        # Reading a legacy row never backfills or approves it implicitly.
        try:
            items.append(await seller_product(db, business_id, pid))
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            items.append({"product_id": str(pid), "inventory_mode": "legacy", "readiness": "needs_backfill"})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/businesses/{business_id}/catalogue/products", status_code=201)
async def create_product(business_id: UUID, payload: ProductCreate, response: Response,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    pid, replay = await sku.create_reviewed_product(db, business_id, payload)
    response.status_code = 200 if replay else 201
    return await seller_product(db, business_id, pid)


@router.get("/businesses/{business_id}/catalogue/products/{product_id}")
async def product_detail(business_id: UUID, product_id: UUID,
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.read")
    return await seller_product(db, business_id, product_id)


@router.post("/businesses/{business_id}/catalogue/products/{product_id}/backfill")
async def backfill(business_id: UUID, product_id: UUID,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await catalogue_result(drafts.backfill_product(db, business_id, product_id))
    return await seller_product(db, business_id, product_id)


@router.put("/businesses/{business_id}/catalogue/products/{product_id}/review")
async def review(business_id: UUID, product_id: UUID, payload: CatalogueReviewWrite,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await catalogue_result(drafts.apply_review(db, business_id, product_id, payload))
    return await seller_product(db, business_id, product_id)


@router.post("/businesses/{business_id}/catalogue/products/{product_id}/activate")
async def activate(business_id: UUID, product_id: UUID, payload: ActivationWrite,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await sku.activate_product(db, business_id, product_id, actor.user_id, payload)
    return await seller_product(db, business_id, product_id)


@router.put("/businesses/{business_id}/catalogue/products/{product_id}/skus")
async def edit_skus(business_id: UUID, product_id: UUID, payload: OperationalSKUWrite,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await sku.update_operational_skus(db, business_id, product_id, payload)
    return await seller_product(db, business_id, product_id)


@router.patch("/businesses/{business_id}/catalogue/products/{product_id}")
async def edit_product(business_id: UUID, product_id: UUID, payload: ProductMetadataWrite,
        actor: Actor = Depends(business_mutation("catalogue.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    await sku.update_product_metadata(db, business_id, product_id, payload)
    return await seller_product(db, business_id, product_id)


async def published_store(db, slug, lock=False, published=True):
    store = await legacy.get_public_store(db, slug, lock=lock, published=published)
    if not await db.scalar(select(Business.id).where(Business.id == store.seller_id, Business.is_active.is_(True))):
        raise HTTPException(404, "Store not found")
    return store


@router.get("/storefronts/{slug}")
async def storefront(slug: str, db: AsyncSession = Depends(get_db)):
    await published_store(db, slug)
    data = await legacy.public_store(slug, db)
    from app.services.checkout_sessions import public_payment_options
    data["payment_options"] = await public_payment_options(slug, db)
    policy = await db.get(CatalogueStorePolicy, (await legacy.get_public_store(db, slug)).seller_id)
    data["checkout_enabled"] = bool(policy and policy.checkout_enabled)
    data["contract_version"] = "storefront.v1"
    return data


@router.get("/storefronts/{slug}/products")
async def public_products(slug: str, q: str = Query("", max_length=200), category_id: UUID | None = None,
        page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    store = await published_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    policy = await db.get(CatalogueStorePolicy, store.seller_id)
    where = [Product.seller_id == store.seller_id, Product.active.is_(True)]
    if q.strip():
        where.append(or_(Product.name.ilike("%" + q.strip() + "%"), Product.description.ilike("%" + q.strip() + "%")))
    if category_id:
        where.append(Product.category_id == category_id)
    statement = select(Product).join(CatalogueActivation,
        (CatalogueActivation.product_id == Product.id) & (CatalogueActivation.business_id == Product.seller_id)).where(*where)
    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = (await db.scalars(statement.order_by(Product.created_at.desc(), Product.id)
        .offset((page - 1) * page_size).limit(page_size))).all()
    skus = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == store.seller_id,
        CatalogueSKU.product_id.in_([p.id for p in rows])).order_by(CatalogueSKU.id))).all() if rows else []
    return {"items": [sku.public_product(p, [s for s in skus if s.product_id == p.id],
        bool(policy and policy.checkout_enabled)) for p in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/storefronts/{slug}/products/{product_id}", response_model=ProductRead)
async def public_product(slug: str, product_id: UUID, db: AsyncSession = Depends(get_db)):
    store = await published_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    if not await sku.is_product_activated(db, store.seller_id, product_id):
        raise HTTPException(404, "Product not found")
    product, _, skus = await sku.rows_for_product(db, store.seller_id, product_id)
    if not product.active:
        raise HTTPException(404, "Product not found")
    policy = await db.get(CatalogueStorePolicy, store.seller_id)
    return sku.public_product(product, skus, bool(policy and policy.checkout_enabled))


@router.post("/storefronts/{slug}/checkout", status_code=201)
async def checkout(slug: str, payload: CheckoutWrite, response: Response, db: AsyncSession = Depends(get_db)):
    store = await published_store(db, slug, lock=True)
    await expire_pending_orders(db, store.seller_id)
    order, replay = await sku.create_sku_order(db, store, payload)
    if not replay and order.whatsapp_updates_opt_in:
        from app.services.whatsapp import record_checkout_opt_in, queue_order_update
        await record_checkout_opt_in(db, order.seller_id, order.customer["phone"], True)
        await queue_order_update(db, order, "placed")
    response.status_code = 200 if replay else 201
    response.headers["Cache-Control"] = "no-store"
    return {"contract_version": "order.v1", **order_json(order, include_token=True)}


@router.get("/storefronts/{slug}/orders/{order_id}")
async def order_status(slug: str, order_id: UUID, response: Response,
        authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    return await legacy.public_order(slug, order_id, response, authorization, db)


@router.post("/storefronts/{slug}/orders/{order_id}/razorpay")
async def payment_start(slug: str, order_id: UUID, authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    return await gateway.start_payment(slug, order_id, authorization, db)


@router.post("/storefronts/{slug}/orders/{order_id}/razorpay/verify")
async def payment_verify(slug: str, order_id: UUID, body: gateway.VerifyInput,
        authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    return await gateway.verify_payment(slug, order_id, body, authorization, db)


@router.get("/businesses/{business_id}/orders")
async def orders(business_id: UUID, status: str | None = None, page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100), actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.read")
    return await legacy.orders(status, page, page_size, str(business_id), db)


@router.post("/businesses/{business_id}/orders/{order_id}/transition")
async def transition(business_id: UUID, order_id: UUID, payload: TransitionInput,
        actor: Actor = Depends(business_mutation("orders.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.write")
    return await legacy.transition(order_id, payload, str(business_id), db)


@router.post("/businesses/{business_id}/orders/{order_id}/reconcile-gateway-order")
async def reconcile_payment_order(business_id: UUID, order_id: UUID, payload: PaymentReconcileWrite,
        actor: Actor = Depends(business_mutation("orders.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.write")
    order = await legacy.seller_order(db, business_id, order_id, lock=True)
    if not order.items or any(i.get("_inventory_engine") != sku.ENGINE for i in order.items):
        raise HTTPException(409, "This operation requires a SKU order")
    from app.services.sku_payments import reconcile_gateway_order
    return await reconcile_gateway_order(db, order, payload.gateway_order_id)


@router.post("/businesses/{business_id}/orders/{order_id}/reconcile-payment")
async def reconcile_payment(business_id: UUID, order_id: UUID,
        actor: Actor = Depends(business_mutation("orders.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.write")
    return await gateway.reconcile_order(order_id, str(business_id), db, commit=False)


@router.get("/businesses/{business_id}/orders/{order_id}")
async def order_detail(business_id: UUID, order_id: UUID,
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.read")
    data = await legacy.order_detail(order_id, str(business_id), db)
    return {**data, "parcel_url": f"/v1/businesses/{business_id}/orders/{order_id}/parcel"
            if settings.V1_PARCEL_ENABLED else None}


@router.post("/businesses/{business_id}/orders/{order_id}/collect-cod")
async def collect_cod(business_id: UUID, order_id: UUID,
        actor: Actor = Depends(business_mutation("orders.write")), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "orders.write")
    return await legacy.collect_cod(order_id, str(business_id), db)
