"""Pure contract/planning tests: no database connection or provider invocation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
import json

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.schemas.catalogue_v1 import (
    CatalogueMappingRead, CatalogueProductRead, CatalogueReviewWrite, PUBLIC_PRODUCT_FIELDS,
    PUBLIC_SKU_FIELDS, REVIEW_WRITE_FIELDS, SKU_WRITE_FIELDS, SKUWrite,
)
from app.services.catalogue_v1 import (
    CatalogueConflict, CatalogueNotFound, apply_review, backfill_product,
    legacy_fingerprint, plan_legacy_backfill, serialize_preview, validate_review,
)


BUSINESS = UUID("11111111-1111-4111-8111-111111111111")
PRODUCT = UUID("22222222-2222-4222-8222-222222222222")


def product(**values):
    base = dict(id=PRODUCT, seller_id=BUSINESS, category_id=None, name="Cotton kurta",
        description="Seller approved cotton kurta", listed_price=129900, floor_price=50000,
        stock_quantity=7, active=True, variants=None, photo_url="https://example.com/kurta.jpg",
        photo_urls=[], pending_reserved_units=3, credentials="private", seller_notes="private")
    base.update(values)
    return SimpleNamespace(**base)


def write(**values):
    base = dict(options={}, price_minor=129900, currency="INR", stock_available=7, active=True)
    base.update(values)
    return SKUWrite(**base)


def review(p, skus):
    return CatalogueReviewWrite(expected_legacy_fingerprint=legacy_fingerprint(p, "INR"), expected_mapping_revision=1,
                                seller_reviewed=True, skus=skus)


def mapping(p, **values):
    base = dict(business_id=BUSINESS, product_id=p.id, state="default_backfilled", revision=1,
        legacy_fingerprint=legacy_fingerprint(p, "INR"), issues=[], legacy_variants=[])
    base.update(values)
    return SimpleNamespace(**base)


def sku(p, **values):
    base = dict(id=uuid4(), business_id=BUSINESS, product_id=p.id, **write().model_dump(exclude={"sku_id"}))
    base.update(values)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("field,value", [
    ("price_minor", True), ("price_minor", -1), ("price_minor", 2_000_000_001),
    ("price_minor", "129900"), ("stock_available", False), ("stock_available", -1),
    ("stock_available", 2_000_000_001), ("stock_available", 1.5),
    ("currency", "USD"), ("currency", "inr"), ("active", "true"),
    ("legacy_variant_index", True), ("legacy_variant_index", -1),
    ("options", {" ": "red"}), ("options", {"Size": " "}),
    ("options", {"Size": "S", " size ": "M"}),
])
def test_strict_sku_facts(field, value):
    with pytest.raises(ValidationError):
        write(**{field: value})


def test_frozen_allowlists_and_extra_field_rejection():
    assert PUBLIC_PRODUCT_FIELDS == {"contract_version", "mode", "business_id", "product_id", "name",
        "description", "category_id", "photo_urls", "readiness", "checkout_enabled", "skus"}
    assert PUBLIC_SKU_FIELDS == {"sku_id", "product_id", "options", "price_minor", "currency", "stock_available", "active"}
    assert REVIEW_WRITE_FIELDS == {"expected_legacy_fingerprint", "expected_mapping_revision", "seller_reviewed", "skus"}
    assert SKU_WRITE_FIELDS == {"sku_id", "legacy_variant_index", "options", "price_minor", "currency", "stock_available", "active"}
    for forbidden in ("floor_price", "business_id", "seller_id", "credentials", "source_evidence"):
        with pytest.raises(ValidationError):
            write(**{forbidden: "private"})
    for value in (False, 1, "true"):
        with pytest.raises(ValidationError):
            CatalogueReviewWrite(expected_legacy_fingerprint="0" * 64, expected_mapping_revision=1, seller_reviewed=value, skus=[write()])


@pytest.mark.parametrize("available", [None, 0, 7])
def test_default_backfill_copies_available_without_subtracting_pending_reservations(available):
    p = product(stock_quantity=available, pending_reserved_units=3)
    before = deepcopy(p.__dict__)
    plan = plan_legacy_backfill(p, BUSINESS)
    assert plan.state == "default_backfilled"
    assert plan.default_sku.stock_available == available
    assert p.__dict__ == before


@pytest.mark.parametrize("variants", [[{"label": "Red"}, {"label": "Red"}], [{"label": "S"}], {}, "Red", [None]])
def test_variants_never_duplicate_aggregate_stock(variants):
    plan = plan_legacy_backfill(product(variants=variants), BUSINESS)
    assert plan.state == "needs_review"
    assert plan.default_sku is None
    assert "legacy_variants_require_seller_allocation" in plan.issues


@pytest.mark.parametrize("values", [{"listed_price": -1}, {"stock_quantity": -1}, {"active": None}, {"listed_price": True}])
def test_invalid_legacy_facts_block_default(values):
    plan = plan_legacy_backfill(product(**values), BUSINESS)
    assert plan.state == "needs_review" and plan.default_sku is None


def variant_review(p, stocks=(2, 5)):
    return review(p, [write(options={"Size": size}, stock_available=stock, legacy_variant_index=index)
        for index, (size, stock) in enumerate(zip(("S", "M"), stocks))])


def test_explicit_index_mapping_handles_duplicate_legacy_labels_without_guessing():
    p = product(variants=[{"label": "Red"}, {"label": "Red"}])
    validate_review(p, BUSINESS, "INR", variant_review(p))


@pytest.mark.parametrize("stocks", [(7, 7), (1, 1), (None, 7)])
def test_seller_allocates_available_once(stocks):
    p = product(variants=[{"label": "S"}, {"label": "M"}])
    with pytest.raises(CatalogueConflict, match="Allocate"):
        validate_review(p, BUSINESS, "INR", variant_review(p, stocks))


def test_untracked_stock_requires_all_untracked():
    p = product(stock_quantity=None, variants=[{"label": "S"}, {"label": "M"}])
    validate_review(p, BUSINESS, "INR", variant_review(p, (None, None)))
    with pytest.raises(CatalogueConflict, match="Untracked"):
        validate_review(p, BUSINESS, "INR", variant_review(p, (None, 0)))


def test_ambiguous_or_missing_options_and_indexes_block_review():
    p = product(variants=[{"label": "S"}, {"label": "M"}])
    payload = variant_review(p)
    payload.skus[1].legacy_variant_index = 0
    with pytest.raises(CatalogueConflict, match="exactly once"):
        validate_review(p, BUSINESS, "INR", payload)
    payload = variant_review(p)
    payload.skus[1].options = payload.skus[0].options
    with pytest.raises(CatalogueConflict, match="unique option"):
        validate_review(p, BUSINESS, "INR", payload)
    payload = variant_review(p)
    payload.skus[0].options = {}
    with pytest.raises(CatalogueConflict, match="explicit options"):
        validate_review(p, BUSINESS, "INR", payload)


def test_stale_review_cannot_overwrite_legacy_changes():
    p = product()
    payload = review(p, [write()])
    p.stock_quantity -= 1
    with pytest.raises(CatalogueConflict, match="changed"):
        validate_review(p, BUSINESS, "INR", payload)


def test_all_planning_and_public_read_functions_reject_cross_tenant_objects():
    p = product(seller_id=uuid4())
    with pytest.raises(CatalogueNotFound):
        plan_legacy_backfill(p, BUSINESS)
    with pytest.raises(CatalogueNotFound):
        validate_review(p, BUSINESS, "INR", review(p, [write()]))
    p = product()
    with pytest.raises(CatalogueNotFound):
        serialize_preview(p, BUSINESS, "INR", mapping(p, business_id=uuid4()), [])
    with pytest.raises(CatalogueNotFound):
        serialize_preview(p, BUSINESS, "INR", mapping(p), [sku(p, business_id=uuid4())])
    with pytest.raises(CatalogueNotFound):
        serialize_preview(p, BUSINESS, "INR", mapping(p), [sku(p, product_id=uuid4())])


def test_public_allowlist_sanitizes_media_and_marks_changed_stock_stale():
    p = product(photo_urls=["javascript:alert(1)", "https://user:password@example.com/private.jpg",
        "/uploads/../secret", "https://example.com/kurta.jpg", "/uploads/extra.jpg"])
    m = mapping(p)
    public, private = serialize_preview(p, BUSINESS, "INR", m, [sku(p)])
    data = public.model_dump(mode="json")
    assert set(data) == PUBLIC_PRODUCT_FIELDS
    assert set(data["skus"][0]) == PUBLIC_SKU_FIELDS
    assert public.photo_urls == ["https://example.com/kurta.jpg", "/uploads/extra.jpg"]
    assert not public.checkout_enabled
    assert "private" not in json.dumps(data)
    p.stock_quantity = 6
    public, private = serialize_preview(p, BUSINESS, "INR", m, [sku(p)])
    assert public.readiness == "stale" and not public.checkout_enabled
    assert "legacy_snapshot_changed" in private.issues


class FakeDB:
    """SQL-shape and mutation assertions only; not a replacement for DB tests."""
    def __init__(self, scalar_results, sku_results=()):
        self.scalar_results = iter(scalar_results)
        self.sku_results = list(sku_results)
        self.added, self.queries = [], []
        self.flushes = 0

    def check_query(self, query):
        compiled = query.compile(dialect=postgresql.dialect())
        assert BUSINESS in compiled.params.values(), "Every query must bind authorized tenant"
        self.queries.append(str(compiled))

    async def scalar(self, query):
        self.check_query(query)
        return next(self.scalar_results)

    async def scalars(self, query):
        self.check_query(query)
        return SimpleNamespace(all=lambda: self.sku_results)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_backfill_idempotence_preserves_existing_mapping_and_stock():
    p = product()
    m = mapping(p, state="reviewed")
    db = FakeDB([None, p, m])
    result, created = await backfill_product(db, BUSINESS, p.id)
    assert result is m and created is False
    assert not db.added and db.flushes == 0 and p.stock_quantity == 7
    assert "FOR UPDATE" in db.queries[1]


@pytest.mark.asyncio
async def test_default_backfill_writes_only_additive_rows():
    p = product()
    db = FakeDB([None, p, None])
    result, created = await backfill_product(db, BUSINESS, p.id)
    assert created and result.state == "default_backfilled"
    assert [type(value) for value in db.added] == [CatalogueProductMapping, CatalogueSKU]
    assert db.added[1].stock_available == 7 and p.stock_quantity == 7
    assert db.added[1].options == {} and db.flushes == 1
    db2 = FakeDB([None, product(), None])
    await backfill_product(db2, BUSINESS, p.id)
    assert db2.added[1].id == db.added[1].id


@pytest.mark.asyncio
async def test_existing_or_ambiguous_skus_never_receive_automatic_stock():
    p = product(variants=[{"label": "Red"}, {"label": "Blue"}])
    db = FakeDB([None, p, None])
    result, _ = await backfill_product(db, BUSINESS, p.id)
    assert result.state == "needs_review"
    assert len(db.added) == 1 and isinstance(db.added[0], CatalogueProductMapping)
    p = product()
    db = FakeDB([None, p, None], [sku(p)])
    result, _ = await backfill_product(db, BUSINESS, p.id)
    assert result.state == "needs_review"
    assert "existing_skus_require_reconciliation" in result.issues
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_missing_tenant_product_returns_not_found_before_mutation():
    db = FakeDB([None, None])
    with pytest.raises(CatalogueNotFound):
        await backfill_product(db, BUSINESS, uuid4())
    assert not db.added


@pytest.mark.asyncio
async def test_review_does_not_accept_foreign_or_unknown_sku_id():
    p = product()
    payload = review(p, [write(sku_id=uuid4())])
    db = FakeDB([None, p, mapping(p)], [sku(p)])
    with pytest.raises(CatalogueConflict, match="unknown SKU"):
        await apply_review(db, BUSINESS, p.id, payload)
    assert not db.added and db.flushes == 0


@pytest.mark.asyncio
async def test_seller_review_creates_variant_snapshot_without_legacy_mutation():
    p = product(variants=[{"label": "Red"}, {"label": "Red"}])
    before = deepcopy(p.__dict__)
    m = mapping(p, state="needs_review")
    db = FakeDB([None, p, m])
    result = await apply_review(db, BUSINESS, p.id, variant_review(p))
    assert result.state == "reviewed" and result.issues == []
    assert len(db.added) == 2 and sum(value.stock_available for value in db.added) == 7
    assert p.__dict__ == before


def test_concrete_contract_fixtures_round_trip():
    root = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "catalogue"
    assert len(list(root.glob("*-read.json"))) >= 3
    assert len(list(root.glob("*-write.json"))) >= 1
    for path in root.glob("*-read.json"):
        data = json.loads(path.read_text())
        assert CatalogueProductRead.model_validate(data).model_dump(mode="json") == data
    for path in root.glob("*-write.json"):
        data = json.loads(path.read_text())
        assert CatalogueReviewWrite.model_validate(data).model_dump(mode="json") == data
    for path in root.glob("*-mapping.json"):
        data = json.loads(path.read_text())
        assert CatalogueMappingRead.model_validate(data).model_dump(mode="json") == data
    for filename, model in (("product-read.schema.json", CatalogueProductRead),
                            ("review-write.schema.json", CatalogueReviewWrite),
                            ("mapping.schema.json", CatalogueMappingRead)):
        assert json.loads((root / filename).read_text()) == model.model_json_schema()
