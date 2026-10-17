# Reviewed import approval → private catalogue draft

The native import workspace uses the shared V1 session/client/CSRF contract.
Both endpoints are relative to
`/api/v1/businesses/{business_id}/imports/candidates/{candidate_id}`:

- GET `/catalogue-preview`: current candidate revision, effective facts, issues,
  all option combinations, and an existing receipt when one has already created
  a product. Requires `catalogue.read`. A proposed quantity is null for multiple
  SKUs; the seller must allocate the confirmed total. Unknown source quantities
  remain null and block creation; null does not mean untracked inventory.
- POST `/catalogue-draft`: `ImportCatalogueWrite` (example in this directory).
  Requires current `catalogue.write`, native mutation/CSRF and the default-off
  `V1_IMPORT_BRIDGE_ENABLED` flag. Explicitly confirm all five factual fields and
  allocate every combination once, with quantities summing to the confirmed total.
  Use the existing source review edit endpoint to resolve facts before this POST.
  Approval of a pending/review candidate and creation are atomic. An already
  approved candidate can create a private draft without a second source revision.

HTTP201 creates an `import-catalogue.v1` receipt; HTTP200 replays the exact key and
body. Store the pending exact command before submitting and preserve it across
unknown responses; the server never accepts browser title/price/product IDs.
HTTP409 means stale revision, unsupported storefront state, a reused conflicting
key, or an already-linked source. The `candidate_already_created` detail includes
an existing product ID for review; changing a source or key cannot create another
product. HTTP422 asks the seller to resolve unsupported facts/allocation.

The response `catalogue_url` opens the native catalogue workspace. It does not
publish the store, activate the product, enable checkout or reserve stock.
`photo_urls` are optional images explicitly reviewed by the seller; a source page,
private uploaded evidence or arbitrary extraction is never inferred as a photo.
Only exact INR minor units are supported; no currency conversion is performed.

Source schemas and fixtures are frozen here for UI consumers. Actual migrated
PG16 service/HTTP security tests are in `backend/tests/test_import_catalogue.py`;
a full integrated native import workspace browser journey remains a later gate.
