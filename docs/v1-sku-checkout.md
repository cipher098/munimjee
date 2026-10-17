# B20 SKU checkout and explicit cutover

This slice adds operational catalogue and SKU checkout APIs around the existing
`commerce_orders`, payment capture validation, expiry and order transitions. No
product/store activates automatically. No live provider or customer send is part
of implementation verification. Shipping remains the separately proposed existing
Parcel Desk link/tracking workflow, with no online courier booking.

## Interfaces and integration

Exact routes, bodies, field allowlists and consumer examples are in
`docs/contracts/catalogue-v2/README.md` and adjacent JSON/JSON Schema. Frozen v1
preview responses retain their original disabled-checkout meaning. New v2 product
responses are operational and expose only explicit public fields. They exclude
floor prices, credentials, mapping provenance, private notes and reservation
markers. Public browse returns only explicitly activated products in an active,
published store; SKU stock/prices, not Product aggregates, are authoritative.

Shared registration for the integrator:

- Register `CatalogueStorePolicy`, `CatalogueActivation`, `CatalogueCreation`,
  `SKUReservation`, `SKUPaymentAttempt` from `app.models.checkout_v1` after real
  identity/catalogue/order models.
- Include `app.api.v1.catalogue.router` in the real FastAPI application. Read actor
  comes from `app.api.v1.identity.current_actor`; mutation actor comes from the
  shared `app.api.v1.session.require_v1_mutation` (native persistent session,
  CSRF/Origin rules and current capability checks).
- Apply actual `0043_v1_auth → 0044_v1_checkout`. No fake predecessor or ORM schema
  recreation is used. Migration 0044 creates the activation/store-policy/creation,
  reservation and payment-attempt tables, composite tenant FKs and the legacy
  Product mutation and immutable SKU order snapshot triggers. It changes no
  existing product activation or stock.
- Messaging uses `is_product_activated(db,business_id,product_id)` before legacy
  facts. True means use authoritative SKU facts or handoff, even with checkout
  disabled. Channel lane owns all resolution/send-path guards.

## Cutover invariants

Available units have the same meaning before and after cutover. A reviewed snapshot
copies currently available stock exactly once; pending legacy reservations have
already reduced it. Activation requires a current reviewed mapping revision and
fingerprint, unique coherent option combinations, reconciled allocations, and an
active reviewed SKU. It rejects orders with a tracked legacy line for this product
that can still cancel/release or whose payment is pending/review-required. Resolve
those orders using their original writer and review the resulting current stock;
do not backfill/re-reserve them as SKU orders. This deliberately conservative gate
can require operational review of older unsettled orders.

Reviewed native creates are private inactive Product drafts. Explicit activation
enables that product and writes an actor/time/fingerprint/revision activation
record. Publication of the Storefront and its independent checkout policy are
separate. Unactivated products may continue the existing legacy workflow. Activated
products are excluded from old public aggregate readers, reject old checkout and
legacy Product PATCH, and have a PostgreSQL trigger forbidding old stock, listed
price or variant mutations. This is a one-way authority decision in this slice;
no automatic fallback or API to delete the activation exists.

Storefront locks serialize checkout/idempotency/customer creation, activation,
catalogue edits and policy changes. Product/mapping/SKU locks use stable UUID order.
Existing order callbacks already lock their order; release then locks product,
mapping, SKU and reservation rows in stable order and never acquires a storefront
lock after an order lock. No remote request occurs while holding stock locks.

SKU checkout takes only SKU IDs/quantities plus existing customer/address/payment
choices. It rejects duplicate lines, foreign/inactive/unactivated SKUs, disabled
policy and insufficient stock. It resolves prices/currency/name/options on the
server, enforces per-product quantity and order total bounds, snapshots them into
the immutable order line JSON and decrements available SKU stock once. A durable
tenant-bound reservation ledger records tracked/untracked quantity per order/SKU.
Product aggregate stock stays frozen. Client price, tenant and stock fields fail
strict extra-field validation. Explicitly untracked null and tracked zero differ.
The database snapshot guard also rejects removal/replacement of the private engine
marker or all items, not only changes to individual price/options fields. The final
SKU stock lock refreshes an initially cached SKU, including a payment callback
restoring stock between candidate lookup and Product locking.

Existing `release_stock` dispatches through the private immutable `sku.v1` marker;
legacy orders retain the old writer. Cancellation/expiry restores a tracked SKU
once under the shared order `stock_released` guard and ledger reconciliation. It
does not restore an intentionally untracked current SKU. Unknown/mixed engines or
ledger/snapshot mismatches fail closed for review. Reservation/release and reviewed
stock/price edits advance the product mapping revision, so stale seller pages
cannot overwrite stock after an intervening checkout. Option identity changes or
SKU deletion require a later explicit reconciliation workflow.

## Payment uncertainty

SKU payment creation uses the existing Razorpay transport and encrypted per-order
credential snapshot. Before its only provider POST, it commits a durable
`requesting` attempt; a crash or lost response leaves a visible reconciliation
state. Retries never POST again while requesting/unknown. Verified response ID,
amount, currency and local-order receipt are persisted as ready. The order lock
is reacquired after the request; cancellation/expiry during the request remains
cancelled/released, while the provider ID is retained for late callback review.

An authorized order operator can associate a known provider order through exact
`GET /v1/orders/{id}` and verify local receipt, integer amount and currency before
association. This method/response is documented in the official
[Razorpay fetch-order API](https://razorpay.com/docs/api/orders/fetch-with-id/).
No receipt search or assumed provider POST idempotence is used. Association does
not mark payment paid. Existing provider capture/amount/currency/signature checks
and `/reconcile-payment` remain authority. Late captured payments after release
remain review-required and never deduct or release stock twice. The old legacy
payment creation path is otherwise preserved; this guard applies to SKU orders
through both the new routes and the existing payment-start URL.

## Validation and limits

Tests use P01's held disposable-schema reset lease and actual Alembic migrations
on the coordinator's separate PostgreSQL 16 checkout lane. HTTP tests mount the
actual feature router with real DB sessions, native persistent sessions and shared
CSRF dependency. Provider methods are replaced with synthetic transports; no live
payment/provider calls or customer messages are evidence here. The test harness
blocks outbound sockets except that exact validated loopback database.

Checks cover stock contention; same-key replay/changed-body conflicts; independent
variant prices/options; foreign SKU and forged tenant ledger rejection; tracked
zero/untracked distinction; once-only competing cancellation; expiry/late capture;
stale inventory revision; blocked pending legacy cutover and fresh allocation after
legacy release; old Product DB guard; native role/tenant/session/CSRF/Origin errors;
approved draft versus public activation; protected order status; malicious client
price/stock inputs; and uncertain/concurrent provider creation with exact mismatch
reconciliation. Existing commerce/catalogue/Razorpay regression suites run as well.
Final counts and source SHA are handed to the integrator after the focused run.

Final local run on 18 October 2026: **137 passed, 0 skipped, 0 failed in 58.81s**
across the new domain/API tests and existing catalogue, commerce, Razorpay and
catalogue-boundary regression files. Raw output is preserved in
`artifacts/v1/B20/2026-10-18-checkout-tests.txt`. Existing Pydantic/HTTPX deprecation
warnings remain. Syntax compilation and `git diff --check` also passed. This is
backend/migrated-schema/HTTP evidence, not browser or live-provider acceptance.

Still external: storefront browser journey/physical camera proof belongs to its
consumer lanes; actual Razorpay test-account canary, production authorization,
international checkout, returns/refunds and transaction-preserving rollback
rehearsal remain separate gates. Disabling store checkout stops new SKU orders
without switching inventory writers. Alembic downgrade drops additive tables and
is development teardown, not a production rollback preserving post-cutover orders.
