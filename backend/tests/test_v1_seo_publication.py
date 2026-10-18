"""Synthetic pure/ASGI safety evidence, not actual-DB/domain migration proof."""
import json
from urllib.parse import urlsplit
from xml.etree.ElementTree import fromstring

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api.v1.storefront import create_router
from app.api.v1.storefront_bootstrap import install_storefront
from app.config import settings
from app.v1.storefront import seo
from tests.test_v1_storefront_rendering import snapshot, PRODUCT, CATEGORY

ORIGIN = "https://configured.example.test"
SOURCE = "https://legacy.example.test"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def reviewed(**changes):
    fields = dict(source_origin=SOURCE, source_path="/legacy/rose-dress",
                  target_path=f"/stores/tara/products/{PRODUCT}", store_slug="tara",
                  owner_reference="synthetic-owner-review-001", reviewed_by="synthetic-owner",
                  reviewed_at="2026-10-18")
    fields.update(changes)
    return fields


class Provider:
    def __init__(self):
        self.store = snapshot()
        self.slugs = ("tara",)

    async def public_store_slugs(self):
        return self.slugs

    async def public_store(self, slug):
        if slug != "tara" or self.store is None:
            raise HTTPException(404, "private-provider-error", headers={"secret": "never-publish"})
        return self.store


def app_for(provider, rows=()):
    app = FastAPI()
    async def dependency():
        return provider
    inventory = seo.parse_legacy_redirects(json.dumps(rows), ORIGIN)
    seo.install_seo_request_fence(app, canonical_base=ORIGIN, legacy_redirects=inventory)
    app.include_router(seo.create_seo_router(canonical_base=ORIGIN, provider_dependency=dependency,
                                             legacy_redirects=inventory))
    app.include_router(create_router(canonical_base=ORIGIN, provider_dependency=dependency))
    return app


def locations(response):
    return [node.text for node in fromstring(response.content).findall(".//s:loc", NS)]


@pytest.mark.parametrize("origin", [
    "", "//evil.test", "https://user:password@shop.test", "https://shop.test/path",
    "https://shop.test?secret=x", "https://shop.test#fragment", "https://shop.test?",
    "https://shop.test#", "https://shop.test\\evil", "https://shop.test\n",
    "https://shop.test\r\nLocation:bad", "https://shop.test\t", "https://shop.test\x00",
    "https://shop.test:0", "https://shop.test:65536", "https://shop.test:abc",
    "https://shop.test:", "https://shop.test:0443", "https://shop.test.",
    "https://Shop.test", "HTTPS://shop.test", "https://xn--shop.test", "https://shöp.test",
    "https://shop..test", "https://-shop.test", "https://shop_.test", "https://shop%2etest",
    "https://127.000.0.1", "https://127.0.0.999", "http://public.test", "http://127.1",
    "http://[0:0:0:0:0:0:0:1]", "https://[::1", "https://shop.test//",
])
def test_strict_origin_rejects_ambiguous_unsafe_authority(origin):
    with pytest.raises(ValueError, match="Invalid SEO origin"):
        seo.strict_origin(origin)


@pytest.mark.parametrize("origin", [ORIGIN, ORIGIN+"/", "https://shop.test:8443",
    "http://localhost:8159", "http://127.0.0.1:8159", "http://[::1]:8159"])
def test_strict_origin_accepts_reviewed_https_and_explicit_loopback(origin):
    assert seo.strict_origin(origin) == origin.rstrip("/")


def test_xml_contains_only_public_canonical_identities_ignores_host_headers_and_names():
    provider = Provider()
    with TestClient(app_for(provider)) as client:
        headers = {"Host": "attacker.test", "Forwarded": "host=evil.test;proto=http", "X-Forwarded-Host": "other.test"}
        index = client.get("/sitemap.xml", headers=headers)
        page = client.get("/sitemap-store-tara.xml", headers=headers)
        assert index.status_code == page.status_code == 200
        assert locations(index) == [ORIGIN+"/sitemap-store-tara.xml"]
        assert locations(page) == [ORIGIN+"/stores/tara", ORIGIN+f"/stores/tara/products/{PRODUCT}", ORIGIN+f"/stores/tara/categories/{CATEGORY}"]
        assert page.headers["content-type"].startswith("application/xml")
        assert page.headers["cache-control"] == "no-store"
        sitemap_directory = urlsplit(locations(index)[0]).path.rsplit("/", 1)[0] + "/"
        assert all(urlsplit(url).path.startswith(sitemap_directory) and len(url) < 2048 for url in locations(page))
        assert client.get("/stores/tara/sitemap.xml").status_code == 404
        for value in ("attacker", "evil", "secret", "Tara", "Rose", "floor_price", "source_evidence", "lastmod", "orders", "seller_id"):
            assert value not in page.text
        provider.slugs = ()
        provider.store = None
        assert locations(client.get("/sitemap.xml")) == []
        gone = client.get("/sitemap-store-tara.xml")
        assert gone.status_code == 404 and gone.headers["cache-control"] == "no-store"
        assert "private-provider-error" not in gone.text and "secret" not in gone.headers


@pytest.mark.parametrize("bad_store", [
    snapshot(publication_verified=False), snapshot(slug="foreign"), snapshot(slug="tara<script>"),
    snapshot(products=(snapshot().products[0],)*2), snapshot(categories=(snapshot().categories[0],)*2),
    snapshot(products=()), snapshot(name=""), snapshot(currency="USD"), snapshot(theme="unknown"),
    snapshot(products=({},)), snapshot(categories=({"name":"Incomplete"},)),
])
def test_sitemap_fails_closed_invalid_unpublished_or_foreign_projection(bad_store):
    provider = Provider(); provider.store = bad_store
    with TestClient(app_for(provider)) as client:
        response = client.get("/sitemap-store-tara.xml")
        assert response.status_code in {404, 503}
        assert response.headers["cache-control"] == "no-store"
        assert "https://" not in response.text


@pytest.mark.parametrize("product", [
    {"name":"Valid text", "description":"Missing identity"},
    {"name":"Valid text", "product_id":PRODUCT, "skus":[{"sku_id":PRODUCT}]},
])
def test_malformed_provider_keys_are_unavailable_503_not_unknown_page_404(product):
    provider = Provider(); provider.store = snapshot(products=(product,), categories=())
    with TestClient(app_for(provider)) as client:
        assert client.get("/sitemap-store-tara.xml").status_code == 503


@pytest.mark.parametrize("slugs", [("tara", "tara"), ("tara", "evil<script>"), ["tara"], tuple(f"store-{i}" for i in range(1001))])
def test_index_capacity_and_identity_fail_without_partial_xml(slugs):
    provider = Provider(); provider.slugs = slugs
    with TestClient(app_for(provider)) as client:
        response = client.get("/sitemap.xml")
        assert response.status_code == 503 and "<sitemapindex" not in response.text


@pytest.mark.parametrize("capacity", ["MAX_PRODUCTS", "MAX_CATEGORIES", "MAX_XML_BYTES", "MAX_URL_CHARS"])
def test_per_store_capacity_fails_without_truncation(monkeypatch, capacity):
    monkeypatch.setattr(seo, capacity, 0)
    with TestClient(app_for(Provider())) as client:
        response = client.get("/sitemap-store-tara.xml")
        assert response.status_code == 503 and "<urlset" not in response.text


@pytest.mark.parametrize("changes", [
    {"source_origin":"//evil.test"}, {"source_origin":SOURCE+"/"}, {"source_origin":SOURCE+"?token=secret"},
    {"source_path":"https://evil.test/path"}, {"source_path":"//evil.test/path"},
    {"source_path":"/old/%2fpath"}, {"source_path":"/old/%252e%252e/path"}, {"source_path":"/old/../path"},
    {"source_path":"/old/./path"}, {"source_path":"/old//path"}, {"source_path":"/old\\path"},
    {"source_path":"/old?token=x"}, {"source_path":"/old#fragment"}, {"source_path":"/old\r\nLocation:evil"},
    {"source_path":"/old/{slug}"}, {"source_path":"/old/*"}, {"source_path":"/"},
    {"target_path":"https://evil.test/path"}, {"target_path":"//evil.test/path"},
    {"target_path":"/stores/foreign"}, {"target_path":"/stores/tara/orders/"+PRODUCT},
    {"target_path":"/stores/tara/products/not-a-uuid"},
    {"target_path":"/stores/tara/products/"+PRODUCT+"?token=x"}, {"target_path":"/stores/tara/"},
    {"store_slug":"other"}, {"reviewed_by":""}, {"reviewed_by":"name\nheader"},
    {"owner_reference":" "}, {"reviewed_at":"2026-02-30"}, {"reviewed_at":"20261018"},
    {"unknown":"field"},
])
def test_reviewed_inventory_rejects_unsafe_unowned_unreviewed_mapping(changes):
    with pytest.raises(ValueError, match="Invalid reviewed redirect inventory"):
        seo.parse_legacy_redirects(json.dumps([reviewed(**changes)]), ORIGIN)


@pytest.mark.parametrize("prefix", sorted(seo._RESERVED))
def test_reviewed_source_never_shadows_protected_route_prefix(prefix):
    with pytest.raises(ValueError):
        seo.parse_legacy_redirects(json.dumps([reviewed(source_path=f"/{prefix}/legacy")]), ORIGIN)


def test_inventory_rejects_duplicates_aliases_noncanonical_uuids_and_excess_capacity(monkeypatch):
    for rows in ([reviewed(), reviewed()], [reviewed(), reviewed(source_origin="https://other.example.test")],
                 [reviewed(source_path=reviewed()["target_path"])],
                 [reviewed(target_path="/stores/tara/products/ABCDEFAB-1234-4234-8234-123456789012")]):
        with pytest.raises(ValueError):
            seo.parse_legacy_redirects(json.dumps(rows), ORIGIN)
    for raw in ('{}', 'null', '[{}]', '[{"source_path":"one","source_path":"two"}]', '[[['*600, '\ud800'):
        with pytest.raises(ValueError):
            seo.parse_legacy_redirects(raw, ORIGIN)
    monkeypatch.setattr(seo, "MAX_REDIRECTS", 0)
    with pytest.raises(ValueError):
        seo.parse_legacy_redirects(json.dumps([reviewed()]), ORIGIN)
    assert seo.parse_legacy_redirects("[]", ORIGIN) == ()


def test_reviewed_redirect_rechecks_target_and_never_reflects_request_authority_or_query():
    provider = Provider()
    with TestClient(app_for(provider, [reviewed()]), base_url=SOURCE, follow_redirects=False) as client:
        path = reviewed()["source_path"]
        response = client.get(path)
        assert response.status_code == 308 and response.headers["location"] == ORIGIN+reviewed()["target_path"]
        assert response.headers["cache-control"] == "no-store"
        for target in (path+"?secret=value", path.replace("rose", "%72ose"), path+"/", path+"////", path.replace("/rose", "//rose"), path+"%2f"):
            assert client.get(target).status_code == 404
        assert client.get(path, headers={"Host":"attacker.test", "X-Forwarded-Host":"legacy.example.test"}).status_code == 404
        assert client.get("http://legacy.example.test"+path).status_code == 404
        for suffix in ("/", "////", "%2f"):
            for url in (SOURCE+path+suffix, "http://legacy.example.test"+path+suffix):
                alias = client.get(url, headers={"Host":"attacker.test"})
                assert alias.status_code == 404 and "location" not in alias.headers
        assert client.post(path).status_code == 405
        provider.store = snapshot(products=(), categories=())
        assert client.get(path).status_code == 404
        provider.store = None
        gone = client.get(path)
        assert gone.status_code == 404 and "location" not in gone.headers
        order = client.get(f"/stores/tara/orders/{PRODUCT}")
        assert order.status_code == 200 and order.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("target", ["/stores/tara", f"/stores/tara/categories/{CATEGORY}"])
def test_reviewed_home_and_category_destinations_are_current_public_pages(target):
    provider = Provider()
    with TestClient(app_for(provider, [reviewed(target_path=target)]), base_url=SOURCE, follow_redirects=False) as client:
        response = client.get(reviewed()["source_path"])
        assert response.status_code == 308 and response.headers["location"] == ORIGIN+target
        if "/categories/" in target:
            provider.store = snapshot(products=(), categories=())
        else:
            provider.store = snapshot(publication_verified=False)
        gone = client.get(reviewed()["source_path"])
        assert gone.status_code == 404 and "location" not in gone.headers


def test_empty_inventory_exposes_no_guessed_legacy_redirect():
    with TestClient(app_for(Provider()), base_url=SOURCE, follow_redirects=False) as client:
        assert client.get(reviewed()["source_path"]).status_code == 404
        assert client.get("/shop/tara").status_code == 404


def test_fence_blocks_only_seo_alias_normalization_and_preserves_unrelated_router_behavior():
    app = app_for(Provider(), [reviewed()])
    @app.get("/unrelated")
    async def unrelated():
        return {"ok":True}
    with TestClient(app, follow_redirects=False) as client:
        for path in ("/sitemap.xml/", "/sitemap.xml////", "/sitemap%2exml", "/sitemap.xml?token=x",
                     "/sitemap-store-tara.xml/", "/sitemap-store-tara.xml////", "/sitemap-store-%74ara.xml"):
            response = client.get(path, headers={"Host":"attacker.test"})
            assert response.status_code == 404 and "location" not in response.headers
        assert client.get("/unrelated/").status_code == 307


@pytest.mark.parametrize("existing", ["/sitemap-store-tara.xml", "/sitemap-store-tara.{format}",
    "/sitemap-store-tara.xml/", "/sitemap.xml///"])
def test_new_parameter_sitemap_never_shadows_concrete_or_intersecting_pattern(existing):
    app = FastAPI()
    @app.get(existing)
    async def protected():
        return {"protected": True}
    async def dependency():
        return Provider()
    router = seo.create_seo_router(canonical_base=ORIGIN, provider_dependency=dependency)
    with pytest.raises(ValueError, match="collides"):
        seo.validate_route_collisions(app, router)


@pytest.mark.parametrize("existing", ["/legacy/rose-dress/", "/legacy/{item}/"])
def test_request_fence_aliases_never_shadow_existing_route(existing):
    app = FastAPI()
    @app.get(existing)
    async def protected():
        return {"protected":True}
    async def dependency():
        return Provider()
    inventory = seo.parse_legacy_redirects(json.dumps([reviewed()]), ORIGIN)
    router = seo.create_seo_router(canonical_base=ORIGIN, provider_dependency=dependency, legacy_redirects=inventory)
    with pytest.raises(ValueError, match="collides"):
        seo.validate_route_collisions(app, router)


def test_fence_preserves_internal_double_slash_resource_and_inventory_rejects_trailing_aliases():
    with pytest.raises(ValueError):
        seo.parse_legacy_redirects(json.dumps([reviewed(), reviewed(source_path=reviewed()["source_path"]+"/")]), ORIGIN)
    app = FastAPI()
    @app.get("/legacy//rose-dress")
    async def protected():
        return {"protected":True}
    async def dependency():
        return Provider()
    inventory = seo.parse_legacy_redirects(json.dumps([reviewed()]), ORIGIN)
    router = seo.create_seo_router(canonical_base=ORIGIN, provider_dependency=dependency, legacy_redirects=inventory)
    seo.validate_route_collisions(app, router)
    seo.install_seo_request_fence(app, canonical_base=ORIGIN, legacy_redirects=inventory)
    app.include_router(router)
    with TestClient(app, base_url=SOURCE) as client:
        assert client.get("/legacy//rose-dress").json() == {"protected":True}


def test_inventory_never_collides_with_new_parameter_sitemap_route():
    async def dependency():
        return Provider()
    with pytest.raises(ValueError):
        seo.parse_legacy_redirects(json.dumps([reviewed(source_path="/sitemap-store-tara.xml")]), ORIGIN)
    with pytest.raises(ValueError):
        seo.create_seo_router(canonical_base=ORIGIN, provider_dependency=dependency,
                             legacy_redirects=(seo.LegacyRedirect(**reviewed(source_path="/sitemap-store-tara.xml")),))


@pytest.mark.parametrize("late", [False, True])
def test_bootstrap_rejects_existing_or_later_dynamic_route_collision(monkeypatch, late):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", ORIGIN)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", json.dumps([reviewed()]))
    app = FastAPI()
    def add_conflict():
        @app.get("/legacy/{anything:path}")
        async def protected(anything: str):
            return {"protected":True}
    if late:
        install_storefront(app)
        add_conflict()
        with pytest.raises(ValueError, match="collides"):
            with TestClient(app):
                pass
    else:
        add_conflict()
        with pytest.raises(ValueError, match="collides"):
            install_storefront(app)


def test_bootstrap_disabled_boundary_ignores_unconfigured_inventory(monkeypatch):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", False)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", "INVALID-PRIVATE-CONFIG")
    app = FastAPI(); install_storefront(app)
    assert not any(route.path in {"/sitemap.xml", reviewed()["source_path"]} for route in app.routes)
