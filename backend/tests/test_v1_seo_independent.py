"""Independent adversarial SEO acceptance; synthetic ASGI provider, no sockets/DB.

The producer's unit fixtures are deliberately not imported. Real publication
queries are covered separately by the guarded migrated selection.
"""
from dataclasses import replace
import json
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.applications import Starlette
import pytest

from app.api.v1.storefront import create_router
from app.v1.storefront.rendering import PublicStorefront

ORIGIN = "https://canonical.example.test"
SOURCE = "https://legacy.example.test"
PID = "10000000-0000-4000-8000-000000000001"
CID = "20000000-0000-4000-8000-000000000001"
SID = "30000000-0000-4000-8000-000000000001"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def snapshot(**changes):
    product = {"product_id": PID, "name": 'Silk & <private-looking> "set"',
               "description": "PRIVATE-DESCRIPTION-SENTINEL", "category_id": CID,
               "skus": [{"sku_id": SID, "product_id": PID, "price_minor": 100,
                         "stock_available": 1, "currency": "INR", "active": True}]}
    return replace(PublicStorefront(slug="tara", name="Synthetic & <boutique>",
        theme="catalogue", products=(product,), categories=({"category_id": CID,
        "name": "Occasion & <wear>"},), publication_verified=True), **changes)


class Provider:
    def __init__(self):
        self.stores = {"tara": snapshot()}
        self.slugs = None
        self.calls = []

    async def public_store_slugs(self):
        return tuple(self.stores) if self.slugs is None else self.slugs

    async def public_store(self, slug):
        self.calls.append(slug)
        if slug not in self.stores:
            raise HTTPException(404, "PRIVATE-PROVIDER-SECRET", headers={"X-Private": "secret"})
        value = self.stores[slug]
        if isinstance(value, Exception):
            raise value
        return value


def mapping(**changes):
    row = dict(source_origin=SOURCE, source_path="/old-dress", target_path=f"/stores/tara/products/{PID}",
               store_slug="tara", owner_reference="synthetic-owner-review", reviewed_by="synthetic-reviewer",
               reviewed_at="2026-10-18")
    row.update(changes)
    return row


def seo():
    # Lazy import permits baseline order-shell acceptance before composition.
    from app.v1.storefront import seo as module
    return module


def make_app(provider, rows=()):
    async def dependency():
        return provider
    app = FastAPI()
    inventory = seo().parse_legacy_redirects(json.dumps(list(rows)), ORIGIN)
    app.include_router(seo().create_seo_router(canonical_base=ORIGIN,
        provider_dependency=dependency, legacy_redirects=inventory))
    app.include_router(create_router(canonical_base=ORIGIN, provider_dependency=dependency))
    seo().install_seo_request_fence(app, canonical_base=ORIGIN, legacy_redirects=inventory)
    return app


def locations(response, kind):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"<?xml")
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["cache-control"] == "no-store"
    root = ET.fromstring(response.content.decode("utf-8"))
    assert root.tag == NS + kind
    assert not root.findall(".//" + NS + "lastmod")
    result = [node.text for node in root.findall(".//" + NS + "loc")]
    assert len(result) == len(set(result))
    assert all(urlsplit(url).netloc == "canonical.example.test" and len(url) < 2048 for url in result)
    return result


def test_baseline_order_shell_survives_revoked_publication_without_provider_call():
    provider = Provider()
    provider.stores.clear()
    async def dependency():
        return provider
    app = FastAPI()
    app.include_router(create_router(canonical_base=ORIGIN, provider_dependency=dependency))
    with TestClient(app) as client:
        assert client.get("/stores/tara").status_code == 404
        provider.calls.clear()
        result = client.get(f"/stores/tara/orders/{PID}", params={"token": "PRIVATE-CAPABILITY"})
    assert result.status_code == 200
    assert provider.calls == []
    assert "PRIVATE-CAPABILITY" not in result.text
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-robots-tag"] == "noindex, nofollow"


def test_protocol_scope_namespace_utf8_and_configured_origin_only():
    with TestClient(make_app(Provider())) as client:
        index = locations(client.get("/sitemap.xml", headers={"Host": "attacker.test",
            "Forwarded": "host=attacker.test;proto=http", "X-Forwarded-Host": "attacker.test"}), "sitemapindex")
        assert index == [ORIGIN + "/sitemap-store-tara.xml"]
        result = client.get("/sitemap-store-tara.xml")
        urls = locations(result, "urlset")
        assert set(urls) == {ORIGIN + "/stores/tara", ORIGIN + f"/stores/tara/products/{PID}",
                            ORIGIN + f"/stores/tara/categories/{CID}"}
        assert all(urlsplit(url).path.startswith(urlsplit(index[0]).path.rsplit("/", 1)[0] + "/") for url in urls)
        for private in ("PRIVATE-", "private-looking", "orders/", "token", "seller", "imports", "attacker.test"):
            assert private not in result.text
        assert client.get("/stores/tara/sitemap.xml").status_code == 404


@pytest.mark.parametrize("slugs", [("tara", "tara"), ("tara", "../secret"), ("tara", None),
                                    ["tara"], tuple(f"s{i}" for i in range(1001))])
def test_invalid_or_over_capacity_discovery_is_wholly_unavailable(slugs):
    provider = Provider(); provider.slugs = slugs
    with TestClient(make_app(provider)) as client:
        result = client.get("/sitemap.xml")
    assert result.status_code == 503
    assert "<loc>" not in result.text and result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad,status", [(snapshot(publication_verified=False), 404), (snapshot(slug="foreign"), 404),
    (snapshot(products=({},)), 503), (snapshot(products=({"name": "Missing identity"},)), 503),
    (snapshot(categories=({},)), 503), (snapshot(products=(snapshot().products[0],) * 1001), 503),
    (HTTPException(503, "PRIVATE-PROVIDER-SECRET", headers={"X-Private": "secret"}), 503)])
def test_untrusted_provider_projection_fails_closed_and_redacted(bad, status):
    provider = Provider(); provider.stores["tara"] = bad
    with TestClient(make_app(provider), raise_server_exceptions=False) as client:
        result = client.get("/sitemap-store-tara.xml")
    assert result.status_code == status, result.text
    assert "PRIVATE" not in result.text and "x-private" not in result.headers
    assert result.headers["cache-control"] == "no-store"


def test_redirect_rechecks_target_and_unpublish_leaves_private_order_route():
    provider = Provider()
    with TestClient(make_app(provider, [mapping()]), base_url=SOURCE) as client:
        url = "/old-dress"
        first = client.get(url, follow_redirects=False)
        assert first.status_code == 308
        assert first.headers["location"] == ORIGIN + f"/stores/tara/products/{PID}"
        assert first.headers["cache-control"] == "no-store"
        provider.stores["tara"] = snapshot(products=(), categories=())
        assert client.get(url, follow_redirects=False).status_code == 404
        provider.stores.clear()
        assert client.get(url, follow_redirects=False).status_code == 404
        assert locations(client.get("/sitemap.xml"), "sitemapindex") == []
        assert client.get("/sitemap-store-tara.xml").status_code == 404
        assert client.get(f"/stores/tara/orders/{PID}").status_code == 200


@pytest.mark.parametrize("target", ["/old-dress?token=x", "/old%2Ddress", "/%6Fld-dress", "/old-dress/extra", "/old-dress/"])
def test_raw_path_query_or_suffix_cannot_inherit_reviewed_mapping(target):
    with TestClient(make_app(Provider(), [mapping()]), base_url=SOURCE) as client:
        result = client.get(target, follow_redirects=False)
    assert result.status_code == 404 and "location" not in result.headers


@pytest.mark.parametrize("base,headers", [(ORIGIN, {}), ("http://legacy.example.test", {}),
    (SOURCE, {"Host": "LEGACY.example.test"}), (SOURCE, {"Host": "legacy.example.test:443"}),
    ("https://attacker.test", {"X-Forwarded-Host": "legacy.example.test", "X-Forwarded-Proto": "https"}),
    (SOURCE, [("Host", "legacy.example.test"), ("Host", "attacker.test")])])
def test_origin_port_case_and_duplicate_host_must_exactly_match_review(base, headers):
    with TestClient(make_app(Provider(), [mapping()]), base_url=base) as client:
        response = client.get("/old-dress", headers=headers, follow_redirects=False)
    assert response.status_code == 404 and "location" not in response.headers


@pytest.mark.parametrize("origin", ["https://good.test\n", "https://good.test\t", "https://good.test\x00",
    "https://good.test:", "https://good.test:0", "https://good.test:65536", "https://good.test:abc",
    "https://good.test:0443", "https://GOOD.test", "https://good.test.", "https://user@good.test",
    "https://good.test\\evil", "https://good.test%2e", "https://good.test?", "https://good.test#",
    "https://good.test//", "https://xn--bcher-kva.test", "https://bücher.test", "https://[::1]evil",
    "http://public.example.test", "http://127.0.0.2"])
def test_canonical_origin_ambiguities_rejected(origin):
    with pytest.raises(ValueError):
        seo().create_seo_router(canonical_base=origin, provider_dependency=lambda: Provider())


@pytest.mark.parametrize("field,value", [("source_path", p) for p in ("/", "/shop/tara", "/api", "/stores/tara/orders/" + PID,
    "/privacy", "/dashboard/x", "/sitemap.xml", "/old/*", "/old/{slug}", "/old/../dress", "/old/%2e%2e/dress",
    "/old\\dress", "//evil.test", "/old?x=1", "/old#x", "/old//dress")]
    + [("target_path", p) for p in ("https://evil.test/x", "//evil.test/x", "/stores/foreign", "/stores/tara/orders/" + PID,
        "/stores/tara/products/" + PID + "?x=1", "/stores/tara/products/" + PID.upper(), "/stores/tara/../foreign")]
    + [("reviewed_at", "2026-02-30"), ("owner_reference", ""), ("reviewed_by", "reviewer\nsecret")])
def test_unreviewable_inventory_never_installs(field, value):
    # PID here has no alphabetic hex; uppercasing it is not a malformed UUID.
    if field == "target_path" and value == f"/stores/tara/products/{PID}":
        value = "/stores/tara/products/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    with pytest.raises(ValueError, match="Invalid reviewed redirect inventory"):
        seo().parse_legacy_redirects(json.dumps([mapping(**{field: value})]), ORIGIN)


def test_empty_default_duplicate_keys_duplicate_sources_and_forged_dataclass():
    assert seo().parse_legacy_redirects("[]", ORIGIN) == ()
    for raw in (json.dumps([mapping(), mapping(source_origin="https://second.example.test")]),
                '[{"source_origin":"https://one.test","source_origin":"https://two.test"}]',
                json.dumps([mapping()] * 1001), json.dumps([mapping(unreviewed_extra="secret")])):
        with pytest.raises(ValueError):
            seo().parse_legacy_redirects(raw, ORIGIN)
    with pytest.raises(ValueError):
        seo().create_seo_router(canonical_base=ORIGIN, provider_dependency=lambda: Provider(),
            legacy_redirects=(seo().LegacyRedirect(**mapping(target_path="https://evil.test")),))


@pytest.mark.parametrize("kind", ["explicit", "dynamic", "crossing", "mount"])
def test_bootstrap_rejects_late_route_collisions(monkeypatch, kind):
    from app.api.v1.storefront_bootstrap import install_storefront
    from app.config import settings
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", ORIGIN)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", "[]")
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", "")
    app = FastAPI(); install_storefront(app)
    if kind == "mount":
        app.mount("/sitemap-store-tara.xml", Starlette())
    else:
        path = {"explicit": "/sitemap-store-tara.xml", "dynamic": "/{existing}",
                "crossing": "/sitemap-{kind}-tara.xml"}[kind]
        app.add_api_route(path, lambda: {"private": True})
    with pytest.raises(ValueError, match="collid"):
        with TestClient(app):
            pass


def test_existing_concrete_route_cannot_be_shadowed_by_dynamic_seo_router():
    app = FastAPI()
    app.add_api_route("/sitemap-store-tara.xml", lambda: {"existing": True})
    router = seo().create_seo_router(canonical_base=ORIGIN, provider_dependency=lambda: Provider())
    with pytest.raises(ValueError, match="collid"):
        seo().validate_route_collisions(app, router)


def test_xml_encoder_escapes_text_and_byte_capacity_never_returns_partial_xml():
    # Direct encoder input verifies XML serialization; route identities remain
    # restricted and never intentionally permit an ampersand in a slug/path.
    response = seo()._xml("urlset", ("/stores/a&b",), ORIGIN)
    assert b"a&amp;b" in response.body
    assert ET.fromstring(response.body).find(".//" + NS + "loc").text == ORIGIN + "/stores/a&b"


def test_xml_location_must_be_strictly_less_than_2048_characters():
    path = "/" + "a" * (2047 - len(ORIGIN) - 1)
    response = seo()._xml("urlset", (path,), ORIGIN)
    assert len(ET.fromstring(response.body).find(".//" + NS + "loc").text) == 2047
    with pytest.raises(ValueError):
        seo()._xml("urlset", (path + "a",), ORIGIN)


def test_category_redirect_revokes_and_home_redirect_remains_currently_public():
    provider = Provider()
    rows = [mapping(source_path="/old-category", target_path=f"/stores/tara/categories/{CID}"),
            mapping(source_path="/old-home", target_path="/stores/tara")]
    with TestClient(make_app(provider, rows), base_url=SOURCE) as client:
        assert client.get("/old-category", follow_redirects=False).status_code == 308
        assert client.get("/old-home", follow_redirects=False).status_code == 308
        provider.stores["tara"] = snapshot(products=(), categories=())
        assert client.get("/old-category", follow_redirects=False).status_code == 404
        assert client.get("/old-home", follow_redirects=False).status_code == 308


def test_xml_byte_capacity_failure_is_503_without_partial_locations(monkeypatch):
    monkeypatch.setattr(seo(), "MAX_XML_BYTES", 1)
    with TestClient(make_app(Provider())) as client:
        for path in ("/sitemap.xml", "/sitemap-store-tara.xml"):
            result = client.get(path)
            assert result.status_code == 503 and "<loc>" not in result.text


def test_discovery_at_documented_bound_contains_all_thousand_stores():
    provider = Provider(); provider.slugs = tuple(f"store-{i}" for i in range(1000))
    with TestClient(make_app(provider)) as client:
        urls = locations(client.get("/sitemap.xml"), "sitemapindex")
    assert len(urls) == 1000
    assert urls[-1] == ORIGIN + "/sitemap-store-store-999.xml"


@pytest.mark.parametrize("base", [SOURCE, "http://legacy.example.test", "https://attacker.example.test"])
@pytest.mark.parametrize("path", ["/old-dress/", "/old-dress///", "/%6Fld-dress///", "/old-dress%2F%2F", "/old-dress/?token=x"])
def test_source_slash_and_decoded_aliases_never_emit_prevalidation_redirect(base, path):
    with TestClient(make_app(Provider(), [mapping()]), base_url=base) as client:
        result = client.get(path, follow_redirects=False)
    assert result.status_code == 404 and "location" not in result.headers


@pytest.mark.parametrize("path", ["/sitemap.xml/", "/sitemap.xml///", "/%73itemap.xml", "/sitemap-store-tara.xml///", "/sitemap-store-tara.xml%2F"])
def test_discovery_aliases_never_emit_host_derived_location(path):
    with TestClient(make_app(Provider()), base_url="https://attacker.example.test") as client:
        result = client.get(path, follow_redirects=False)
    assert result.status_code == 404 and "location" not in result.headers


def test_request_fence_leaves_unrelated_route_normalization_intact():
    app = make_app(Provider(), [mapping()])
    app.add_api_route("/unrelated", lambda: {"ok": True})
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/unrelated///", follow_redirects=False)
    assert result.status_code == 307 and result.headers["location"] == ORIGIN + "/unrelated"


def test_inventory_cannot_assign_a_slash_alias_to_a_second_mapping():
    with pytest.raises(ValueError):
        seo().parse_legacy_redirects(json.dumps([mapping(), mapping(source_path="/old-dress/",
            source_origin="https://second.example.test")]), ORIGIN)


def test_feature_disabled_does_not_install_discovery_or_validate_unused_inventory(monkeypatch):
    from app.api.v1.storefront_bootstrap import install_storefront
    from app.config import settings
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", "not-reviewed-json")
    app = FastAPI(); install_storefront(app)
    assert not any(getattr(route, "path", "").startswith(("/sitemap", "/stores", "/old")) for route in app.routes)
    assert app.user_middleware == []


@pytest.mark.parametrize("source,existing", [("/old-dress/", "/old-dress"), ("/old-dress", "/old-dress/")])
@pytest.mark.parametrize("late", [False, True])
def test_fence_cannot_take_ownership_of_existing_slash_alias_resource(monkeypatch, source, existing, late):
    from app.api.v1.storefront_bootstrap import install_storefront
    from app.config import settings
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", ORIGIN)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", json.dumps([mapping(source_path=source)]))
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", "")
    app = FastAPI()
    if not late:
        app.add_api_route(existing, lambda: {"private": True})
    with pytest.raises(ValueError, match="collid"):
        install_storefront(app)
        if late:
            app.add_api_route(existing, lambda: {"private": True})
        with TestClient(app):
            pass


@pytest.mark.parametrize("late", [False, True])
def test_fence_does_not_mask_existing_internal_double_slash_route(monkeypatch, late):
    from app.api.v1.storefront_bootstrap import install_storefront
    from app.config import settings
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", ORIGIN)
    monkeypatch.setattr(settings, "V1_STOREFRONT_LEGACY_REDIRECTS", json.dumps([mapping(source_path="/old/path")]))
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", "")
    app = FastAPI()
    if not late:
        app.add_api_route("/old//path", lambda: {"existing": True})
    # Conservative startup refusal or narrower fence scope are both safe.
    try:
        install_storefront(app)
        if late:
            app.add_api_route("/old//path", lambda: {"existing": True})
        with TestClient(app) as client:
            response = client.get("/old//path", follow_redirects=False)
    except ValueError:
        return
    assert response.status_code == 200 and response.json() == {"existing": True}
