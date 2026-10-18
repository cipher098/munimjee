# Bounded V1 public discovery and reviewed redirects

18 October 2026. This source-only addition is based on `e750e5a`. It does not
complete V12, seller migration acceptance or any release gate. The authoritative
ownership/freeze is `docs/v1-seo-contracts.md` in the coordinator checkout.

## Public discovery

The existing default-off `V1_STOREFRONT_ENABLED` bootstrap installs
`GET /sitemap.xml` and `GET /sitemap-store-{slug}.xml` alongside the existing SSR
routes. The index lists only published storefronts whose Seller and Business are
currently active. Each per-store file uses the same current canonical publication
provider as SSR and lists only its store home, activated active products with
active SKUs, and the tenant-owned categories referenced by those products.
Drafts, seller IDs, private product data, order/capability links, imports and editor
URLs are never projected. The index contains store slugs, not tenant identifiers.

Per-store files live at the origin root so their canonical `/stores/{slug}` home
is within the sitemap's directory scope. See the primary
[Sitemaps protocol](https://www.sitemaps.org/protocol.html#location), including the
single-host, location, UTF-8/XML escaping and less-than-2,048-character URL rules.
XML uses the standard serializer/namespace. No generated or guessed lastmod,
priority, inventory timestamps or search-engine indexing promises are supplied.
The standard root index is the discovery URL; robots.txt/provider submission is
a separate deployment concern.

Limits are 1,000 stores, 1,000 products and 1,000 categories per store, 2,000,000
serialized XML bytes and 2,047 characters per emitted absolute URL. The index DB
query requests 1,001 slugs and fails 503 at capacity; existing public product
publication already has the equivalent 1,001-row sentinel. Over-capacity or
malformed projections fail without partial XML. There is no silent truncation.
All sitemap and redirect responses use `Cache-Control: no-store` so a new request
rechecks publication. A successful already-completed response is not a claim that
the store remains published indefinitely.

`PUBLIC_BASE_URL` is the only canonical authority; Host and forwarded headers
never construct sitemap links or redirect targets. SEO startup additionally
requires unambiguous lowercase ASCII DNS/HTTPS authority with a valid explicit
port, if present. Credentials, controls, whitespace, Unicode/IDNA aliases, trailing
dots, percent escapes, backslashes, non-root paths, query/fragment delimiters and
ambiguous numeric hosts are rejected. Explicit `http://localhost`,
`http://127.0.0.1` or `http://[::1]` origins are available for isolated local runs.
The existing rendering/checkout contracts are unchanged.

## Explicit reviewed inventory

`V1_STOREFRONT_LEGACY_REDIRECTS` is a JSON string defaulting to `[]`. No real URL
inventory is supplied or guessed. Every enabled row must contain exactly:

```json
{
  "source_origin": "https://legacy.example.test",
  "source_path": "/legacy/reviewed-dress",
  "target_path": "/stores/reviewed-shop/products/abcdefab-1234-4234-8234-123456789012",
  "store_slug": "reviewed-shop",
  "owner_reference": "synthetic-owner-review-001",
  "reviewed_by": "synthetic-domain-owner",
  "reviewed_at": "2026-10-18"
}
```

This is an inert format example, not a deployable seller mapping. Review metadata
must be nonempty, bounded and free of controls; dates must use the exact ISO date
format. It is an ownership assertion requiring external verification, not proof of
domain authority. Never place credentials, tokens or customer details in metadata.
Unknown/duplicate JSON fields, excessive input/depth and more than 1,000 rows fail
configuration. `LegacyRedirect` is an immutable internal value; direct router
callers are revalidated and cannot bypass inventory validation.

Source paths are exact bounded ASCII paths. Percent encoding (including double
encoding), traversal, repeated slashes, path templates, wildcards, backslashes,
query strings and fragments are rejected. The first source segment may not be a
protected route family, including `/shop`, `/stores`, orders, checkout, auth/API,
dashboard, static/uploads, editors, legal/health/onboarding or sitemap discovery.
Only same-configured-origin target paths `/stores/{store_slug}` or its canonical
product/category UUID pages are accepted. Duplicate source paths are rejected
even across origins. Chains, loops, self-targets and route collisions fail closed.

Installation checks the existing routing table and repeats validation at final
application startup, since main declares some legacy routes after the bootstrap.
Matching is bidirectional for concrete routes/mounts; overlapping dynamic fixed
prefixes are conservatively refused. Invalid configuration prevents startup rather
than overriding an order, authentication or other existing route. The application
must run its normal ASGI lifespan/startup. There is no catchall redirect route.

An accepted GET returns 308 only if the actual ASGI scheme and single Host header
exactly match the reviewed source origin, raw path bytes exactly match the reviewed
path, and no query is present. Request ports/case are not normalized: explicit
`:443` and absent port are distinct reviewed authorities. Forwarded headers do
not confer authority. The deployment proxy must strip untrusted forwarding headers
before applying any server-level trusted-proxy transformation of ASGI scheme.
Every request re-reads current publication and confirms the exact destination
remains a public page. Unpublished/removed/foreign targets return 404 with no
Location. Invalid/unavailable provider data returns 503 without echoing its
private details. The destination always combines the configured origin and
reviewed path; neither request query nor request authority is reflected.

A narrowly scoped ASGI request fence runs before Starlette's implicit slash
redirects. It recognizes only declared source paths and their repeated/trailing
slash aliases plus the new sitemap namespace, rejecting alias/raw-byte/query or
source-authority mismatches with 404 and no Location. This closes framework
normalization paths that would otherwise run before endpoint validation and
reflect a request Host. Other routes retain their existing slash behavior.

## Frozen Python interfaces

`app.v1.storefront.seo` exports `strict_origin(value) -> str`,
`parse_legacy_redirects(raw, canonical_base) -> tuple[LegacyRedirect, ...]`,
`public_paths(store) -> tuple[str, ...]`,
`create_seo_router(*, canonical_base, provider_dependency, legacy_redirects=())`,
and `validate_route_collisions(app, router) -> None`.
Direct router consumers must also call
`install_seo_request_fence(app, *, canonical_base, legacy_redirects=())` **before
the first ASGI request**. The real storefront bootstrap installs this fence.
`PublishedStorefrontProvider.public_store_slugs() -> tuple[str, ...]` supplies
the bounded current index; existing `public_store(slug)` remains authoritative.
Configuration errors raise non-echoing `ValueError`; unverified public projection
raises `LookupError`. Successful XML is 200, gone pages 404, unavailable/oversized
publication 503, and supported reviewed redirects 308.

## Verification and local rerun

Remote evidence is pure and synthetic ASGI only. The added actual-main/migration
tests are explicitly skipped here because no disposable PostgreSQL lane is
allocated. They preserve P01's exact numeric-loopback URL, matching database name,
explicit reset opt-in, blocked provider networking and held migration/reset lease.
No alternate DB, Docker probe, reset or service restart was attempted.

From `backend/`, source-only regression:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest -q tests/test_v1_seo_publication.py tests/test_v1_seo_publication_db.py tests/test_v1_storefront_bootstrap.py tests/test_v1_storefront_rendering.py tests/test_storefront_publication.py
```

The local owner must first allocate an exclusive disposable PostgreSQL **16**
database named `munimjee_test_seo_publication`, a numeric loopback endpoint and
disposable credentials. Set `TEST_LANE=seo_publication`, `TEST_DB_RESET=1` and
`TEST_DATABASE_URL` to that exact assigned
`postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/munimjee_test_seo_publication`
URL. USER/PASSWORD/PORT are placeholders, not values to paste. Do not use a source,
development, shared or production database. The fixture drops/rebuilds its schema
under the unchanged held advisory lease and runs the actual Alembic chain.

Then run the same command above. The seven new `test_v1_seo_publication_db.py`
cases exercise **actual app.main routing and final startup**, native signup,
reviewed SKU activation, current Seller/Business/store/product/SKU/activation
revocation, category tenant scope, a real COD order and the retained bearer
capability after unpublication. They assert PG16 and use ASGI HTTP, not a real
browser or actual external domain. Existing baseline publication checks rerun in
the same selection. Save the full command, source hashes, XML report and raw output.

Independent QA has separate source/evidence and its own mounted rerun instructions.
Actual seller URL inventory/ownership, domain/provider routing authority and TLS,
search-engine fetch/discovery, migration reconciliation and rollback, existing
seller/customer order-link preservation on actual domains, physical browser/device
acceptance and final integrated PG16/runtime-image/hosted CI gates remain open.
This addition does not retroactively close the historical release acceptance audit.
