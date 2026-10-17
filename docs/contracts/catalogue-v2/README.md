# Operational catalogue.v2 and checkout API

This is a distinct contract from frozen `catalogue.v1` preview responses. A v2
product has `mode: "operational"`, `readiness: "active"` and a store-policy-derived
`checkout_enabled` boolean. A v1 preview always has checkout disabled. Storefronts
must select a specific `sku_id`; labels or client prices never authorize checkout.
Amounts are integer INR minor units. `stock_available: null` explicitly means
untracked; draft extraction with unknown inventory is not permission to write null.

## Public routes

| Method/path | Response/use |
| --- | --- |
| `GET /api/v1/storefronts/{slug}` | Published store branding/policies/categories, payment options, checkout policy |
| `GET …/products?q=&category_id=&page=1&page_size=24` | `{items: ProductRead[],total,page,page_size}`; activated products only |
| `GET …/products/{product_id}` | `product-read.json` shape; absent/foreign/unactivated/unpublished is 404 |
| `POST …/checkout` | `checkout-write.json`; 201 new order, 200 same-key replay |
| `GET …/orders/{order_id}` | Protected order response; `Authorization: Bearer <order access_token>` |
| `POST …/orders/{order_id}/razorpay` | Same order capability; provider order parameters, never captured-payment authority |
| `POST …/orders/{order_id}/razorpay/verify` | Existing Razorpay ID/signature fields; provider capture validation remains authoritative |

The checkout response contains `contract_version: "order.v1"`, `id`, `number`,
`access_token`, customer/address, totals (`subtotal`, `shipping_fee`, `total`,
`currency`), payment/fulfilment states and immutable items including `product_id`,
`sku_id`, `name`, `options`, `currency`, `quantity`, `unit_price`, `line_total` and
`photo_url`. Internal reservation/engine markers are never exposed. Reuse the
same idempotency UUID and body after an uncertain checkout response; changed-body
replay conflicts. Do not create a new payment order after an uncertain creation.

Public products are filtered by active Business/Seller, published Storefront,
explicit product activation and Product.active. Inactive SKUs are omitted. Checkout
policy defaults off and does not activate products. Orders/status/payment retain
their scoped capability behavior if a store is later unpublished.

## Authenticated seller/import approval routes

Prefix `/api/v1/businesses/{business_id}/catalogue`. Reads require current
`catalogue.read`; mutations require `catalogue.write`, native-session mutation
protection and current membership. Storefront settings writes use `business.write`.
Native browser mutations send session-bound CSRF cookie/header and allowed Origin;
bearer APIs use the shared authenticated mutation dependency.

| Method/path | Body/result |
| --- | --- |
| `GET/PUT /storefront` | Existing `StoreInput`; creates/updates actual branding/policies/publication settings |
| `GET/PUT /checkout-policy` | `{checkout_enabled:boolean}`; store must be configured |
| `GET /products` | Paginated seller catalogue records; legacy unmapped records say `needs_backfill` |
| `POST /products` | `product-create.json`; idempotent approved-create bridge, 201 or replay 200 |
| `GET /products/{id}` | Seller record described below |
| `POST /products/{id}/backfill` | Explicit safe legacy snapshot; no implicit approval/activation |
| `PUT /products/{id}/review` | Frozen v1 reviewed allocation with fingerprint/revision, before activation only |
| `POST /products/{id}/activate` | `activation-write.schema.json`; explicit reviewed reconciliation gate |
| `PUT /products/{id}/skus` | `sku-edit.schema.json`; all current SKU IDs, current revision, reviewed facts |
| `PATCH /products/{id}` | Reviewed metadata plus current revision; no legacy stock/price fields |

Seller records contain `product` (v1 preview or v2 operational), `inventory_mode`
(`legacy` or `sku`), `mapping_revision`, current `legacy_fingerprint`, review
`issues`, and all seller SKU writes including their `legacy_variant_index`.
Use that record to construct review/activation/edit requests. Never synthesize a
revision or fingerprint from source media. Existing options/IDs cannot be changed
by a stock edit. Every reservation/release advances the mapping revision, preventing
an old inventory page from overwriting intervening orders.

Approved-create requires explicit `seller_reviewed: true`, a stable idempotency key,
reviewed fields and explicit stock semantics. It creates an inactive private Product
plus reviewed SKU facts. It does not activate, publish the store, enable checkout,
infer private floor prices or send messages. Source provenance/review/audit remains
in the import workflow; unapproved drafts cannot call this bridge as approval.
`create_reviewed_product(db,business_id,payload)` is the internal equivalent for a
trusted authorized import approval transaction; its caller must perform the same
actor/capability checks. Reimports use revision-checked approved edits and must not
silently reset seller corrections or call creation with a new idempotency key.

Activation requires current reviewed allocation/fingerprint/revision and no
reversible/uncertain legacy reservation. It never transfers or subtracts pending
legacy reservations. Activation establishes permanent SKU authority for that
product; disabling checkout does not restore a legacy writer. Legacy product
mutations/checkouts/readers fail closed or exclude activated products. A store can
retain other unactivated products on the legacy workflow during migration.

Order management prefix `/api/v1/businesses/{business_id}/orders` uses orders.read
for list/detail and orders.write for `/transition`, `/collect-cod`,
`/reconcile-gateway-order` and `/reconcile-payment`. Exact gateway-order
reconciliation body is `{gateway_order_id:"order_…"}`; it associates a verified
provider order, not a paid status. Payment reconciliation uses captured provider
payment evidence. No customer cancellation/refund authority is added by these APIs.

Errors use FastAPI's standard `detail`: 401 invalid/missing actor, 403 capability or
CSRF/origin failure, 404 inaccessible resource, 409 stale facts/activation/stock/
idempotency/uncertain-payment conflict, 422 invalid strict contract fields. Client
code must preserve user edits and refetch current facts on 409, never silently
change selected SKU or retry payment creation with a fresh identity.
