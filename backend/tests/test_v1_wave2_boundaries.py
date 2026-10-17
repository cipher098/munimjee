"""Independent import→identity/catalogue boundaries using actual P01 migrations."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.commerce import CommerceOrder, Storefront
from app.models.identity import Membership, User
from app.models.product import Product
from app.models.seller import Seller
from app.services.catalogue_v1 import CatalogueNotFound, backfill_product, load_preview
from app.services.identity import ensure_legacy_owner_bridge, require_business_access, resolve_legacy_owner
from app.v1.imports import (
    FactField, ImportReviewError, ReviewDecision, SellerOverride, apply_overrides,
    approve, begin_review, confirm_facts, parse_candidate, reimport_candidate, reject,
)
from tests.conftest_db import db_session  # noqa: F401


@pytest.fixture
def imported_product():
    business, reviewer = uuid4(), uuid4()
    payload = {
        "provenance": {"business_id": str(business), "import_job_id": str(uuid4()),
            "captured_at": "2026-10-17T12:00:00Z",
            "source": {"kind": "website", "url": "https://boutique.example.com/dress"},
            "source_product_id": "dress-1", "evidence": "Synthetic literal source"},
        "facts": {"title": "Dress", "description": "Synthetic", "price": {"amount": "1299.00", "currency": "INR"}, "stock": 7, "options": []},
    }
    return SimpleNamespace(business=business, reviewer=reviewer, payload=payload)


def reviewed(sample):
    candidate = begin_review(parse_candidate(sample.payload, business_id=sample.business), business_id=sample.business)
    return confirm_facts(candidate, ReviewDecision(reviewer_id=sample.reviewer, confirmed_fields=tuple(FactField)), business_id=sample.business)


@pytest.mark.parametrize("operation", ["begin", "confirm", "approve", "override", "reject", "reimport"])
def test_every_review_transition_rejects_a_foreign_business(imported_product, operation):
    sample = imported_product
    pending = parse_candidate(sample.payload, business_id=sample.business)
    candidate = reviewed(sample)
    decision = ReviewDecision(reviewer_id=sample.reviewer, confirmed_fields=tuple(FactField), reason="Synthetic rejection")
    other = uuid4()
    actions = {
        "begin": lambda: begin_review(pending, business_id=other),
        "confirm": lambda: confirm_facts(candidate, decision, business_id=other),
        "approve": lambda: approve(candidate, business_id=other),
        "override": lambda: apply_overrides(candidate, (SellerOverride(field="stock", value=1, reviewer_id=sample.reviewer),), business_id=other),
        "reject": lambda: reject(candidate, decision, business_id=other),
        "reimport": lambda: reimport_candidate(candidate, pending, business_id=other),
    }
    with pytest.raises(ImportReviewError, match="does not belong"):
        actions[operation]()


def test_successive_reimports_preserve_override_and_require_fresh_review(imported_product):
    sample = imported_product
    candidate = apply_overrides(reviewed(sample), (
        SellerOverride(field="price", value={"amount": "1400", "currency": "INR"}, reviewer_id=sample.reviewer),
    ), business_id=sample.business)
    candidate = approve(confirm_facts(candidate, ReviewDecision(reviewer_id=sample.reviewer, confirmed_fields=tuple(FactField)), business_id=sample.business), business_id=sample.business)
    for hour, price in [(13, "1199"), (14, "1599")]:
        incoming = deepcopy(sample.payload)
        incoming["facts"]["price"]["amount"] = price
        incoming["provenance"]["captured_at"] = f"2026-10-17T{hour}:00:00Z"
        result = reimport_candidate(candidate, parse_candidate(incoming, business_id=sample.business), business_id=sample.business)
        candidate = result.candidate
        assert candidate.effective_facts().price.amount == Decimal("1400")
        assert candidate.review is None
        with pytest.raises(ImportReviewError):
            approve(candidate, business_id=sample.business)


@pytest_asyncio.fixture
async def wave2_tenants(db_session):
    """Reusable native-compatible synthetic tenants; never creates ORM tables."""
    records = []
    for index in range(2):
        seller = Seller(id=uuid4(), email=f"wave2-{index}@example.test", password_hash="synthetic", business_name=f"Wave2 {index}", is_active=True)
        db_session.add(seller)
        await db_session.flush()
        await ensure_legacy_owner_bridge(db_session, seller)
        store = Storefront(seller_id=seller.id, slug=f"wave2-{seller.id.hex}", name=seller.business_name, published=False)
        product = Product(id=uuid4(), seller_id=seller.id, name="Private draft dress", description="Synthetic", listed_price=129900,
            floor_price=51000, stock_quantity=7, variants=None, active=True)
        db_session.add_all([store, product])
        await db_session.flush()
        actor = await resolve_legacy_owner(db_session, seller.id)
        records.append(SimpleNamespace(seller=seller, store=store, product=product, actor=actor))
    await db_session.commit()
    return tuple(records)


@pytest.mark.asyncio
async def test_authorized_catalogue_read_then_revocation_is_rechecked(db_session, wave2_tenants):
    first, second = wave2_tenants
    await require_business_access(db_session, first.actor, first.seller.id, "catalogue.write")
    await backfill_product(db_session, first.seller.id, first.product.id)
    public, private = await load_preview(db_session, first.seller.id, first.product.id)
    assert "floor_price" not in public.model_dump()
    assert public.checkout_enabled is False and first.store.published is False
    with pytest.raises(HTTPException) as foreign:
        await require_business_access(db_session, first.actor, second.seller.id, "catalogue.read")
    assert foreign.value.status_code == 404
    with pytest.raises(CatalogueNotFound):
        await load_preview(db_session, first.seller.id, second.product.id)
    membership = (await db_session.execute(select(Membership).where(Membership.business_id == first.seller.id, Membership.user_id == first.actor.user_id))).scalar_one()
    membership.revoked_at = datetime.now(timezone.utc)
    await db_session.flush()
    for capability in ("catalogue.read", "catalogue.write"):
        with pytest.raises(HTTPException) as revoked:
            await require_business_access(db_session, first.actor, first.seller.id, capability)
        assert revoked.value.status_code == 404
    assert await db_session.scalar(select(func.count()).select_from(CommerceOrder)) == 0


@pytest.mark.asyncio
async def test_import_approval_alone_never_changes_publication_stock_or_orders(db_session, wave2_tenants, imported_product):
    first, _ = wave2_tenants
    sample = imported_product
    sample.business = first.seller.id
    sample.payload["provenance"]["business_id"] = str(first.seller.id)
    approved = approve(reviewed(sample), business_id=first.seller.id)
    assert approved.state.value == "approved"
    await db_session.refresh(first.product)
    await db_session.refresh(first.store)
    assert first.product.stock_quantity == 7 and first.product.listed_price == 129900
    assert first.store.published is False
    assert await db_session.scalar(select(func.count()).select_from(CommerceOrder)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["user_revoked", "user_inactive", "role_downgraded"])
async def test_current_actor_recheck_observes_authority_changed_in_another_transaction(db_session, wave2_tenants, migrated_engine, change):
    """Models a cached actor while another transaction revokes during a lock wait.

    The current host cannot run this DB gate; retaining the User instance is
    deliberate so an identity-map cache cannot stand in for current authority.
    """
    first, _ = wave2_tenants
    cached_user = await db_session.get(User, first.actor.user_id)
    cached_access = await require_business_access(db_session, first.actor, first.seller.id, "catalogue.write")
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessions.begin() as other:
        if change == "role_downgraded":
            await other.execute(update(Membership).where(Membership.id == cached_access.membership.id).values(role="viewer"))
        else:
            values = {"revoked_at": datetime.now(timezone.utc)} if change == "user_revoked" else {"is_active": False}
            await other.execute(update(User).where(User.id == first.actor.user_id).values(**values))
    assert cached_user.revoked_at is None
    with pytest.raises(HTTPException) as denied:
        await require_business_access(db_session, first.actor, first.seller.id, "catalogue.write")
    assert denied.value.status_code == (403 if change == "role_downgraded" else 401)
