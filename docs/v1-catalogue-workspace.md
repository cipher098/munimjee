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

Before sending a product draft, the page persists and reads back its exact body/key in `sessionStorage` under `munimjee.v1.catalogue-draft:{user_id}:{business_id}`. The envelope also binds a SHA-256 fingerprint of the native session's CSRF token; no raw token is stored. After an uncertain response or reload, the page displays the saved human-readable facts and an explicit **Retry saved draft** button. It never posts automatically, and another draft cannot replace an unresolved command. The retry rechecks current native identity, session and write capability, then sends the same body/key. A successful response must contain a valid product record for the same business before recovery state clears. A malformed success response remains uncertain. A definite first-attempt client rejection allows correction; a client error after an earlier uncertain attempt keeps recovery pending.

Malformed, expired or changed stored state blocks new draft commands and directs the seller to review existing products. Unavailable persistence sends no new draft POST. Different users/businesses/sessions cannot reuse or reveal the pending facts. Shared native cleanup removes this reserved prefix on login/signup/invitation acceptance, logout/logout-all and 401; the page also clears/withholds recovery on identity mismatch or 401. Recovery is limited to the original native browser session. After signing in again, review existing products before creating a replacement for an earlier uncertain save. Public customer checkout storage has a separate lifecycle and is not modified here.

Activation and stock edits use server revisions/fingerprints; there is no automatic conflict retry with a refreshed revision. Product and order detail requests discard late responses after changing or closing the detail. Pagination discards older responses.

The **Open storefront** link is hidden unless the private storefront API supplies `public_storefront_url` for a published store. The UI accepts the exact `/stores/{slug}` path over HTTPS, or HTTP on the current origin for local previews, and rejects credentials, query strings and fragments. The integration owner supplies the configured canonical URL and gates it behind the default-off storefront feature. This UI does not derive the public origin from the request Host.

## Verification

The new tests use P01 `migrated_database`/`migrated_engine`: numeric-loopback disposable database name `munimjee_test_<TEST_LANE>`, `TEST_DB_RESET=1`, a held reset lease, and the actual Alembic chain. Providers are blocked by the synthetic test configuration. The integrated application mounts this router in actual `app.main`; its central browser entry point adds no duplicate registration. The isolated feature-branch test entry point supplies the equivalent catalogue/workspace registrations until those central composition commits are consumed. No real customer messages or payments are used.

Run backend checks with the guarded test lane configured:

```sh
python -m pytest tests/test_catalogue_workspace.py -q
python -m tests.run_catalogue_workspace_browser
```

The browser runner expects the storefront's locked Playwright dependency in `frontend/storefront/node_modules`. The check covers real native signup, private draft save with a lost response and idempotent recovery, explicit publication/activation/checkout gates, authoritative public SKU data, a real COD order and cancellation stock release, sellout rejection, stale inventory edit/review reset, viewer restrictions, DOM text safety and 390px layout. Screenshots are saved in `artifacts/v1/catalogue-workspace/`.

The customer storefront UI remains the remote storefront workstream. Public product/checkout API success here is not a customer-browser checkout certification or production release.

Verified locally on the guarded PostgreSQL 16 checkout lane: **3 backend checks passed** and **66 recorded real-browser checks passed**. The expanded recovery cases cover post-commit response loss across reload, exact-key retry with one product, malformed success responses, changed/corrupt/expired storage, persistence denial before POST, hidden-form tampering, session replacement, foreign user/business isolation and 401 cleanup. Public-link allow/deny cases explicitly inject the optional API field at the browser transport boundary; the real feature-off API leaves the link hidden. The activation conflict check also proves that a stale draft cannot activate and its review checkbox resets after current facts reload. Impeccable's mechanical detector returned no findings. The browser run uses synthetic identities and blocks non-local browser requests.

## Visual system evidence

This is an extension of the incumbent seller workspace, not a new visual identity. `commerce.css` remains unchanged. The rendered desktop and 390px captures preserve its green actions, ink text, paper background, platform sans typography, bordered white panels, and 34/25/21/16px heading hierarchy. Native disclosure controls collapse completed settings and unused draft forms; labels and controls keep 44px touch targets. Scoped secondary text uses the existing darker navigation ink for legibility. No new design-system file or palette was introduced. The synthetic markup text in screenshots is an intentional DOM escaping test, not production product copy.
