"""Side-effect-free planning and additive, tenant-bound catalogue snapshots.

No checkout, reservation, Product, CommerceOrder or provider writes occur here.
Caller owns transaction commit/rollback and verifies seller review authority.
"""
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select

from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.commerce import Storefront
from app.models.product import Product
from app.schemas.catalogue_v1 import CatalogueMappingRead, CatalogueProductRead, CatalogueReviewWrite, SKURead, SKUWrite


class CatalogueConflict(ValueError):
    """Review cannot be applied safely; surface as a conflict, never auto-fix."""


class CatalogueNotFound(LookupError):
    """Same response for absent and other-tenant products/SKUs."""


def assert_tenant(product, business_id: UUID):
    if product.seller_id != business_id:
        raise CatalogueNotFound("Product unavailable")


def legacy_fingerprint(product, currency: str) -> str:
    values = {key: getattr(product, key) for key in (
        "listed_price", "stock_quantity", "active", "variants", "name", "description",
        "photo_url", "photo_urls",
    )}
    values.update(product_id=str(product.id), business_id=str(product.seller_id), currency=currency,
                  category_id=str(product.category_id) if product.category_id else None)
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def legacy_variant_evidence(product) -> list[dict]:
    raw = product.variants
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        return [{"index": None, "value": raw}]
    return [{"index": index, "value": value} for index, value in enumerate(raw)]


@dataclass(frozen=True)
class BackfillPlan:
    state: str
    fingerprint: str
    issues: tuple[str, ...]
    legacy_variants: list[dict]
    default_sku: SKUWrite | None


def plan_legacy_backfill(product, business_id: UUID, currency: str = "INR") -> BackfillPlan:
    """Copy AVAILABLE stock exactly once; do not inspect/subtract reservations."""
    assert_tenant(product, business_id)
    issues = []
    variants = legacy_variant_evidence(product)
    if variants:
        issues.append("legacy_variants_require_seller_allocation")
    try:
        sku = SKUWrite(options={}, price_minor=product.listed_price, currency=currency,
                       stock_available=product.stock_quantity, active=product.active)
    except ValueError:
        sku = None
        issues.append("invalid_legacy_price_stock_currency_or_active")
    if variants:
        sku = None
    return BackfillPlan("needs_review" if issues else "default_backfilled",
                        legacy_fingerprint(product, currency), tuple(issues), variants, sku)


def validate_review(product, business_id: UUID, currency: str, payload: CatalogueReviewWrite):
    assert_tenant(product, business_id)
    if payload.expected_legacy_fingerprint != legacy_fingerprint(product, currency):
        raise CatalogueConflict("Legacy product changed; refresh and review again")
    if any(sku.currency != currency for sku in payload.skus):
        raise CatalogueConflict("SKU currency must equal the storefront currency")
    options = [json.dumps(sku.options, sort_keys=True, ensure_ascii=False) for sku in payload.skus]
    if len(options) != len(set(options)):
        raise CatalogueConflict("Each SKU must have a unique option combination")
    ids = [sku.sku_id for sku in payload.skus if sku.sku_id is not None]
    if len(ids) != len(set(ids)):
        raise CatalogueConflict("Duplicate SKU ID")
    raw = product.variants
    if raw is not None and not isinstance(raw, list):
        raise CatalogueConflict("Malformed legacy variants require correction before allocation")
    if raw:
        indexes = [sku.legacy_variant_index for sku in payload.skus]
        if any(index is None for index in indexes) or sorted(indexes) != list(range(len(raw))):
            raise CatalogueConflict("Map each legacy variant index exactly once")
        if any(not sku.options for sku in payload.skus):
            raise CatalogueConflict("Variant SKUs require explicit options")
    elif len(payload.skus) != 1 or payload.skus[0].options or payload.skus[0].legacy_variant_index is not None:
        raise CatalogueConflict("Nonvariant products require one default SKU")
    stock = product.stock_quantity
    if stock is None:
        if any(sku.stock_available is not None for sku in payload.skus):
            raise CatalogueConflict("Untracked legacy stock requires untracked SKU stock")
    elif type(stock) is not int or stock < 0 or stock > 2_000_000_000:
        raise CatalogueConflict("Invalid legacy available stock requires correction")
    elif any(sku.stock_available is None for sku in payload.skus) or sum(sku.stock_available for sku in payload.skus) != stock:
        raise CatalogueConflict("Allocate current available stock exactly once across SKUs")


async def _locked_product(db, business_id, product_id):
    product = await db.scalar(select(Product).where(
        Product.seller_id == business_id, Product.id == product_id).with_for_update())
    if product is None:
        raise CatalogueNotFound("Product unavailable")
    return product


async def _currency(db, business_id):
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == business_id).with_for_update())
    return store.currency if store else "INR"


async def _mapping(db, business_id, product_id):
    return await db.scalar(select(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id == business_id,
        CatalogueProductMapping.product_id == product_id).with_for_update())


async def backfill_product(db, business_id: UUID, product_id: UUID):
    """Idempotent by tenant/product lock; replay never overwrites a reviewed SKU.

    Business compatibility row must exist (0040). Runs explicitly after schema
    migration, not inside Alembic. Pending reservations already reduced Product
    stock; no reservation read or release belongs in this backfill.
    """
    # Match commerce lock order: storefront, then product.
    currency = await _currency(db, business_id)
    product = await _locked_product(db, business_id, product_id)
    existing = await _mapping(db, business_id, product_id)
    if existing is not None:
        return existing, False
    plan = plan_legacy_backfill(product, business_id, currency)
    skus = (await db.scalars(select(CatalogueSKU).where(
        CatalogueSKU.business_id == business_id, CatalogueSKU.product_id == product_id))).all()
    # An interrupted/manual reconciliation must never fabricate a second default.
    issues = list(plan.issues)
    if skus:
        issues.append("existing_skus_require_reconciliation")
    mapping = CatalogueProductMapping(business_id=business_id, product_id=product_id,
        state="needs_review" if skus else plan.state, legacy_fingerprint=plan.fingerprint,
        issues=issues, legacy_variants=plan.legacy_variants)
    db.add(mapping)
    if not skus and plan.default_sku is not None:
        db.add(CatalogueSKU(id=uuid5(product_id, f"catalogue.v1:{business_id}:default"),
            business_id=business_id, product_id=product_id,
            **plan.default_sku.model_dump(exclude={"sku_id"})))
    await db.flush()
    return mapping, True


async def apply_review(db, business_id: UUID, product_id: UUID, payload: CatalogueReviewWrite):
    """Apply a complete approved snapshot. No hidden deletion or legacy mutation."""
    currency = await _currency(db, business_id)
    product = await _locked_product(db, business_id, product_id)
    validate_review(product, business_id, currency, payload)
    mapping = await _mapping(db, business_id, product_id)
    if mapping is None:
        raise CatalogueConflict("Backfill the product mapping before seller review")
    if mapping.revision != payload.expected_mapping_revision:
        raise CatalogueConflict("Catalogue review changed; refresh before applying edits")
    existing = (await db.scalars(select(CatalogueSKU).where(
        CatalogueSKU.business_id == business_id, CatalogueSKU.product_id == product_id).with_for_update())).all()
    by_id = {sku.id: sku for sku in existing}
    supplied = {sku.sku_id for sku in payload.skus if sku.sku_id is not None}
    # Keep IDs stable and reject foreign/missing IDs without querying another tenant.
    if supplied != set(by_id):
        raise CatalogueConflict("Review must include existing SKU IDs; unknown SKU unavailable")
    for write in payload.skus:
        sku = by_id.get(write.sku_id)
        if sku is not None and sku.options != write.options:
            raise CatalogueConflict("Existing SKU options are immutable; reconcile changed variants separately")
    for write in payload.skus:
        values = write.model_dump(exclude={"sku_id"})
        sku = by_id.get(write.sku_id)
        if sku is None:
            db.add(CatalogueSKU(id=uuid4(), business_id=business_id, product_id=product_id, **values))
        else:
            for key, value in values.items():
                setattr(sku, key, value)
    mapping.state = "reviewed"
    mapping.revision += 1
    mapping.issues = []
    mapping.legacy_fingerprint = legacy_fingerprint(product, currency)
    mapping.legacy_variants = legacy_variant_evidence(product)
    await db.flush()
    return mapping


def _media_url(value):
    if not isinstance(value, str) or any(char in value for char in ("\\", "\r", "\n", "\x00")):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
        if value.startswith("/uploads/") and not parsed.netloc and ".." not in unquote(parsed.path):
            return value
    except ValueError:
        pass
    return None


def serialize_preview(product, business_id: UUID, currency: str, mapping, skus):
    """Public allowlist. Never dump ORM __dict__ or source/private extraction."""
    assert_tenant(product, business_id)
    if mapping.business_id != business_id or mapping.product_id != product.id:
        raise CatalogueNotFound("Product unavailable")
    if any(s.business_id != business_id or s.product_id != product.id for s in skus):
        raise CatalogueNotFound("SKU unavailable")
    readiness = mapping.state if mapping.legacy_fingerprint == legacy_fingerprint(product, currency) else "stale"
    images = [product.photo_url] + (product.photo_urls if isinstance(product.photo_urls, list) else [])
    images = list(dict.fromkeys(url for raw in images if (url := _media_url(raw))))
    public_skus = [SKURead(sku_id=s.id, product_id=s.product_id, options=s.options,
        price_minor=s.price_minor, currency=s.currency, stock_available=s.stock_available, active=s.active)
        for s in sorted(skus, key=lambda value: str(value.id))]
    public = CatalogueProductRead(business_id=business_id, product_id=product.id,
        name=product.name, description=product.description or "", category_id=product.category_id,
        photo_urls=images, readiness=readiness, skus=public_skus)
    private = CatalogueMappingRead(business_id=business_id, product_id=product.id,
        readiness=readiness, mapping_revision=mapping.revision,
        legacy_fingerprint=legacy_fingerprint(product, currency),
        issues=list(mapping.issues) + (["legacy_snapshot_changed"] if readiness == "stale" else []),
        legacy_variants=legacy_variant_evidence(product))
    return public, private


async def load_preview(db, business_id: UUID, product_id: UUID):
    """Authorized seller/preview read. Public publication routing is a later slice."""
    currency = await _currency(db, business_id)
    product = await _locked_product(db, business_id, product_id)
    mapping = await _mapping(db, business_id, product_id)
    if mapping is None:
        raise CatalogueConflict("Product has no catalogue snapshot yet")
    skus = (await db.scalars(select(CatalogueSKU).where(
        CatalogueSKU.business_id == business_id, CatalogueSKU.product_id == product_id))).all()
    return serialize_preview(product, business_id, currency, mapping, skus)
