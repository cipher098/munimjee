"""Bounded public discovery and explicit, reviewed legacy URL redirects.

No database writer, domain provisioning, inferred URL mapping or catchall exists
here. The configured origin and the current publication provider are authority.
"""
from dataclasses import dataclass
from datetime import date
import ipaddress
import json
import re
from urllib.parse import urlsplit
from uuid import UUID
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, RedirectResponse
from starlette.routing import Match, compile_path

from app.v1.storefront.rendering import PublicStorefront, public_product, THEMES
from app.v1.storefront.design import public_design

MAX_STORES = 1000
MAX_PRODUCTS = 1000
MAX_CATEGORIES = 1000
MAX_REDIRECTS = 1000
MAX_XML_BYTES = 2_000_000
MAX_URL_CHARS = 2047
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}", re.ASCII)
_PATH = re.compile(r"/(?:[A-Za-z0-9_.~-]+/)*[A-Za-z0-9_.~-]*", re.ASCII)
_RESERVED = frozenset({
    "api", "auth", "dashboard-auth", "dashboard", "admin", "v1", "stores",
    "shop", "orders", "order", "checkout", "payments", "payment", "webhooks",
    "static", "uploads", "storefront-assets", "editor", "imports", "settings",
    "health", "privacy", "terms", "data-deletion", "onboarding", "favicon.ico",
    "sitemap.xml", "robots.txt", "docs", "redoc", "openapi.json", ".well-known",
})
_ERROR_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


def strict_origin(value: str) -> str:
    """Accept an unambiguous configured ASCII origin, never a request URL.

    Explicit numeric loopback/localhost HTTP is only for isolated local runs.
    IDNA and trailing-dot aliases need a separately reviewed canonical choice.
    """
    if (not isinstance(value, str) or not value or len(value) > 300
            or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)
            or any(c in value for c in "\\%?#")):
        raise ValueError("Invalid SEO origin")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise ValueError("Invalid SEO origin") from None
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"}
            or port is not None and not 1 <= port <= 65535):
        raise ValueError("Invalid SEO origin")
    try:
        address = ipaddress.ip_address(host)
        if address.compressed != host:
            raise ValueError("Invalid SEO origin")
    except ValueError:
        if ":" in host or re.fullmatch(r"[0-9.]+", host) or len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            or label.startswith("xn--") for label in host.split(".")
        ):
            raise ValueError("Invalid SEO origin") from None
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    origin = f"{parsed.scheme}://{authority}"
    if value.rstrip("/") != origin or parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Invalid SEO origin")
    return origin


def _safe_path(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048 or not _PATH.fullmatch(value)
            or "//" in value or any(part in {".", ".."} for part in value.split("/"))):
        raise ValueError("Invalid reviewed redirect path")
    return value


@dataclass(frozen=True)
class LegacyRedirect:
    source_origin: str
    source_path: str
    target_path: str
    store_slug: str
    owner_reference: str
    reviewed_by: str
    reviewed_at: str


def parse_legacy_redirects(raw: str, canonical_base: str) -> tuple[LegacyRedirect, ...]:
    """Validate a bounded explicit inventory. Errors never echo configuration."""
    origin = strict_origin(canonical_base)
    if not isinstance(raw, str):
        raise ValueError("Invalid reviewed redirect inventory")
    try:
        if len(raw.encode("utf-8")) > 1_000_000:
            raise ValueError()
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate reviewed inventory field")
                result[key] = value
            return result
        rows = json.loads(raw, object_pairs_hook=unique_fields)
        if not isinstance(rows, list) or len(rows) > MAX_REDIRECTS:
            raise ValueError()
        inventory = []
        fields = set(LegacyRedirect.__dataclass_fields__)
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields or any(not isinstance(v, str) for v in row.values()):
                raise ValueError()
            mapping = LegacyRedirect(**row)
            if strict_origin(mapping.source_origin) != mapping.source_origin or not _SLUG.fullmatch(mapping.store_slug):
                raise ValueError()
            source = _safe_path(mapping.source_path)
            target = _safe_path(mapping.target_path)
            first_segment = source.split("/")[1].lower()
            if source == "/" or first_segment in _RESERVED or first_segment.startswith("sitemap-store-"):
                raise ValueError()
            base = f"/stores/{mapping.store_slug}"
            if target != base:
                parts = target.split("/")
                if (len(parts) != 5 or "/".join(parts[:3]) != base or parts[3] not in {"products", "categories"}
                        or str(UUID(parts[4])) != parts[4]):
                    raise ValueError()
            for metadata in (mapping.owner_reference, mapping.reviewed_by):
                if not 1 <= len(metadata) <= 128 or metadata.strip() != metadata or any(ord(c) < 32 or ord(c) == 127 for c in metadata):
                    raise ValueError()
            if date.fromisoformat(mapping.reviewed_at).isoformat() != mapping.reviewed_at:
                raise ValueError()
            inventory.append(mapping)
        # Conservative path uniqueness also prevents one host's mapping from
        # shadowing an existing route when deployed behind a different authority.
        sources = {row.source_path for row in inventory}
        if len(sources) != len(inventory) or len({path.rstrip("/") for path in sources}) != len(inventory):
            raise ValueError()
        targets = {(origin, row.target_path) for row in inventory}
        if any((row.source_origin, row.source_path) in targets or row.source_path == row.target_path for row in inventory):
            raise ValueError()
        return tuple(inventory)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ValueError("Invalid reviewed redirect inventory") from None


def public_paths(store: PublicStorefront) -> tuple[str, ...]:
    """Validate and project only canonical public page identities."""
    if store.publication_verified is not True:
        raise LookupError("Storefront unavailable")
    if (not _SLUG.fullmatch(store.slug) or store.theme not in THEMES or store.currency != "INR"
            or len(store.products) > MAX_PRODUCTS or len(store.categories) > MAX_CATEGORIES):
        raise ValueError("Invalid public sitemap projection")
    for field in ("name", "description", "shipping_policy", "return_policy"):
        text = getattr(store, field)
        if not isinstance(text, str) or len(text) > 6000 or field == "name" and not text.strip():
            raise ValueError("Invalid public sitemap store")
    public_design(store.design, store.theme)
    products = [public_product(item) for item in store.products]
    product_ids = [item["product_id"] for item in products]
    sku_ids = [sku["sku_id"] for item in products for sku in item["skus"]]
    categories = []
    for item in store.categories:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not 1 <= len(item["name"]) <= 200:
            raise ValueError("Invalid public sitemap category")
        categories.append(str(UUID(str(item["category_id"]))))
    if (len(set(product_ids)) != len(product_ids) or len(set(categories)) != len(categories) or len(set(sku_ids)) != len(sku_ids)
            or any(not any(sku["active"] for sku in item["skus"]) for item in products)
            or any(item["category_id"] is not None and item["category_id"] not in categories for item in products)
            or any(category not in {item["category_id"] for item in products} for category in categories)):
        raise ValueError("Invalid public sitemap identities")
    base = f"/stores/{store.slug}"
    return (base, *(f"{base}/products/{identity}" for identity in product_ids),
            *(f"{base}/categories/{identity}" for identity in categories))


def _xml(kind: str, paths: tuple[str, ...], origin: str) -> Response:
    root = Element(kind, xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for path in paths:
        if len(origin + path) > MAX_URL_CHARS:
            raise ValueError("Sitemap URL capacity exceeded")
        entry = SubElement(root, "sitemap" if kind == "sitemapindex" else "url")
        SubElement(entry, "loc").text = origin + path
    content = tostring(root, encoding="utf-8", xml_declaration=True)
    if len(content) > MAX_XML_BYTES:
        raise ValueError("Sitemap capacity exceeded")
    return Response(content, media_type="application/xml", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _failure(status=503):
    return HTTPException(status, "Public page unavailable", headers=_ERROR_HEADERS)


def _recognized_path(path):
    return path.rstrip("/") or "/"


class _SEORequestFence:
    """Reject only known SEO/source aliases before Router.redirect_slashes.

    Starlette strips *all* trailing slashes and builds its implicit redirect
    from the request URL. An endpoint check alone runs too late for aliases.
    """
    def __init__(self, app, *, inventory):
        self.app = app
        self.sources = {row.source_path.rstrip("/"): row for row in inventory}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            # Match Starlette's trailing-slash normalization only. Internal
            # repeated slashes can belong to an unrelated existing resource.
            recognized = _recognized_path(path)
            mapping = self.sources.get(recognized)
            sitemap = recognized == "/sitemap.xml" or (
                recognized.startswith("/sitemap-store-") and recognized.endswith(".xml"))
            if mapping is not None or sitemap:
                expected = mapping.source_path if mapping is not None else recognized
                valid = (path == expected and scope.get("raw_path") == expected.encode("ascii", errors="replace")
                         and not scope.get("query_string", b""))
                if mapping is not None:
                    hosts = [value for key, value in scope.get("headers", []) if key.lower() == b"host"]
                    expected_host = urlsplit(mapping.source_origin).netloc.encode("ascii")
                    valid = valid and hosts == [expected_host] and scope.get("scheme") == urlsplit(mapping.source_origin).scheme
                elif recognized != "/sitemap.xml":
                    valid = valid and bool(_SLUG.fullmatch(recognized[len("/sitemap-store-"):-4]))
                if not valid:
                    response = Response('{"detail":"Public page unavailable"}', status_code=404,
                                        media_type="application/json", headers=_ERROR_HEADERS)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def install_seo_request_fence(app, *, canonical_base: str, legacy_redirects=()) -> None:
    """Install before first ASGI request, alongside create_seo_router.

    It changes no global slash policy and captures no unknown legacy paths.
    Direct router consumers need this helper just as the real bootstrap does.
    """
    origin = strict_origin(canonical_base)
    try:
        raw = json.dumps([vars(row) for row in legacy_redirects])
    except (TypeError, AttributeError):
        raise ValueError("Invalid reviewed redirect inventory") from None
    inventory = parse_legacy_redirects(raw, origin)
    app.add_middleware(_SEORequestFence, inventory=inventory)


def validate_route_collisions(app, router: APIRouter) -> None:
    """Fail before serving if explicit SEO paths intersect any other route.

    Repeat at final app startup: app.main registers some legacy routes after
    install_storefront. Included copies of our own routes share endpoint identity.
    """
    for proposed in router.routes:
        scope = {"type": "http", "path": proposed.path, "root_path": "", "method": "GET"}
        for existing in app.routes:
            if (getattr(existing, "endpoint", None) is proposed.endpoint and existing.path == proposed.path):
                continue
            if existing.matches(scope)[0] != Match.NONE:
                raise ValueError("Reviewed SEO route collides with an existing route")
            # The proposed sitemap contains a parameter. Test the reverse
            # direction too, so an existing concrete route/mount cannot be
            # swallowed by the new pattern. Overlapping dynamic fixed prefixes
            # are conservatively refused rather than trying to infer arbitrary
            # converter/regex intersections at startup.
            other_path = getattr(existing, "path", "")
            reverse_scope = {**scope, "path": other_path}
            dynamic_overlap = ("{" in proposed.path and "{" in other_path and (
                proposed.path.split("{", 1)[0].startswith(other_path.split("{", 1)[0])
                or other_path.split("{", 1)[0].startswith(proposed.path.split("{", 1)[0])))
            # The request fence recognizes slash aliases before routing. Such
            # aliases must not silently mask a preexisting literal/dynamic route.
            proposed_alias = _recognized_path(proposed.path)
            existing_alias = _recognized_path(other_path)
            alias_collision = (compile_path(proposed_alias)[0].fullmatch(existing_alias)
                               or compile_path(existing_alias)[0].fullmatch(proposed_alias))
            if proposed.matches(reverse_scope)[0] != Match.NONE or dynamic_overlap or alias_collision:
                raise ValueError("Reviewed SEO route collides with an existing route")


def create_seo_router(*, canonical_base: str, provider_dependency, legacy_redirects=()) -> APIRouter:
    origin = strict_origin(canonical_base)
    # Validate direct callers too; a hand-created dataclass is not authority.
    try:
        raw = json.dumps([vars(row) for row in legacy_redirects])
    except (TypeError, AttributeError):
        raise ValueError("Invalid reviewed redirect inventory") from None
    inventory = parse_legacy_redirects(raw, origin)
    routes = APIRouter(tags=["public-storefront-discovery"])

    async def paths_for(slug, provider):
        if not _SLUG.fullmatch(slug):
            raise _failure(404)
        try:
            store = await provider.public_store(slug)
            if store.slug != slug:
                raise LookupError()
            return public_paths(store)
        except HTTPException as error:
            # Never disclose an upstream body or private provider headers.
            raise _failure(404 if error.status_code == 404 else 503) from None
        except KeyError:
            raise _failure() from None
        except LookupError:
            raise _failure(404) from None
        except (ValueError, TypeError, AttributeError):
            raise _failure() from None

    @routes.get("/sitemap.xml", include_in_schema=False)
    async def sitemap_index(provider=Depends(provider_dependency)):
        try:
            slugs = await provider.public_store_slugs()
            if (not isinstance(slugs, tuple) or len(slugs) > MAX_STORES or len(set(slugs)) != len(slugs)
                    or any(not isinstance(slug, str) or not _SLUG.fullmatch(slug) for slug in slugs)):
                raise ValueError()
            return _xml("sitemapindex", tuple(f"/sitemap-store-{slug}.xml" for slug in slugs), origin)
        except HTTPException as error:
            raise _failure(503) from None
        except (ValueError, TypeError, AttributeError):
            raise _failure() from None

    @routes.get("/sitemap-store-{slug}.xml", include_in_schema=False)
    async def store_sitemap(slug: str, provider=Depends(provider_dependency)):
        paths = await paths_for(slug, provider)
        try:
            return _xml("urlset", paths, origin)
        except ValueError:
            raise _failure() from None

    def redirect_endpoint(mapping):
        async def reviewed_redirect(request: Request, provider=Depends(provider_dependency)):
            hosts = request.headers.getlist("host")
            source = f"{request.scope['scheme']}://{hosts[0]}" if len(hosts) == 1 else ""
            if (source != mapping.source_origin or request.scope.get("raw_path") != mapping.source_path.encode("ascii")
                    or request.scope.get("query_string", b"")):
                raise _failure(404)
            paths = await paths_for(mapping.store_slug, provider)
            if mapping.target_path not in paths:
                raise _failure(404)
            return RedirectResponse(origin + mapping.target_path, status_code=308,
                                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        return reviewed_redirect

    for mapping in inventory:
        routes.add_api_route(mapping.source_path, redirect_endpoint(mapping), methods=["GET"], include_in_schema=False)
    validate_route_collisions(routes, routes)
    return routes
