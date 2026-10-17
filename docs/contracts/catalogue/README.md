# catalogue.v1 fixtures

These synthetic contracts describe an additive **preview foundation**.
`checkout_enabled` is always false. They do not advertise ready SKU checkout or
inventory reservation support.

Use `product-read.schema.json` for storefront read validation,
`review-write.schema.json` for seller-approved allocations, and
`mapping.schema.json` only for authenticated seller review. Concrete examples
cover nonvariants, repeated ambiguous labels, and explicit reviewed allocations.

Business IDs equal legacy Seller IDs. Prices use minor units; currency is INR.
`stock_available` is available-to-purchase snapshot stock; null means untracked.
Tracked allocations sum to the current legacy aggregate exactly once. Never
subtract pending reservations during import/backfill.

Review bodies carry the current `expected_legacy_fingerprint` and
`expected_mapping_revision`, plus explicit `seller_reviewed: true`. The example
write creates initial reviewed SKUs with null `sku_id`; subsequent updates must
include the service-assigned existing IDs and current revision. Raw extraction
does not authorize this write. Preserve seller corrections on reimport.

See `docs/v1-catalogue.md` and `backend/app/schemas/catalogue_v1.py` for exact scope,
field allowlists, idempotence, limitations, and migration/registration instructions.
