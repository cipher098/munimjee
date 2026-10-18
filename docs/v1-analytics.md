# Seller purchase analytics

Frozen contract: `seller-analytics.v1`. This dashboard reads canonical `commerce_orders` only. It does not merge legacy Instagram orders, screenshots, `transactions`, customers or channel identities. It performs no writes, provider calls or payment decisions. No migration is introduced.

## Definitions and limits

The date range is a UTC **order-created cohort**, from inclusive to exclusive. Default: the last30 UTC calendar dates including today; maximum366 dates. All metrics use current states of the orders placed in that range, not payment/settlement events occurring within it. Payment timestamps are not available. Status/method filters affect the entire cohort, aggregates, trend and order rows.

- Placed orders/value includes unpaid, cancelled and expired orders; value includes shipping.
- Online paid requires Razorpay method, current `paid` state and a persisted gateway payment association from the captured-payment authority. It is distinct from COD.
- COD collected requires COD method and current `collected` state.
- Payment-review count includes current `review_required`. Its captured-review amount additionally requires Razorpay and the persisted payment association. It is not a completed refund.
- Cancellation is the union of cancelled fulfillment/payment states, counted once per order. Expiry uses current expired payment state. These categories may overlap and are not deducted from the payment measures.
- Every amount is an exact nonnegative integer **string in minor units**, grouped by currency. There is no cross-currency total, conversion, fee deduction, net revenue or accounting claim.
- Default exclusion covers only known gateway test orders with their own stored credential-snapshot mode `test`. Live snapshot mode is separately classified; COD/uninitialized online orders lack an immutable test marker and remain explicitly unclassified. Current account settings never infer historical mode. Full test exclusion remains an unresolved requirement.
- Visits, product views, enquiries, checkout starts, conversion, attribution, completed refunds, fees, net revenue and settlement-period cashflow are unavailable (`null`), not zero. A canonical event ledger, test provenance, payment/refund timestamps and refund facts are separate follow-up contracts.

No credential snapshot, provider ID, customer field, address, note or order item is materialized in an analytics result. SQL reads only safe order scalars and derives a test-mode classification inside PostgreSQL. One statement supplies the aggregate/daily/page projections from one MVCC snapshot. Native identity/current analytics.read is checked before and after the read; the page uses current native business access and session/response ordering fences.

## API and ownership

GET `/api/v1/businesses/{business_id}/analytics`: `from_date`, `to_date` (YYYY-MM-DD), optional `payment_status`, `fulfillment_status`, `payment_method`, `include_gateway_test=false`, `page=1`, `page_size=25` (maximum50; maximum page1000). Unknown query fields are rejected. Native `analytics.read` required; no-store/no-referrer. Page `/v1/businesses/{business_id}/analytics` uses native business.read and shows access guidance if the actor lacks analytics.read. Staff currently lacks analytics.read; owner/manager/viewer have it.

Owner files: schemas/services/API `analytics_v1.py`, static `analytics_v1.{html,js,css}`, own tests/docs/fixtures. Integrator owns actualmain registration, navigation, shared client and static packaging. Port8163, exclusive P01 payment_w3 lane; all provider transports forbidden. No production provider or database action is authorized.

## Direction contract

THESIS: Explain the value of customer orders with exact source definitions, then let a seller inspect the filtered purchases behind it.

OWN-WORLD: Extend commerce.css paper/ink/green, system typography, plain panels, labeled native controls and familiar seller tables. No design-system replacement.

STORY: Choose an order-created period and current-state filters, compare recorded online/COD/review totals separately, inspect daily placement and recent orders, and continue in the existing order workspace.

FIRST VIEWPORT: Business heading and order-workspace link, date/status filters, then placed/current-payment measures with the UTC cohort label. The currency breakdown and order table continue below; mobile stacks controls and scrolls tables within their containers.

FORM: Operate extension of incumbent native seller workspace. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Local validation and unresolved release scope

Focused P01 PostgreSQL16/contract suite:22 passed (14 actual migrated-database cases,8 pure contract cases), with actual0050 chain and no metadata create_all. Includes UTC offset/midnight boundaries, current-state overlaps, mixed currencies, test-mode exclusions, null/empty capture associations, exact bigint sums, stable pagination, tenant/role/cookie isolation, and final-read discard after session/role revocation.

Mounted browser:21 checks use actual app.main native identity/catalogue/order APIs plus the new analytics router, which the owned test server mounts only if main does not yet register it. The journey creates and activates a reviewed SKU, places/replays COD orders, performs actual fulfillment/collection/cancellation, and verifies the dashboard. It also covers filters, empty/error/malformed responses, out-of-order queries, viewer/staff boundaries, revocation, native-session replacement and late results after logout. Three Node checks cover exact formatting beyond Number precision and read-contract rejection. Provider calls and external browser requests remain zero. This proves no real gateway payment or deployment.

The detector ran once and reported11px text through linked styles; the owned nav, table headers and hints were raised to12px, preserving the incumbent palette/type. Desktop1440/mobile390 were inspected together. The fresh finish-review agent could not start (`agent thread limit reached`); an independent integrator source/render verdict is requested before handoff. The documentation comparison runs inline using the shipped documenter references: ordinary extension, no DESIGN/system-file changes, no shipping raster assets. Existing unrelated table typography is not changed or canonized.

Follow-up data requirements remain open: complete immutable test/demo provenance including COD and pre-gateway orders; visits/product views/enquiries/checkout-start event identity and deduplication; source/referral attribution and conversion denominators; payment/refund event timestamps, amounts, fees and completed refund reconciliation; explicit policy for legacy conversation-order reconciliation. This bounded dashboard does not satisfy those missing V10 sources by inference. The tenant/date query has bounded period/page sizes but no new index; high-volume seller performance needs representative-load evidence before expansion.
