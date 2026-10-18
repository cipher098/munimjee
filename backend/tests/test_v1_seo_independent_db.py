"""Actual migrated SEO acceptance, pending an explicitly allocated P01 DB lane.

Uses the baseline native signup/catalogue fixture only for setup. SEO assertions
and malicious inventories are independent of the SEO producer's test suite.
No sqlite/create_all, database allocation, Docker or provider fallback exists.
"""
import json
from uuid import uuid4

import pytest

from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.seller import Seller
from app.services.storefront_publication import published_storefront_provider
from tests.test_storefront_publication import public_api, setup, checkout  # noqa: F401
from tests.test_v1_seo_independent import ORIGIN, SOURCE, locations, mapping


def install(client, data):
    from app.v1.storefront.seo import create_seo_router, parse_legacy_redirects
    rows = [mapping(store_slug=data["slug"], target_path=f"/stores/{data['slug']}/products/{data['pid']}")]
    inventory = parse_legacy_redirects(json.dumps(rows), ORIGIN)
    client._transport.app.include_router(create_seo_router(canonical_base=ORIGIN,
        provider_dependency=published_storefront_provider,
        legacy_redirects=inventory))


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["unpublished", "inactive_seller", "inactive_business", "inactive_product", "inactive_sku", "unactivated"])
async def test_actual_db_discovery_tenant_scope_draft_exclusion_and_revocation(public_api, gate):
    client, factory = public_api
    first = await setup(client)
    # An approved product with no activation remains a private draft.
    draft = await client.post(first["prefix"] + "/products", headers=first["headers"], json={
        "idempotency_key": str(uuid4()), "seller_reviewed": True, "name": "PRIVATE-DRAFT-SENTINEL",
        "description": "Private draft", "photo_urls": [], "skus": [{"options": {"Size": "L"},
        "price_minor": 999, "currency": "INR", "stock_available": 3, "active": True}]})
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["product"]["product_id"]
    second = await setup(client)
    install(client, first)
    index_before = locations(await client.get("/sitemap.xml"), "sitemapindex")
    assert set(index_before) == {ORIGIN + f"/sitemap-store-{item['slug']}.xml" for item in (first, second)}
    sitemap_path = f"/sitemap-store-{first['slug']}.xml"
    result = await client.get(sitemap_path)
    urls = locations(result, "urlset")
    assert set(urls) == {ORIGIN + f"/stores/{first['slug']}", ORIGIN + f"/stores/{first['slug']}/products/{first['pid']}"}
    assert str(second["pid"]) not in result.text and draft_id not in result.text
    assert "PRIVATE-DRAFT-SENTINEL" not in result.text
    assert (await client.get(SOURCE + "/old-dress", follow_redirects=False)).status_code == 308
    async with factory.begin() as db:
        if gate == "unpublished": (await db.get(Storefront, first["bid"])).published = False
        elif gate == "inactive_seller": (await db.get(Seller, first["bid"])).is_active = False
        elif gate == "inactive_business": (await db.get(Business, first["bid"])).is_active = False
        elif gate == "inactive_product": (await db.get(Product, first["pid"])).active = False
        elif gate == "inactive_sku": (await db.get(CatalogueSKU, first["sku"])).active = False
        else: await db.delete(await db.get(CatalogueActivation, (first["bid"], first["pid"])))
    assert (await client.get(SOURCE + "/old-dress", follow_redirects=False)).status_code == 404
    current = await client.get(sitemap_path)
    if gate in {"unpublished", "inactive_seller", "inactive_business"}:
        assert current.status_code == 404
        assert ORIGIN + sitemap_path not in locations(await client.get("/sitemap.xml"), "sitemapindex")
    else:
        assert locations(current, "urlset") == [ORIGIN + f"/stores/{first['slug']}"]
    # Foreign publication survives the other tenant's revocation.
    assert ORIGIN + f"/stores/{second['slug']}/products/{second['pid']}" in locations(
        await client.get(f"/sitemap-store-{second['slug']}.xml"), "urlset")


@pytest.mark.asyncio
async def test_actual_db_existing_order_capability_survives_unpublish(public_api):
    client, factory = public_api
    data = await setup(client)
    install(client, data)
    placed = await client.post(f"/api/v1/storefronts/{data['slug']}/checkout", json=checkout(data["sku"]))
    assert placed.status_code == 201, placed.text
    order = placed.json()
    async with factory.begin() as db:
        (await db.get(Storefront, data["bid"])).published = False
    assert (await client.get(f"/sitemap-store-{data['slug']}.xml")).status_code == 404
    path = f"/api/v1/storefronts/{data['slug']}/orders/{order['id']}"
    assert (await client.get(path)).status_code == 404
    assert (await client.get(path, headers={"Authorization": "Bearer " + order["access_token"]})).status_code == 200
    shell = await client.get(f"/stores/{data['slug']}/orders/{order['id']}")
    assert shell.status_code == 200 and order["access_token"] not in shell.text
    assert shell.headers["x-robots-tag"] == "noindex, nofollow"
