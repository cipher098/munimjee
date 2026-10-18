"""Actual app.main + actual Alembic gates, only on an allocated P01 lane.

No create_all, alternate connection, reset bypass, domain or provider calls.
"""
import json
from types import SimpleNamespace
from uuid import uuid4
from xml.etree.ElementTree import fromstring

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import get_db
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.seller import Seller
from tests.test_storefront_publication import setup, checkout
from tests.test_v1_seo_publication import ORIGIN, SOURCE, NS, reviewed


def locs(response):
    assert response.status_code == 200, response.text
    return [node.text for node in fromstring(response.content).findall(".//s:loc", NS)]


@pytest_asyncio.fixture
async def mounted_seo(migrated_engine, monkeypatch):
    from app.main import app
    from app.api.v1.storefront_bootstrap import install_storefront
    # Existing native fixtures may install storefront dynamically. Preserve the
    # whole shared app state and replace only that install for this explicit run.
    original_routes = list(app.router.routes)
    original_startup = list(app.router.on_startup)
    original_overrides = dict(app.dependency_overrides)
    original_middleware = list(app.user_middleware)
    original_stack = app.middleware_stack
    seo_paths = {"/sitemap.xml", "/sitemap-store-{slug}.xml"}
    app.router.routes[:] = [route for route in original_routes if not (
        getattr(route, "path", "").startswith(("/stores/", "/storefront-assets/"))
        or getattr(route, "path", "") in seo_paths
        or "public-storefront-discovery" in getattr(route, "tags", []))]
    app.router.on_startup[:] = [handler for handler in original_startup
                                if handler.__name__ != "validate_installed_seo_routes"]
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", ORIGIN)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", "[]")
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async def database():
        async with sessions.begin() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN,
                               headers={"Origin": ORIGIN}, follow_redirects=False) as client:
            data = await setup(client)
            mapping = reviewed(store_slug=data["slug"], target_path=f"/stores/{data['slug']}/products/{data['pid']}")
            monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", json.dumps([mapping]))
            # Test-only fixture rebuild: native setup has already used this
            # process-global app. Production bootstrap installs before serving.
            app.middleware_stack = None
            install_storefront(app)
            await app.router.startup()  # Exercise final app.main collision guard.
            async with sessions() as db:
                version = await db.scalar(text("SHOW server_version_num"))
                assert 160000 <= int(version) < 170000, "SEO mounted gate requires actual PostgreSQL16"
            yield SimpleNamespace(app=app, client=client, sessions=sessions, data=data, mapping=mapping)
            await app.router.shutdown()
    finally:
        app.router.routes[:] = original_routes
        app.router.on_startup[:] = original_startup
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        app.user_middleware[:] = original_middleware
        app.middleware_stack = original_stack


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["unpublished", "inactive_seller", "inactive_business", "unactivated", "inactive_product", "inactive_sku"])
async def test_actual_main_current_publication_revocation_sitemap_redirect_and_order(mounted_seo, gate):
    j = mounted_seo; data = j.data
    sitemap = f"/sitemap-store-{data['slug']}.xml"
    canonical = ORIGIN + j.mapping["target_path"]
    assert locs(await j.client.get("/sitemap.xml")) == [ORIGIN+sitemap]
    assert canonical in locs(await j.client.get(sitemap))
    legacy = SOURCE+j.mapping["source_path"]
    response = await j.client.get(legacy)
    assert response.status_code == 308 and response.headers["location"] == canonical
    async with j.sessions.begin() as db:
        if gate == "unpublished": (await db.get(Storefront, data["bid"])).published = False
        elif gate == "inactive_seller": (await db.get(Seller, data["bid"])).is_active = False
        elif gate == "inactive_business": (await db.get(Business, data["bid"])).is_active = False
        elif gate == "unactivated":
            await db.execute(delete(CatalogueActivation).where(CatalogueActivation.business_id == data["bid"]))
        elif gate == "inactive_product": (await db.get(Product, data["pid"])).active = False
        elif gate == "inactive_sku": (await db.get(CatalogueSKU, data["sku"])).active = False
    if gate in {"unpublished", "inactive_seller", "inactive_business"}:
        assert locs(await j.client.get("/sitemap.xml")) == []
        assert (await j.client.get(sitemap)).status_code == 404
    else:
        assert canonical not in locs(await j.client.get(sitemap))
    gone = await j.client.get(legacy)
    assert gone.status_code == 404 and "location" not in gone.headers
    shell = await j.client.get(f"/stores/{data['slug']}/orders/{uuid4()}")
    assert shell.status_code == 200 and shell.headers["cache-control"] == "no-store"
    assert shell.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.asyncio
async def test_actual_main_category_tenant_scope_private_draft_and_existing_capability(mounted_seo):
    j = mounted_seo; data = j.data
    category_id, foreign_id = uuid4(), uuid4()
    # A second actual native account supplies separate tenant facts; draft
    # creation is the actual catalogue writer, never a guessed public product.
    async with AsyncClient(transport=ASGITransport(app=j.app), base_url=ORIGIN, headers={"Origin":ORIGIN}) as other:
        foreign = await setup(other, activate=False)
    async with j.sessions.begin() as db:
        db.add(ProductCategory(id=category_id, seller_id=data["bid"], name='Public & <category>'))
        db.add(ProductCategory(id=foreign_id, seller_id=foreign["bid"], name='PRIVATE_FOREIGN_CATEGORY'))
        await db.flush()
        (await db.get(Product, data["pid"])).category_id = category_id
        (await db.get(Product, foreign["pid"])).category_id = foreign_id
    page = await j.client.get(f"/sitemap-store-{data['slug']}.xml", headers={"Host":"injected.example.test"})
    urls = locs(page)
    assert ORIGIN+f"/stores/{data['slug']}/categories/{category_id}" in urls
    assert str(foreign_id) not in page.text and str(foreign["pid"]) not in page.text
    assert str(data["bid"]) not in page.text and "PRIVATE_FOREIGN_CATEGORY" not in page.text
    # A persisted cross-tenant category reference is stripped by the real
    # publication provider rather than entering the public sitemap.
    async with j.sessions.begin() as db:
        (await db.get(Product, data["pid"])).category_id = foreign_id
    after = await j.client.get(f"/sitemap-store-{data['slug']}.xml")
    assert str(foreign_id) not in after.text and "/categories/" not in after.text
    placed = await j.client.post(f"/api/v1/storefronts/{data['slug']}/checkout", json=checkout(data["sku"]))
    assert placed.status_code == 201, placed.text
    order = placed.json()
    async with j.sessions.begin() as db:
        (await db.get(Storefront, data["bid"])).published = False
    status = f"/api/v1/storefronts/{data['slug']}/orders/{order['id']}"
    assert (await j.client.get(status)).status_code == 404
    allowed = await j.client.get(status, headers={"Authorization":"Bearer "+order["access_token"]})
    assert allowed.status_code == 200, allowed.text
    shell = await j.client.get(f"/stores/{data['slug']}/orders/{order['id']}")
    assert shell.status_code == 200 and order["access_token"] not in shell.text
