# E20 storefront integration

Updated: 18 October 2026. Active work, not product-complete. Base is verified `7de7cd6` plus frozen wave-two contracts. Original fixture preview at port 4317 is preserved; this worktree uses port 4318. No production, provider, payment, customer messaging or courier-booking call is authorized or performed.

The first-slice evidence below is historical. The completed canonical API/provider follow-up, current wiring and actual database/browser evidence are recorded in [v1-storefront-integration.md](v1-storefront-integration.md). Its protected status route and strict HTTP 200 replay decoder supersede the pending items described below. Production registration and asset packaging remain integrator-owned.

## First contract slice

`backend/app/api/v1/storefront.py` exports `create_router(canonical_base=..., provider_dependency=...)`; it is not registered in shared startup. The integrator must supply a canonical publication provider and mount only `frontend/storefront/src` at `/storefront-assets/src`. The default provider returns 503/noindex, preventing accidentally exposing legacy or draft products.

Stable server-rendered paths:

- `/stores/{slug}`
- `/stores/{slug}/products/{product_uuid}`
- `/stores/{slug}/categories/{category_uuid}`

The provider's `public_store(slug)` returns internal `PublicStorefront`, after the canonical catalogue service verifies publication, activation, tenant ownership, current mapping and product visibility. `publication_verified=True` is an explicit provider attestation, not a new database publish flag. Reviewed SKU snapshots alone never establish publication. A failed publication assertion, foreign product/category or missing selection returns 404/noindex. Unconfigured/malformed integration returns 503/noindex.

Canonical origin is required configuration and never derives from Host/forwarded headers or product media. HTML, metadata, JSON-LD and bootstrap use escaping and explicit public projections. Product name/description/options are strictly typed; unknown private fields never serialize. Media rejects unsafe schemes, backslashes, controls, credentials, fragments and query strings. There is no independent remote-media fetcher. Strict production media allowlisting/signed-media support must follow the canonical catalogue policy.

SSR contains real linked product names/descriptions/prices without JavaScript. It emits canonical metadata and minimal Product/CollectionPage JSON-LD; no unverified Offer/payment/availability or global-shipping claim is asserted. Public bootstrap includes no customer, order, access token or imported evidence. The public document remains independent of any checkout session.

## Operational capability and checkout

The existing `catalogue.v1` fixture preview remains isolated. The operational entry is `live-entry.js`, using an allowlisted internal `storefront.page.v1` SSR projection. It never activates through a query parameter or fixture flag. `canonical-contract.js` deliberately exports null until the exact `catalogue.v2` request/read/order/error schemas freeze. The live page can display public server data while checkout controls truthfully explain that integration is pending. This is not a claim that real APIs or orders are integrated yet.

`createStorefrontApi()` uses `/api/v1/storefronts/{slug}`, `/products` and `/checkout`. It requires separate named store/products/order decoders and a write encoder. Calls stay same-origin, reject redirects, omit client-supplied tenant/price authority and time out after 15 seconds (bounded injectable timeout for local tests). Only a valid decoded HTTP 201 can confirm an order in this first contract slice; operational replay status still needs agreement. A malformed response, 200, timeout, unknown 409 or server failure is uncertain, not a new order or definitive rejection. Only the canonical error decoder may classify an error as definitive.

Checkout intent is saved **before** POST in sessionStorage, bound to store slug, UUID key and bounded request schema. Ambiguous retry/reload keeps the exact payload and idempotency key and locks bag edits. Double-clicks cannot create another request. Missing/corrupt storage blocks checkout. A 24-hour expiry removes customer/address data while retaining an expired locked tombstone; it never silently makes a fresh key. Definitive rejection and confirmation remove customer/address details. Pending customer/address data is session-scoped, limited to 32 KiB and cleared when that browser session ends. No localStorage or cross-store reuse exists.

Confirmed response totals/currency/status/UUID are validated, and saved confirmations are revalidated on reload. If storage fails after 201, acknowledged confirmation remains in memory; previous durable pending intent stays locked after reload. It must never be labelled “not sent” or permit a new key. Pending payment is explicitly distinct from paid. Navigation URLs require same-origin order-path boundaries and reject token query strings; there is no automatic payment redirect. Capability-token order status and provider-specific payment steps remain pending exact backend contract, and must use Authorization with a private noindex/no-store view rather than token URLs.

## Current verification

- 28 pure Python SSR/router checks pass against a synthetic injected provider, without database/provider access: publication/default-provider denial, foreign selection, strict DTO/privacy, canonical-origin trust, escaping/JSON roundtrip, media URL safety and all three theme paths. The latest three cases reject nested private objects in store policy/category text (`86e2455`); these extend the earlier 25-case evidence.
- Ten pure JavaScript operational checks pass: uncertain exact-body/key reload, immutable ambiguous intent, definitive rejection edit recovery, post-201 storage failure, corrupt confirmation/expiry fail-closed, total/status/URL validation and absent decoder gate.
- Sixteen Chromium browser checks pass: eight preserved fixture journeys and eight injected mock-HTTP operational journeys across all three themes at 390/1440px, including connection-loss/reload exact replay and definitive stock-conflict edit recovery. Twenty total JavaScript checks and syntax checks pass. These are not evidence of a working canonical database/API writer.
- Evidence manifest and two labelled mock-HTTP screenshots: `artifacts/v1/E20/2026-10-18-contract-seams/`. Original browser/JS source is `9f775dd`; additional malformed-provider identity checks are verified at `160312f`. Follow-up `24e1570` preserves canonical product anchors after enhancement and tests Escape/Enter focus. The root reviewer independently ran all 16 browser cases against that unchanged working tree before its commit: 16 passed in 20.8 seconds. The root also reproduced 25 SSR/20 JS checks on the earlier clean `4f8832f`; these source references are intentionally distinct. Docker recheck timed out after eight seconds; no runtime restart or database reset was attempted.
- The preimplementation checkout design study was inspected before these flows were implemented (`design/live-checkout-study.html/.png`).

Run owned checks with `npm --prefix frontend/storefront test`, `npm --prefix frontend/storefront run check`, and `PYTHONPATH=backend python -m pytest backend/tests/test_v1_storefront_rendering.py -q` in a dependency-complete test environment. Browser test configuration defaults to 4318, overridable by `STOREFRONT_TEST_PORT`; it does not reuse the old 4317 preview.

## Remaining gates

Freeze and consume exact operational DTOs/publication services, wire canonical provider/SSR registration/static mount in the integrator, prove actual guarded database activation and SKU checkout, add mock-HTTP browser error journeys and independent QA, then obtain authorized provider/physical-device evidence. Protected status, real payment steps, pagination/SEO sitemap/legacy redirects and real media need integration evidence. Shipping work follows the order-first Parcel Desk scan/link-existing-parcel design; no courier booking is introduced here.
