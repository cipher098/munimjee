# Native catalogue workspace

The seller page at `/v1/businesses/{business_id}/catalogue` uses the existing protected catalogue.v2 and order APIs. Its router is `app.api.v1.catalogue_workspace.router`; the integration owner registers it in `app.main` and connects the per-business setup checklist links. It uses `commerce.css` and the shared `v1_client.js` native session/CSRF transport. It adds no migration, seller-token shortcut or external provider integration.

## Seller actions

- Save storefront name/address, contact details, shipping fee and policies. Cash on delivery and publication are explicit checkboxes, initially off in a fresh workspace. A storefront address cannot change after orders exist; API conflicts are displayed.
- Enter a product and one or more option combinations using ordinary labeled fields. Each combination has an INR price, available quantity or explicit untracked quantity, and availability switch. Prices convert from rupees to integer minor units without floating-point rounding. The seller must check the review box before saving a private draft. The API enforces option uniqueness and consistent dimensions/tracking.
- Open a reviewed draft and explicitly confirm activation. The server receives the revision and fingerprint from the displayed record, revalidates reconciliation and pending legacy reservations, and permanently switches product authority. Publication and store checkout policy remain separate controls. Existing ambiguous legacy allocations remain pending, with an explanation and working business-setup link; this slice does not invent an allocation.
- Explicitly enable checkout for activated products. A new draft or successful activation never silently checks this control.
- For activated products, review and replace SKU prices, availability and available quantities using the current mapping revision. A stale write reloads the current record and clears the review checkbox; the seller reviews again before resubmitting.
- Read tenant-scoped orders and immutable line snapshots. Users with `orders.write` can confirm, pack, ship with optional manual tracking, deliver or cancel when the existing server state machine permits. Cancelling asks for confirmation and releases stock through the existing inventory engine. Online settlement/refund authority remains server controlled. Parcel Desk scanning is a separate integration and is not claimed here.

Missing or revoked native sessions do not gain access through this page. Viewer/staff catalogue controls are disabled and the API independently rejects unauthorized mutations. Server-rendered HTML is an authenticated shell; private facts come from authorized APIs, are not embedded in the HTML, and use `textContent` when rendered.

## Retry and race handling

A draft keeps its idempotency key and exact payload after a transport/server failure. Retrying unchanged recovers a committed draft if only its response was lost. Changing facts while an earlier save is unconfirmed is blocked until the seller retries unchanged or reloads/checks the catalogue. Definite client errors allow correction. Activation and stock edits use server revisions/fingerprints; there is no automatic conflict retry with a refreshed revision. Product and order detail requests discard late responses after changing or closing the detail. Pagination discards older responses.

## Verification

The new tests use P01 `migrated_database`/`migrated_engine`: numeric-loopback disposable database name `munimjee_test_<TEST_LANE>`, `TEST_DB_RESET=1`, a held reset lease, and the actual Alembic chain. Providers are blocked by the synthetic test configuration. Browser tests run the real local application with only the new router registrations added by the test entry point. No real customer messages or payments are used.

Run backend checks with the guarded test lane configured:

```sh
python -m pytest tests/test_catalogue_workspace.py -q
python -m tests.run_catalogue_workspace_browser
```

The browser runner expects the storefront's locked Playwright dependency in `frontend/storefront/node_modules`. The check covers real native signup, private draft save with a lost response and idempotent recovery, explicit publication/activation/checkout gates, authoritative public SKU data, a real COD order and cancellation stock release, sellout rejection, stale inventory edit/review reset, viewer restrictions, DOM text safety and 390px layout. Screenshots are saved in `artifacts/v1/catalogue-workspace/`.

The customer storefront UI remains the remote storefront workstream. Public product/checkout API success here is not a customer-browser checkout certification or production release.

Verified locally on the guarded PostgreSQL 16 checkout lane: **3 backend checks passed** and **37 recorded real-browser checks passed**. The activation conflict check also proves that a stale draft cannot activate and its review checkbox resets after current facts reload. Impeccable's mechanical detector returned no findings. The browser run uses synthetic identities and blocks non-local browser requests.

## Visual system evidence

This is an extension of the incumbent seller workspace, not a new visual identity. `commerce.css` remains unchanged. The rendered desktop and 390px captures preserve its green actions, ink text, paper background, platform sans typography, bordered white panels, and 34/25/21/16px heading hierarchy. Native disclosure controls collapse completed settings and unused draft forms; labels and controls keep 44px touch targets. Scoped secondary text uses the existing darker navigation ink for legibility. No new design-system file or palette was introduced. The synthetic markup text in screenshots is an intentional DOM escaping test, not production product copy.
