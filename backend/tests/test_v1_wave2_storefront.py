"""Independent SSR/privacy boundary checks with synthetic provider responses."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.storefront import create_router
from app.v1.storefront.rendering import PublicStorefront, render_storefront


@pytest.fixture
def storefront():
    product_id, sku_id, category_id = (str(uuid4()) for _ in range(3))
    return PublicStorefront(
        slug="synthetic", name="Synthetic boutique", theme="editorial", publication_verified=True,
        products=({"product_id": product_id, "name": "Synthetic dress", "description": "Public facts only",
            "category_id": category_id, "photo_urls": ["/uploads/synthetic.jpg"],
            "floor_price": 51000, "instagram_token": "PRIVATE-TOKEN-SENTINEL", "seller_notes": "PRIVATE-NOTE-SENTINEL",
            "skus": [{"sku_id": sku_id, "product_id": product_id, "options": {"Size": "S"}, "price_minor": 129900,
                "currency": "INR", "stock_available": 2, "active": True, "supplier_cost": "PRIVATE-COST-SENTINEL"}]},),
        categories=({"category_id": category_id, "name": "Dresses"},),
    )


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.scripts = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self.active = {"attrs": dict(attrs), "body": ""}

    def handle_data(self, data):
        if self.active is not None:
            self.active["body"] += data

    def handle_endtag(self, tag):
        if tag == "script" and self.active is not None:
            self.scripts.append(self.active)
            self.active = None


def test_public_html_and_embedded_json_exclude_private_dto_extras(storefront):
    html = render_storefront(storefront, "https://store.example.test")
    for private in ("floor_price", "instagram_token", "seller_notes", "supplier_cost", "PRIVATE-TOKEN-SENTINEL", "PRIVATE-NOTE-SENTINEL", "PRIVATE-COST-SENTINEL"):
        assert private not in html
    document = Document()
    document.feed(html)
    data = json.loads(next(script["body"] for script in document.scripts if script["attrs"].get("id") == "storefront-data"))
    assert data["capabilities"]["sku_checkout"] is False
    assert data["products"][0]["skus"][0]["price_minor"] == 129900


@pytest.mark.parametrize("attack", ["</script><script>alert(1)</script>", '<img src=x onerror="alert(1)">', '"/><svg onload=alert(1)>', "\u2028\u2029<&>"])
def test_source_text_cannot_break_out_of_metadata_or_json_script(storefront, attack):
    source = deepcopy(storefront.products[0])
    source["name"] = attack
    source["description"] = attack
    store = PublicStorefront(**{**storefront.__dict__, "name": attack, "description": attack, "products": (source,)})
    html = render_storefront(store, "https://store.example.test")
    document = Document()
    document.feed(html)
    assert len(document.scripts) == 3
    assert all(not any(name.lower().startswith("on") for name in attrs) for _, attrs in document.tags)
    assert all(tag != "svg" for tag, _ in document.tags)
    data = json.loads(next(script["body"] for script in document.scripts if script["attrs"].get("id") == "storefront-data"))
    assert data["products"][0]["name"] == attack


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/products", "/categories"])
async def test_default_publication_gate_does_not_infer_publish_from_catalogue_data(suffix):
    app = FastAPI()
    app.include_router(create_router(canonical_base="https://configured.example.test"))
    path = "/stores/synthetic" + (suffix + "/" + str(uuid4()) if suffix else "")
    async with AsyncClient(transport=ASGITransport(app), base_url="https://spoofed-host.example.test") as client:
        result = await client.get(path)
    assert result.status_code == 503
    assert result.headers["x-robots-tag"] == "noindex, nofollow"
    assert "configured.example.test" not in result.text


@pytest.mark.asyncio
async def test_canonical_origin_is_configuration_bound_and_foreign_ids_are_404(storefront):
    class Provider:
        async def public_store(self, slug):
            if slug != storefront.slug:
                raise LookupError("Synthetic unavailable store")
            return storefront
    async def provider():
        return Provider()
    app = FastAPI()
    app.include_router(create_router(canonical_base="https://configured.example.test", provider_dependency=provider))
    async with AsyncClient(transport=ASGITransport(app), base_url="https://spoofed-host.example.test") as client:
        public = await client.get("/stores/synthetic")
        assert public.status_code == 200
        assert '<link rel="canonical" href="https://configured.example.test/stores/synthetic">' in public.text
        assert "spoofed-host" not in public.text
        for path in ("/stores/foreign", f"/stores/synthetic/products/{uuid4()}", f"/stores/synthetic/categories/{uuid4()}"):
            result = await client.get(path)
            assert result.status_code == 404
            assert "PRIVATE-" not in result.text


def test_repeated_sku_identity_cannot_alias_two_displayed_products(storefront):
    other = deepcopy(storefront.products[0])
    other["product_id"] = str(uuid4())
    other["name"] = "Different dress"
    other["skus"][0]["product_id"] = other["product_id"]
    store = PublicStorefront(**{**storefront.__dict__, "products": storefront.products + (other,)})
    with pytest.raises(ValueError):
        render_storefront(store, "https://store.example.test")


@pytest.mark.parametrize("field", ["shipping_policy", "return_policy", "category_name"])
def test_nested_private_objects_cannot_pass_through_text_presentation_fields(storefront, field):
    updates = {field: {"credential": "PRIVATE-NESTED-SENTINEL"}}
    if field == "category_name":
        updates = {"categories": ({**storefront.categories[0], "name": updates[field]},)}
    store = PublicStorefront(**{**storefront.__dict__, **updates})
    try:
        html = render_storefront(store, "https://store.example.test")
    except (ValueError, TypeError):
        return
    assert "PRIVATE-NESTED-SENTINEL" not in html, "Nontext presentation data escaped the public-field allowlist"
