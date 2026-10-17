"""Actual migrated PostgreSQL SKU writer/cutover tests under P01's reset lease."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.catalogue_v1 import CatalogueSKU, CatalogueProductMapping
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy, SKUReservation
from app.models.commerce import CommerceCustomer, CommerceOrder, Storefront
from app.models.product import Product
from app.models.seller import Seller
from app.schemas.checkout_v1 import ActivationWrite, CheckoutWrite, OperationalSKUWrite, ProductCreate
from app.schemas.catalogue_v1 import SKUWrite, CatalogueReviewWrite
from app.services import checkout_v1 as svc
from app.services.catalogue_v1 import apply_review, CatalogueConflict, legacy_fingerprint
from app.services.commerce import create_order, CheckoutInput, release_stock, expire_pending_orders
from app.services.identity import ensure_legacy_owner_bridge, legacy_owner_id


@pytest_asyncio.fixture
async def sessions(migrated_engine):
    yield async_sessionmaker(migrated_engine, expire_on_commit=False)


async def seed(sessions, stock=2, activate=True, enabled=True, variants=False):
    business = uuid4()
    async with sessions.begin() as db:
        seller = Seller(id=business, email=f"{business}@example.invalid", password_hash="synthetic", business_name="Test boutique")
        db.add(seller)
        await db.flush()
        await ensure_legacy_owner_bridge(db, seller)
        store = Storefront(seller_id=business, slug="test-" + business.hex, name="Test boutique", published=True)
        db.add(store)
        await db.flush()
        skus = [SKUWrite(options={"Size": "S"} if variants else {}, price_minor=129900,
            currency="INR", stock_available=stock, active=True)]
        if variants:
            skus.append(SKUWrite(options={"Size": "M"}, price_minor=139900,
                currency="INR", stock_available=stock, active=True))
        payload = ProductCreate(idempotency_key=uuid4(), seller_reviewed=True, name="Kurta",
            description="Reviewed facts", skus=skus)
        pid, _ = await svc.create_reviewed_product(db, business, payload)
        mapping = await db.get(CatalogueProductMapping, (business, pid))
        if activate:
            await svc.activate_product(db, business, pid, legacy_owner_id(business), ActivationWrite(
                seller_reviewed=True, expected_mapping_revision=mapping.revision,
                expected_legacy_fingerprint=mapping.legacy_fingerprint))
        db.add(CatalogueStorePolicy(business_id=business, checkout_enabled=enabled))
        sku_ids = (await db.scalars(select(CatalogueSKU.id).where(CatalogueSKU.product_id == pid).order_by(CatalogueSKU.price_minor))).all()
    return business, pid, sku_ids


def checkout(sku_id, **changes):
    fields = dict(idempotency_key=uuid4(), customer={"name": "Synthetic Buyer", "phone": "+919876543210"},
        address={"line1": "12 Test Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001"},
        items=[{"sku_id": sku_id, "quantity": 1}], payment_method="cod")
    fields.update(changes)
    return CheckoutWrite(**fields)


async def place(sessions, business, payload):
    async with sessions.begin() as db:
        store = await svc.lock_store(db, business)
        order, replay = await svc.create_sku_order(db, store, payload)
        return order.id, replay


@pytest.mark.asyncio
async def test_actual_single_sku_contention_never_oversells(sessions):
    business, pid, ids = await seed(sessions, stock=1)
    async def attempt():
        try:
            await place(sessions, business, checkout(ids[0]))
            return "placed"
        except HTTPException as exc:
            assert exc.status_code == 409
            return "unavailable"
    assert sorted(await asyncio.wait_for(asyncio.gather(attempt(), attempt()), 10)) == ["placed", "unavailable"]
    async with sessions() as db:
        assert (await db.get(CatalogueSKU, ids[0])).stock_available == 0
        assert (await db.get(Product, pid)).stock_quantity == 1  # legacy snapshot never decremented
        assert await db.scalar(select(func.count()).select_from(SKUReservation)) == 1


@pytest.mark.asyncio
async def test_checkout_refreshes_cached_sku_after_concurrent_callback_release(sessions, monkeypatch):
    business, _, ids = await seed(sessions, stock=2)
    prior, _ = await place(sessions, business, checkout(ids[0]))
    async with sessions.begin() as db:
        store = await svc.lock_store(db, business)
        original = db.scalars
        injected = False
        async def with_release(statement, *args, **kwargs):
            nonlocal injected
            result = await original(statement, *args, **kwargs)
            if not injected and "FROM catalogue_skus" in str(statement) and statement._for_update_arg is None:
                injected = True
                cached = result.all()
                assert cached[0].stock_available == 1
                # Payment callbacks lock their order directly, without storefront
                # lock, and may restore stock before checkout locks this Product.
                async with sessions.begin() as callback:
                    order = await callback.scalar(select(CommerceOrder).where(CommerceOrder.id == prior).with_for_update())
                    await release_stock(callback, order)
                return SimpleNamespace(all=lambda: cached)
            return result
        monkeypatch.setattr(db, "scalars", with_release)
        payload = checkout(ids[0], items=[{"sku_id": ids[0], "quantity": 2}])
        await svc.create_sku_order(db, store, payload)
        assert injected and (await db.get(CatalogueSKU, ids[0])).stock_available == 0


@pytest.mark.asyncio
async def test_checkout_retry_hash_and_price_snapshots(sessions):
    business, pid, ids = await seed(sessions, variants=True)
    payload = checkout(ids[1])
    order_id, replay = await place(sessions, business, payload)
    assert not replay
    assert await place(sessions, business, payload) == (order_id, True)
    async with sessions.begin() as db:
        original = await db.get(CommerceOrder, order_id)
        snapshot = deepcopy(original.items)
        assert snapshot[0]["unit_price"] == 139900 and snapshot[0]["options"] == {"Size": "M"}
        assert original.total == 139900 and snapshot[0]["currency"] == "INR"
        mapping = await db.get(CatalogueProductMapping, (business, pid))
        skus = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.product_id == pid))).all()
        writes = [SKUWrite(sku_id=s.id, options=s.options, price_minor=s.price_minor + 100,
            currency=s.currency, stock_available=s.stock_available, active=s.active,
            legacy_variant_index=s.legacy_variant_index) for s in skus]
        await svc.update_operational_skus(db, business, pid, OperationalSKUWrite(
            seller_reviewed=True, expected_mapping_revision=mapping.revision, skus=writes))
        assert original.items == snapshot
    changed = payload.model_copy(update={"note": "changed"})
    with pytest.raises(HTTPException) as err:
        await place(sessions, business, changed)
    assert err.value.status_code == 409
    async with sessions() as db:
        assert (await db.get(CatalogueSKU, ids[1])).stock_available == 1


@pytest.mark.asyncio
async def test_cancellation_once_under_competing_releases(sessions):
    business, _, ids = await seed(sessions)
    oid, _ = await place(sessions, business, checkout(ids[0]))
    async def cancel():
        async with sessions.begin() as db:
            await svc.lock_store(db, business)
            order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == oid).with_for_update())
            await release_stock(db, order)
            order.fulfillment_status = "cancelled"
    await asyncio.wait_for(asyncio.gather(cancel(), cancel()), 10)
    async with sessions() as db:
        assert (await db.get(CatalogueSKU, ids[0])).stock_available == 2
        assert (await db.get(CommerceOrder, oid)).stock_released
        assert (await db.scalar(select(SKUReservation))).released


@pytest.mark.asyncio
async def test_expiry_then_late_capture_keeps_inventory_released(sessions, monkeypatch):
    from app.services import razorpay_payments as payments
    business, _, ids = await seed(sessions)
    async def gateway(*args, **kwargs):
        return None
    from app.services import checkout_sessions
    monkeypatch.setattr(checkout_sessions, "require_public_gateway", gateway)
    oid, _ = await place(sessions, business, checkout(ids[0], payment_method="razorpay"))
    async with sessions.begin() as db:
        order = await db.get(CommerceOrder, oid)
        order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        order.gateway_order_id = "order_synthetic"
    async with sessions.begin() as db:
        await svc.lock_store(db, business)
        await expire_pending_orders(db, business)
    async with sessions.begin() as db:
        order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == oid).with_for_update())
        await payments.apply_captured_payment(db, order, {"id": "pay_synthetic", "order_id": "order_synthetic",
            "amount": order.total, "currency": "INR", "status": "captured", "captured": True})
        assert order.payment_status == "review_required"
        assert (await db.get(CatalogueSKU, ids[0])).stock_available == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stock", [None, 0])
async def test_untracked_and_zero_have_distinct_checkout_semantics(sessions, stock):
    business, _, ids = await seed(sessions, stock=stock)
    if stock == 0:
        with pytest.raises(HTTPException):
            await place(sessions, business, checkout(ids[0]))
        return
    oid, _ = await place(sessions, business, checkout(ids[0]))
    async with sessions.begin() as db:
        await release_stock(db, await db.get(CommerceOrder, oid))
        assert (await db.get(CatalogueSKU, ids[0])).stock_available is None
        assert not (await db.scalar(select(SKUReservation))).tracked


@pytest.mark.asyncio
async def test_disabled_policy_never_falls_back_to_legacy_writer(sessions):
    business, pid, ids = await seed(sessions, enabled=False)
    with pytest.raises(HTTPException):
        await place(sessions, business, checkout(ids[0]))
    payload = CheckoutInput(**{**checkout(ids[0]).model_dump(exclude={"items"}), "items": [{"product_id": pid, "quantity": 1}]})
    async with sessions.begin() as db:
        store = await svc.lock_store(db, business)
        with pytest.raises(HTTPException) as exc:
            await create_order(db, store, payload)
        assert exc.value.status_code == 409
        assert (await db.get(Product, pid)).stock_quantity == 2


@pytest.mark.asyncio
async def test_trigger_rejects_old_writer_and_preview_review_cannot_reset_live_skus(sessions):
    business, pid, _ = await seed(sessions)
    async with sessions() as db:
        p = await db.get(Product, pid)
        p.stock_quantity = 100
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    async with sessions.begin() as db:
        mapping = await db.get(CatalogueProductMapping, (business, pid))
        with pytest.raises(CatalogueConflict, match="operational"):
            await apply_review(db, business, pid, CatalogueReviewWrite(seller_reviewed=True,
                expected_mapping_revision=mapping.revision, expected_legacy_fingerprint=mapping.legacy_fingerprint,
                skus=[SKUWrite(options={}, price_minor=1, currency="INR", stock_available=2, active=True)]))


@pytest.mark.asyncio
async def test_pending_legacy_reservation_blocks_activation_then_requires_fresh_review(sessions):
    business, pid, ids = await seed(sessions, stock=7, activate=False)
    async with sessions.begin() as db:
        customer = CommerceCustomer(id=uuid4(), seller_id=business, name="Buyer", phone="+919876543210")
        db.add(customer)
        await db.flush()
        legacy = CommerceOrder(id=uuid4(), seller_id=business, customer_id=customer.id,
            idempotency_key=uuid4(), request_hash="0" * 64, customer={}, address={},
            items=[{"product_id": str(pid), "quantity": 3, "_stock_reserved": True}], subtotal=3,
            shipping_fee=0, total=3, payment_method="cod")
        db.add(legacy)
        await db.flush()
        mapping = await db.get(CatalogueProductMapping, (business, pid))
        payload = ActivationWrite(seller_reviewed=True, expected_mapping_revision=mapping.revision,
            expected_legacy_fingerprint=mapping.legacy_fingerprint)
        with pytest.raises(HTTPException, match="legacy"):
            await svc.activate_product(db, business, pid, legacy_owner_id(business), payload)
        await release_stock(db, legacy)
        legacy.fulfillment_status = "cancelled"
        await db.flush()
        with pytest.raises(HTTPException):
            await svc.activate_product(db, business, pid, legacy_owner_id(business), payload)
        p = await db.get(Product, pid)
        assert p.stock_quantity == 10 and (await db.get(CatalogueSKU, ids[0])).stock_available == 7
        await apply_review(db, business, pid, CatalogueReviewWrite(seller_reviewed=True,
            expected_mapping_revision=mapping.revision, expected_legacy_fingerprint=legacy_fingerprint(p, "INR"),
            skus=[SKUWrite(sku_id=ids[0], options={}, price_minor=129900, currency="INR", stock_available=10, active=True)]))
        await svc.activate_product(db, business, pid, legacy_owner_id(business), ActivationWrite(
            seller_reviewed=True, expected_mapping_revision=mapping.revision,
            expected_legacy_fingerprint=mapping.legacy_fingerprint))
        assert (await db.get(CatalogueSKU, ids[0])).stock_available == 10


@pytest.mark.asyncio
async def test_cross_tenant_sku_selection_and_database_ledger_forgery_fail(sessions):
    first, pid, ids = await seed(sessions)
    other, _, _ = await seed(sessions)
    with pytest.raises(HTTPException) as exc:
        await place(sessions, other, checkout(ids[0]))
    assert exc.value.status_code == 404
    oid, _ = await place(sessions, first, checkout(ids[0]))
    async with sessions() as db:
        db.add(SKUReservation(business_id=other, order_id=oid, product_id=pid, sku_id=ids[0],
            quantity=1, tracked=True))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_stock_revision_prevents_stale_available_stock_overwrite(sessions):
    business, pid, ids = await seed(sessions)
    async with sessions() as db:
        mapping = await db.get(CatalogueProductMapping, (business, pid))
        revision = mapping.revision
    await place(sessions, business, checkout(ids[0]))
    async with sessions.begin() as db:
        with pytest.raises(HTTPException, match="changed"):
            await svc.update_operational_skus(db, business, pid, OperationalSKUWrite(seller_reviewed=True,
                expected_mapping_revision=revision, skus=[SKUWrite(sku_id=ids[0], options={}, price_minor=1,
                currency="INR", stock_available=100, active=True)]))
        assert (await db.get(CatalogueSKU, ids[0])).stock_available == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["price", "remove_marker", "remove_items", "null_items"])
async def test_actual_database_keeps_sku_order_line_snapshots_immutable(sessions, change):
    business, _, ids = await seed(sessions)
    oid, _ = await place(sessions, business, checkout(ids[0]))
    async with sessions() as db:
        order = await db.get(CommerceOrder, oid)
        original = deepcopy(order.items)
        changed = deepcopy(original)
        if change == "price":
            changed[0]["unit_price"] = 1
        elif change == "remove_marker":
            changed[0].pop("_inventory_engine")
        elif change == "remove_items":
            changed = []
        else:
            changed = None
        order.items = changed
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
        assert (await db.get(CommerceOrder, oid)).items == original
