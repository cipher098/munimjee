# Canonical storefront publication and COD integration

This bounded local slice connects the existing three storefront themes to actual `catalogue.v2` SKU APIs and the B20 order writer. The default publication presentation is catalogue. Only COD is advertised by this browser publication provider and canonical store decoder; gateway-only stores remain browse-only with truthful online-payment-unavailable copy. Existing gateway APIs remain unchanged. Theme persistence and a seller theme-setting system are not implemented. No provider/payment/customer-message call or deployment was performed.

`PublishedStorefrontProvider` requires a published Storefront, active Seller and Business, active Product, explicit tenant-bound CatalogueActivation and at least one active same-tenant canonical SKU. Product names/descriptions may come from the activated product record; prices, options, available stock and currency come only from current SKUs. Unactivated or inactive records never fall back to legacy inventory. Tenant category references are checked. The provider fails closed beyond 1,000 products until paged SSR is available.

Public collection, product and category pages retain their existing canonical paths and render linked names, descriptions, INR prices and conservative availability without JavaScript. Hydration uses only the public projection. Query-bearing, credential-bearing, unsafe and malformed media URLs are omitted, including after availability refresh. No media bytes are retained or fetched by the server. The synthetic browser captures intentionally show “Image unavailable” rather than substitute imagery.

The canonical adapter consumes the exact committed storefront.v1/catalogue.v2/order.v1 shapes. Product refresh reads bounded pages and rejects changed totals or duplicate product/SKU IDs across pages. It never infers tenant, price or stock from a checkout request. Both 201 creation and 200 identical-key replay require a valid matching order body, item quantities, server totals, payment method, customer/address and 64-character capability before confirmation. Pending COD is displayed as pending, never paid.

The only definitive backend stock failure is HTTP 409 detail.code `sku_out_of_stock`, emitted by the pre-reservation insufficient-quantity branch. Idempotency lookup remains before this branch. Rejection creates no customer, order, reservation, payment attempt or access capability. Every other 409, timeout, malformed success, 500 or lost response retains the original uncertain body/key. No automatic resend or fresh key occurs. The documented JSON fixture and error schema are under `docs/contracts/catalogue-v2/`.

Pending intent is saved before POST in sessionStorage. Reload retries the exact intent. Confirmation/rejection removes customer/address details; a known confirmed order retains only item IDs/quantities, totals/status/reference and session-held capability. The capability is removed when reopening an older-than-24-hour confirmation. Expired uncertain intent loses PII but remains locked. Session storage failure blocks a first POST and cannot turn an acknowledged response into a rejected attempt. Closing the browser session loses its order-access capability; no recovery-by-email/phone is claimed.

`/stores/{slug}/orders/{order_uuid}` is a private no-store/noindex shell containing only the two route identifiers. The capability stays in sessionStorage and the Authorization header, never a URL, public HTML or image. Status remains available after store unpublication through the existing protected API; a different browser session cannot read it. This is an order status flow, not a payment checkout/redirect flow.

## Integrator seams

No model or migration is added. Shared startup/config changes are integrator-owned and now consumed from `8a42e54` (with native browser safety `837b7b0`):

- Add `V1_STOREFRONT_ENABLED=False`; when explicitly enabled require a valid configured canonical `PUBLIC_BASE_URL`. Never derive origin from Host or forwarding headers.
- Register `app.api.v1.storefront.create_router(canonical_base=settings.PUBLIC_BASE_URL, provider_dependency=app.services.storefront_publication.published_storefront_provider)`.
- Mount **only** `frontend/storefront/src` at `/storefront-assets/src`; tests, fixtures, node_modules and design artifacts must not become public static content.
- Enabled configuration without canonical origin or required packaged assets should fail configuration. Disabled startup must remain unchanged. The backend-only Docker context currently lacks frontend modules; container packaging is a remaining deployment gate.

The browser server sets the explicit test configuration before importing actual app.main and owns port 8150. Router/provider/static installation therefore uses the shared production bootstrap. It uses actual native signup/session/CSRF/catalogue/checkout APIs and the migrated database, with no test-only authentication path. Existing fixture previews at 4317/4318 remain untouched; incumbent browser regressions ran on 8151.

## Verification

The branch consumes shared authority fixes `38c3da0`, reset safety `9402390`, QA selector fix `d606325`, native browser safety `837b7b0` and shared storefront bootstrap `8a42e54`. All database work uses the dedicated `channel_operator_w2` P01 lane with full actual migrations through 0046 and the reset lease; no runtime environment file or other database is used.

- 45 Node checks pass, including exact 200 replay, uncertain reload, protected status, typed-stock-only recovery, unsafe refreshed media and same-total pagination collisions.
- 22 Chromium incumbent fixture/injected-HTTP checks pass across all three theme contracts on port 8151.
- 24 additional real Chromium checks pass on port 8150: native signup, store settings, reviewed SKU, activation, publication, policy, SSR, mobile COD, protected status/reload/unpublish, absent-capability denial, four uncertain POST failure modes and real stock rejection/recovery. Request instrumentation reports no external requests and no JavaScript errors.
- PostgreSQL provider/SSR/checkout regression result and independent review verdict are recorded in `artifacts/v1/storefront-integration/verification.md`.

Render captures include the desktop collection, mobile product/checkout/confirmation/private status, replayed COD and stock rejection. Author inspection found no clipped controls at 390px or 1365px. Existing green/type/dialog theme presentation is preserved. Fresh additional reviewer spawning previously failed with the session thread-capacity limit; the independent integrator reviews source and captures instead. No claim is made that automated browser checks replace physical-device or live-provider evidence.

Run the guarded Python tests with `PYTHONPATH=backend` and the allocated TEST_LANE/TEST_DATABASE_URL/TEST_DB_RESET variables. Browser harness: `python backend/tests/run_storefront_integration_browser.py`. Run Node checks with `npm --prefix frontend/storefront test`; incumbent browser checks with `STOREFRONT_TEST_PORT=8151 CI=1 npm --prefix frontend/storefront run test:browser` after installing locked Playwright dependencies.

Remaining gates include production registration/asset packaging, online Razorpay payment steps, provider authorization/delivery, real approved product media, seller theme persistence, large-catalogue paged SSR/sitemap/redirect work, repeated shopping after a confirmed intent and physical-device evidence. COD order creation/status/replay is the proven scope; no broader commerce launch claim is made.
