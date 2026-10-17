# Catalogue V1 preview foundation

Status: additive B10 first slice. This is a seller/preview catalogue snapshot,
not operational SKU checkout, publication, inventory reservations or B10 completion.
Every read contains `mode: "preview_foundation"` and `checkout_enabled: false`.
No HTTP route is introduced by this slice.

## Compatibility and authority

- `Business.id == Seller.id`. Products keep their existing IDs and `seller_id`.
  New `business_id` columns reference `businesses.id`; composite foreign keys
  additionally require the product to belong to that business. An additive
  `products(seller_id, id)` unique constraint supports those foreign keys.
- `commerce_orders` remains the order core. Legacy checkout, reservation,
  cancellation, payment callbacks and product inventory writes are unchanged.
- `stock_available` means units currently available, matching the existing
  `Product.stock_quantity` meaning. It is never physical/on-hand stock. `null`
  means untracked; zero means tracked and unavailable. Negative values fail.
- Pending legacy reservations already reduced `Product.stock_quantity`.
  Backfill copies available stock once; it never subtracts, releases, recreates
  or transfers reservations. Neither reservation history nor checkout changes
  can be inferred from a SKU snapshot.
- Prices are integer minor units (`129900` means INR 1,299), with strict bounds
  `0..2000000000`. Stock uses the same bounds. Booleans, numeric strings and
  fractional values are rejected. INR is the only supported currency in this
  slice; B30 must deliberately extend the contract before other currencies.

## Registration and migration

Integrator shared-file change: register `Business`/identity models first, then
`CatalogueSKU` and `CatalogueProductMapping` from `app.models.catalogue_v1`
in `app.models.__init__`. The catalogue model appends the matching additive
product tenant unique constraint to SQLAlchemy metadata, without editing the
legacy product model. Both real model modules must be loaded for ORM FK resolution.

Migration `0041_v1_catalogue` depends on `0040_v1_identity`. It creates only
`catalogue_skus`, `catalogue_product_mappings`, constraints and the product tenant
key. It performs no product/SKU data backfill, provider calls or writer cutover.

`backfill_product(db, business_id, product_id)` is an explicit, bounded service
operation after Business compatibility backfill. The caller owns commit/rollback
and authorizes the business ID before invoking any service. Storefront then
product locks match the legacy checkout lock order. Product IDs are always
queried with the authorized business ID. No service accepts tenant identity in
a write body. Transactions must end promptly after these operations.

## Backfill and review behavior

1. A legacy nonvariant product (`variants` is `null` or `[]`) with valid facts
   receives one deterministic default SKU with `options: {}`. Stock is copied
   directly, including null and zero. State becomes `default_backfilled`.
2. Any nonempty or malformed legacy variants require review. No SKU or stock is
   generated from labels, photographs, aggregate stock, or guessed combinations.
   Mapping evidence records original values and indexes. Duplicate labels remain
   distinguishable by their array indexes.
3. Invalid legacy price, stock, active flag or currency also requires review.
   Existing SKUs without a mapping cause reconciliation, never another default.
4. Replaying backfill returns the existing mapping without modifying any SKU,
   seller review, stock or fingerprint. This remains true for stale snapshots.
5. Seller review requires explicit `seller_reviewed: true`, the current legacy
   fingerprint and `expected_mapping_revision`. Mapping revision starts at 1 and
   increases once per successful review. A competing or stale edit conflicts
   instead of silently replacing seller corrections. Raw import extraction must
   remain a draft until authorized seller review.
6. Review supplies exactly one explicit SKU for each legacy variant index, with
   unique nonempty option combinations and independent reviewed prices. A tracked
   product's allocations must sum to its current available stock, including
   inactive SKUs. Untracked product stock requires every allocation to be null.
   A nonvariant keeps one default SKU with empty options. Malformed legacy arrays
   require explicit legacy correction before allocation; this slice does not
   rewrite Product variants.
7. Existing SKU IDs must all be present on later reviews. IDs from another
   product/business are unavailable. Existing options are immutable in this slice;
   changed option layouts require a later deliberate reconciliation workflow.
   New SKU IDs are assigned by the service. Omitted historical SKUs are not deleted.
8. Public serialization uses explicit field constructors, never ORM dictionaries.
   Private floor prices, credentials, source extraction, mapping evidence and
   seller notes cannot enter the public product/SKU field allowlists. Media URLs
   are sanitized. The seller mapping response is a separate private contract.

The fingerprint covers legacy public product/media data, price, available stock,
active state, variants and storefront currency. If legacy facts change, preview
readiness is `stale`. The service reports this and preserves the old snapshot for
review. It does not quietly synchronize two inventory writers.

## Frozen contracts and fixtures

Source: `backend/app/schemas/catalogue_v1.py`. Unknown fields are forbidden on
read/write models. Tenant IDs are in read envelopes and authorized service
arguments, never review bodies. Fixtures and generated JSON Schema are in
`docs/contracts/catalogue/`:

| Fixture | Consumer use |
| --- | --- |
| `nonvariant-read.json` | Default SKU with tracked available stock |
| `variants-needs-review-read.json` | Ambiguous repeated labels, zero generated SKUs |
| `variants-reviewed-read.json` | Independent reviewed SKU prices/options/stock |
| `variants-reviewed-write.json` | Explicit review/allocation request, initial SKU IDs null |
| `variants-legacy-source.json` | Synthetic legacy input corresponding to variant fixtures |
| `*-mapping.json` | Seller-only readiness, fingerprint, revision and original variant evidence |
| `product-read.schema.json` | Storefront/preview public field allowlist |
| `review-write.schema.json` | Import review request validation |
| `mapping.schema.json` | Private seller review response validation |

`serialize_preview` returns `(public_product, private_mapping)` separately.
`load_preview` performs tenant-scoped DB reads and returns the same pair. A
future public API must expose only the public object and enforce publication
authorization separately; this slice is not an anonymous publication endpoint.
Import workers should store proposed changes separately, fetch current mapping
revision/fingerprint for the seller, and submit only the approved allocation.
Reimports must never call this service with fabricated seller review authority.

## Verification evidence and remaining work

The 53 focused checks passed on 17 October 2026: 46 pure contract/planning/SQL
shape checks and 7 PostgreSQL checks using the actual Alembic chain through 0041
on the coordinator-allocated disposable database. No ORM schema recreation was
used. PostgreSQL checks verified pending reservations remain unchanged, concurrent
backfill produces one default SKU, competing seller reviews conflict, composite
tenant FK enforcement, and raw DB rejection of invalid prices/stock/currency.
The only observed warning was existing Pydantic class-config deprecation.

Database tests are opt-in (`V1_CATALOGUE_DB_TESTS=1`) and refuse any URL except the
coordinator's exact disposable catalogue database URL before connection/migration.
They import the real A10 identity model/migration. Standalone branch validation
used local-only copies of those dependency files; they are not catalogue commits.
No test used environment secrets or contacted providers.

Not yet delivered: actual SKU reservation/decrement/release writers, checkout
line SKU IDs, immutable order SKU snapshots, reservation contention/expiry tests,
legacy pending-order reconciliation at cutover, anonymous publication API,
catalogue HTTP authorization and import UI. Allocation sums are a review invariant,
not proof of safe inventory cutover. Keep SKU checkout disabled until coordinated
writer migration and reconciliation pass against migrated schema.

The Alembic downgrade is development schema teardown. Production rollback must
preserve new transactions; dropping SKU/mapping tables is not a cutover rollback.

## Integrated test lane

The integrated DB fixture uses P01 `migrated_engine`, actual Alembic head and the
shared reset lease. Configure `TEST_DATABASE_URL`, `TEST_LANE` and `TEST_DB_RESET=1`
using the literal loopback `munimjee_test_<lane>` policy. Standalone hardcoded
catalogue database/opt-in switches are superseded in integration; missing DB opt-in
skips DB checks and is not a validation pass.
