"""Opt-in PostgreSQL checks against Alembic, never ORM create_all/drop_all.

Uses P01 migrated_engine and its validated disposable lane/reset lease.
No hardcoded worker URL or application DATABASE_URL fallback is permitted.
"""
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.catalogue_v1 import CatalogueSKU
from app.models.commerce import CommerceCustomer, CommerceOrder, Storefront
from app.models.product import Product
from app.models.seller import Seller
from app.schemas.catalogue_v1 import CatalogueReviewWrite, SKUWrite
from app.services.catalogue_v1 import (
    CatalogueConflict, CatalogueNotFound, apply_review, backfill_product, load_preview,
)


@pytest_asyncio.fixture
async def sessions(migrated_engine):
    """Portable P01 lane: actual Alembic head under the shared reset lease."""
    yield async_sessionmaker(migrated_engine, expire_on_commit=False)


async def seed(sessions, variants=None, stock=7, pending=False):
    from app.models.identity import Business
    business, product_id = uuid4(), uuid4()
    async with sessions.begin() as db:
        db.add(Seller(id=business, email=f"{business}@example.invalid", password_hash="synthetic", business_name="Synthetic boutique"))
        await db.flush()
        db.add(Business(id=business, name="Synthetic boutique"))
        db.add(Storefront(seller_id=business, slug=f"test-{business.hex}", name="Synthetic boutique"))
        db.add(Product(id=product_id, seller_id=business, name="Kurta", listed_price=129900,
            floor_price=50000, stock_quantity=stock, variants=variants, active=True))
        await db.flush()
        if pending:
            customer_id = uuid4()
            db.add(CommerceCustomer(id=customer_id, seller_id=business, name="Synthetic buyer", phone=f"+91{business.int % 10**10:010d}"))
            await db.flush()
            db.add(CommerceOrder(id=uuid4(), seller_id=business, customer_id=customer_id,
                idempotency_key=uuid4(), request_hash="0" * 64, customer={"name": "Synthetic buyer"},
                address={}, items=[{"product_id": str(product_id), "quantity": 3, "_stock_reserved": True}],
                subtotal=389700, shipping_fee=0, total=389700, payment_method="razorpay", payment_status="pending"))
    return business, product_id


@pytest.mark.asyncio
async def test_real_migration_backfill_preserves_pending_reservations_and_replays(sessions):
    business, pid = await seed(sessions, pending=True)
    async with sessions.begin() as db:
        mapping, created = await backfill_product(db, business, pid)
        assert created and mapping.state == "default_backfilled"
    async with sessions.begin() as db:
        _, created = await backfill_product(db, business, pid)
        assert not created
        public, private = await load_preview(db, business, pid)
        assert public.skus[0].stock_available == 7 and not public.checkout_enabled
        assert private.mapping_revision == 1
        product = await db.get(Product, pid)
        assert product.stock_quantity == 7
        orders = (await db.scalars(select(CommerceOrder).where(CommerceOrder.seller_id == business))).all()
        assert len(orders) == 1 and orders[0].items[0]["quantity"] == 3
        assert not orders[0].stock_released and orders[0].payment_status == "pending"


@pytest.mark.asyncio
async def test_competing_real_backfills_create_one_default_sku(sessions):
    business, pid = await seed(sessions)
    async def run():
        async with sessions.begin() as db:
            _, created = await backfill_product(db, business, pid)
            return created
    results = await asyncio.wait_for(asyncio.gather(run(), run()), timeout=10)
    assert sorted(results) == [False, True]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CatalogueSKU).where(CatalogueSKU.product_id == pid)) == 1


@pytest.mark.asyncio
async def test_competing_seller_reviews_preserve_first_approved_edit(sessions):
    business, pid = await seed(sessions, variants=[{"label": "Red"}, {"label": "Red"}])
    async with sessions.begin() as db:
        await backfill_product(db, business, pid)
        public, private = await load_preview(db, business, pid)
        assert public.readiness == "needs_review" and public.skus == []
        payload = CatalogueReviewWrite(expected_legacy_fingerprint=private.legacy_fingerprint,
            expected_mapping_revision=private.mapping_revision, seller_reviewed=True,
            skus=[SKUWrite(options={"Size": "S"}, price_minor=129900, currency="INR", stock_available=2, active=True, legacy_variant_index=0),
                  SKUWrite(options={"Size": "M"}, price_minor=139900, currency="INR", stock_available=5, active=True, legacy_variant_index=1)])
    async def run(payload):
        try:
            async with sessions.begin() as db:
                await apply_review(db, business, pid, payload)
            return "applied"
        except CatalogueConflict:
            return "conflict"
    assert sorted(await asyncio.wait_for(asyncio.gather(run(payload), run(payload)), timeout=10)) == ["applied", "conflict"]
    async with sessions.begin() as db:
        public, private = await load_preview(db, business, pid)
        assert private.mapping_revision == 2 and public.readiness == "reviewed"
        assert len(public.skus) == 2 and sum(s.stock_available for s in public.skus) == 7
        assert not public.checkout_enabled
        def edited(delta):
            return CatalogueReviewWrite(expected_legacy_fingerprint=private.legacy_fingerprint,
                expected_mapping_revision=private.mapping_revision, seller_reviewed=True,
                skus=[SKUWrite(sku_id=s.sku_id, options=s.options, price_minor=s.price_minor + delta,
                    currency=s.currency, stock_available=s.stock_available, active=s.active,
                    legacy_variant_index=0 if s.options["Size"] == "S" else 1) for s in public.skus])
        first, second = edited(100), edited(200)
    # Both edits contain all existing IDs; only mapping revision prevents stale overwrite.
    assert sorted(await asyncio.wait_for(asyncio.gather(run(first), run(second)), timeout=10)) == ["applied", "conflict"]
    async with sessions.begin() as db:
        public, private = await load_preview(db, business, pid)
        assert private.mapping_revision == 3
        prices = {s.options["Size"]: s.price_minor for s in public.skus}
        assert prices in ({"S": 130000, "M": 140000}, {"S": 130100, "M": 140100})
        # A subsequent legacy reservation changes fingerprint and cannot be hidden.
        p = await db.get(Product, pid)
        p.stock_quantity = 6
        await db.flush()
        public, _ = await load_preview(db, business, pid)
        assert public.readiness == "stale"


@pytest.mark.asyncio
async def test_actual_fk_and_service_both_reject_cross_tenant_product(sessions):
    owner, pid = await seed(sessions)
    other, _ = await seed(sessions)
    async with sessions.begin() as db:
        with pytest.raises(CatalogueNotFound):
            await backfill_product(db, other, pid)
    # Direct insert bypassing Python must still fail the composite tenant FK.
    async with sessions() as db:
        db.add(CatalogueSKU(id=uuid4(), business_id=other, product_id=pid, options={},
            price_minor=129900, currency="INR", stock_available=7, active=True))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CatalogueSKU).where(CatalogueSKU.product_id == pid)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("column,value", [("price_minor", -1), ("stock_available", -1), ("currency", "USD")])
async def test_actual_database_constraints_reject_invalid_facts(sessions, column, value):
    business, pid = await seed(sessions)
    values = dict(id=uuid4(), business_id=business, product_id=pid, options={},
        price_minor=129900, currency="INR", stock_available=7, active=True)
    values[column] = value
    async with sessions() as db:
        db.add(CatalogueSKU(**values))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
