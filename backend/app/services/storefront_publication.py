"""Canonical published-SKU projection; no draft or legacy inventory fallback."""
from fastapi import Depends, HTTPException
from sqlalchemy import exists, select

from app.database import get_db
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.seller import Seller
from app.services.checkout_v1 import public_product
from app.v1.storefront.rendering import PublicStorefront


class PublishedStorefrontProvider:
    def __init__(self, db, *, theme="catalogue"):
        # Presentation is application configuration, never an untrusted query or
        # a claim that seller theme settings have been persisted.
        if theme not in {"catalogue", "editorial", "video"}:
            raise ValueError("Unsupported storefront presentation")
        self.db, self.theme = db, theme

    async def public_store(self, slug):
        db = self.db
        store = await db.scalar(select(Storefront).join(Seller, Seller.id == Storefront.seller_id).join(
            Business, Business.id == Storefront.seller_id).where(
            Storefront.slug == slug, Storefront.published.is_(True), Seller.is_active.is_(True),
            Business.is_active.is_(True)).with_for_update(read=True, of=Storefront))
        if store is None:
            raise HTTPException(404, "Storefront unavailable")
        # Do not silently omit a published PDP because it fell off a first page.
        # Fail closed at a documented bounded capacity until paged SSR is added.
        rows = list((await db.scalars(select(Product).join(CatalogueActivation,
            (CatalogueActivation.business_id == Product.seller_id) & (CatalogueActivation.product_id == Product.id)
        ).where(Product.seller_id == store.seller_id, Product.active.is_(True), exists(select(CatalogueSKU.id).where(
            CatalogueSKU.business_id == store.seller_id, CatalogueSKU.product_id == Product.id,
            CatalogueSKU.active.is_(True)))).order_by(Product.id).limit(1001))).all())
        if len(rows) > 1000:
            raise HTTPException(503, "This catalogue needs paged publication")
        skus = list((await db.scalars(select(CatalogueSKU).where(CatalogueSKU.business_id == store.seller_id,
            CatalogueSKU.product_id.in_([row.id for row in rows]), CatalogueSKU.active.is_(True))
            .order_by(CatalogueSKU.id))).all()) if rows else []
        policy = await db.get(CatalogueStorePolicy, store.seller_id)
        categories = list((await db.scalars(select(ProductCategory).where(ProductCategory.seller_id == store.seller_id,
            ProductCategory.id.in_([row.category_id for row in rows if row.category_id])).order_by(ProductCategory.name))).all()) if rows else []
        category_ids = {category.id for category in categories}
        products = []
        for row in rows:
            dto = public_product(row, [sku for sku in skus if sku.product_id == row.id], bool(policy and policy.checkout_enabled)).model_dump(mode="json")
            if row.category_id not in category_ids:
                dto["category_id"] = None
            products.append(dto)
        from app.services.checkout_sessions import public_payment_options
        options = await public_payment_options(slug, db)
        methods = tuple(method for method, enabled in (("cod", options["cod_enabled"]),
            ("razorpay", options["razorpay_enabled"])) if enabled)
        return PublicStorefront(slug=store.slug, name=store.name, theme=self.theme,
            description=store.description, shipping_policy=store.shipping_policy, return_policy=store.return_policy,
            currency=store.currency, products=tuple(products),
            categories=tuple({"category_id":str(category.id),"name":category.name} for category in categories),
            publication_verified=True, checkout_enabled=bool(policy and policy.checkout_enabled and methods), payment_methods=methods)


async def published_storefront_provider(db=Depends(get_db)):
    return PublishedStorefrontProvider(db)
