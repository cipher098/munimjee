# V1 SEO and acceptance batch ownership

18 October 2026. Base `e750e5a` (reviewed release composition, product base
`3082f1a` / application `dd36b0d`). All three workers must be explicitly configured
GPT-6.1 Sol/high. No hosted CI retries or billing changes, Docker probes/restarts,
production/providers, DNS/routing writes, charges or shared migrations.

## Superseding ownership correction

**CSV is wholly local-owned by catalogue_commerce.** The local product-per-row,
stable document UUID + product_ref contract reserves `0053 → 0052`. Remote workers
must not edit CSV parsing, import APIs/schemas/services/UI/models or migrations.
Local support `0051`, customer links `0052` and analytics (reported `3556850`)
are separate work. Do not claim them integrated into this frozen remote base.

## Frozen file ownership before parallel writes

| Lane | Branch / worktree | Ownership |
| --- | --- | --- |
| SEO implementation | `codex/v1-seo-publication` / `munimjee-wave6-seo` | `backend/app/api/v1/storefront.py`, `storefront_bootstrap.py`, `backend/app/services/storefront_publication.py`, new `backend/app/v1/storefront/seo.py`; one narrowly named redirect-config field in `backend/app/config.py` if needed; dedicated `test_v1_seo*.py` files, `docs/v1-seo-publication.md`, `artifacts/v1/seo-publication/` |
| Independent SEO QA | `codex/v1-seo-independent-qa` / `munimjee-wave6-qa` | New `backend/tests/test_v1_seo_independent*.py`, dedicated new mounted SEO harness/server if warranted, `docs/v1-seo-independent-qa.md`, `artifacts/v1/seo-independent-qa/`; peer source read-only |
| Read-only acceptance delta | `codex/v1-acceptance-delta` / `munimjee-wave6-acceptance` | New `docs/v1-acceptance-delta.md`, `artifacts/v1/acceptance-delta/` and new evidence verifier only if meaningful; no existing audit/product edits |
| Coordinator | `codex/v1-seo-coordination` | This contract, composition, aggregate evidence and handoff |

No edits to `app/main.py`, existing rendering/checkout/catalogue contracts,
import recovery UI, product schemas/models/migrations, release workflow/locks,
shared go-live plan or local team product files without a precise contract review.
New app Python modules enter the existing runtime allowlist automatically.

## SEO API and safety contract

- Retain the existing default-off `V1_STOREFRONT_ENABLED` installation boundary,
  authoritative configured canonical origin and published provider. No Host or
  forwarded-header-derived canonical links.
- Add a discoverable bounded sitemap index and per-store sitemap, containing only
  genuinely published, active tenant stores and canonical public product/category
  pages. Never expose private/draft/foreign products, orders, tokens, seller IDs,
  imports or editor routes. No fake lastmod dates or silent capacity truncation.
- Freeze concrete route/config/function signatures with coordinator and QA before
  adapting peer consumers. Prefer additive SEO routing through the existing
  storefront bootstrap. Leave existing order capability links usable.
- Redirect infrastructure consumes only an explicit reviewed inventory. Default
  inventory is empty; no real mappings are guessed or enabled. Exact safe source
  origin/path must bind to an owned reviewed canonical destination, itself checked
  against current public publication. No arbitrary external target, path/query
  reflection, protocol-relative URL, traversal/encoding confusion, wildcard/catchall
  routing, chain/loop or protected route collision. Existing real route conflicts
  fail closed rather than silently replacing authentication/API/order behavior.
- Inventory fields carry review/ownership metadata but never secrets. Reject invalid
  configuration at startup, bound entries, and document domain/provider authority
  as a separate deployment gate. Code tests with `.example.test` mappings establish
  infrastructure behavior only, not a migrated seller's actual URL acceptance.
- No new database schema. A schema need is a contract blocker to report, not a
  reason to invent a migration after local `0053`.

Frozen implementation seam: new `app.v1.storefront.seo.create_seo_router(*,
canonical_base, provider_dependency, legacy_redirects=())` exposes `/sitemap.xml`
and `/stores/{slug}/sitemap.xml`; provider adds bounded `public_store_slugs()`.
The configured inventory field is `V1_STOREFRONT_LEGACY_REDIRECTS`, default `[]`.
`parse_legacy_redirects(raw, canonical_base)` returns validated `LegacyRedirect`
entries with `source_origin`, `source_path`, `target_path`, `store_slug`,
`owner_reference`, `reviewed_by`, `reviewed_at` (ISO date). Sources match exact
scheme/Host/raw path without query; destinations are the configured canonical
store/product/category paths, rechecked for current public existence. `/shop`
and all order/auth/API/static/editor routes are protected from legacy overrides.
No inferred production mappings are part of this batch.

## Verification and handoff

Reuse P01 exact numeric-loopback lane validation, matching test database name,
explicit reset opt-in and held advisory lease. Actual DB checks need a separately
allocated lane; never reuse a source/production URL or weaken guards. Docker is
known unavailable here; do not probe it again. Cached Python3.11 interpreter:
`/tmp/munimjee-release-ci-py311/bin/python`. Browser cache and fixture harness may
be reused, with synthetic versus actual API/DB evidence labelled exactly.

QA independently probes publication revocation/tenant scope, canonical origin and
Host injection, XML escaping/capacity, redirect validation and order-link regression.
Review source safety before any optional mounted execution. Preserve historical
audit/evidence; a later feature does not retroactively close full V12 or G0–G6.
The acceptance lane tracks exact frozen source versus reported local work and
remaining V1 code-owned/provider/device/operational gates without duplicate writes.
Push bounded separate branches with exact SHAs, commands, passes/skips and a local
actual-PG16/mounted verification path. Do not claim release readiness.
