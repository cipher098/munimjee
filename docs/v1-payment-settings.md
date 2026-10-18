# Native payment setup

The owner or manager opens `/v1/businesses/{business_id}/payments` using the native V1 session. The page uses the existing protected Razorpay configuration API. Staff and viewers receive access guidance and never fetch configuration. Configuration is local: saving does not call Razorpay or verify a connection. `V1_PUBLIC_PAYMENTS_ENABLED`, storefront approval and checkout policy remain independent gates. A real gateway canary is still required before live release.

## Direction contract

THESIS: Put the current account beside a deliberate credential form, with clear separation between a saved setting and a verified connection.

OWN-WORLD: Extend the incumbent commerce.css paper, green, system type, restrained rules, native fields and spacious section layout. Preserve existing design files and tokens.

STORY: A seller checks the current public account fields, enters only the secrets they intend to replace, saves, and sees the confirmed configuration or an explicit uncertain-save recovery state.

FIRST VIEWPORT: Business navigation and page title lead into a two-column account summary; the credential editor follows in the same section structure. Mobile stacks the same reading order with full-width actions.

FORM: Operate extension of the existing native seller workspace; no new identity or composition tournament. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## HTTP contract

GET and PUT `/api/v1/businesses/{business_id}/payments/razorpay` require current `business.write` access. PUT requires native identity, CSRF/trusted Origin, rechecks authority after the Seller lock, and uses the shared final mutation guard before transaction commit. Native writes flush without an internal commit. Legacy `/commerce/razorpay` keeps its existing payload and default commit/provider-verification behavior.

Read allowlist: `configured`, `enabled`, `mode`, `key_id`, `webhook_url`, `encryption_ready`, `configuration_revision`, `connection_verification`. Both responses are `Cache-Control: no-store`; secrets, encrypted credentials, customer/order bearers and session tokens are never returned. `connection_verification` is always `not_performed` here.

Write allowlist: `key_id`, optional `key_secret`, optional `webhook_secret`, `mode`, `enabled`, optional `expected_revision`. The UI always sends `expected_revision`; omission remains compatible for existing native callers. Unknown fields are rejected. Secret validation errors use a generic message and never echo input.

The revision is a domain- and business-bound server HMAC over the current key ID, mode, enabled flag and exact stored encrypted credentials. It includes a deterministic absent-account state. It does not decrypt secrets and is not an authentication capability. Changes to encryption ciphertext invalidate older commands even when the replacement plaintext is identical. A no-op may retain the revision. Secret-key rotation also changes the revision and requires refresh.

The Seller lock serializes configuration writes. A fresh scalar revision is compared before mutation. Only that mismatch returns typed `409 gateway_config_stale`. The response's safe fields and revision come from one fresh snapshot while the lock remains held. Competing changed writes with one expected revision have one winner; a delayed older conditional request cannot overwrite its replacement. Pending online orders retain the existing credential-rotation conflict.

## Unknown saves and privacy

Secret fields are masked, never backfilled, cleared after submission, and never stored or logged by this feature. Browser memory briefly holds the outgoing body. There is no automatic credential retry.

Before PUT, sessionStorage must accept and read back a nonsecret marker under `munimjee.v1.gateway-intent:{user_id}:{business_id}`. Its exact fields are version, user/business IDs, SHA-256 of the current session CSRF token, creation time, expected revision, intended public key ID/mode/enabled, and sending/uncertain state. The marker contains no secret, JWT, raw CSRF token or request body. It expires after seven days. Invalid, expired or different-session contents are withheld and require an explicit fresh review. Storage failure prevents dispatch.

A lost response, timeout, malformed success or untyped error remains uncertain. Reload never retries. GET shows current safe settings but cannot prove whether a secret change saved. The seller must explicitly choose replacement, re-enter both secrets, confirm review, and submit against the latest revision. This is a new conditional replacement, not a replay or receipt claim. Confirmed safe 200 clears recovery. Typed stale-revision rejection requires refresh. Identity changes, logout and 401 clear private markers through the shared client; the page also erases private DOM and ends the session context. Focus/visibility and all asynchronous results recheck native identity/capability before revealing or saving data.

## Integration seams

Register `app.api.v1.payment_settings.router` in main and add a per-business Payments navigation action. Include `payment_settings.html`, `.js`, `.css` in the existing static runtime package. The test server uses actual `app.main` and adds only this new page router if the shared registration is absent; all native configuration and identity APIs are the actual mounted routes. No DDL, new account table or provider adapter is introduced.

## Evidence

The owned tests use P01's reset lease and actual Alembic migrations on the exclusive `payment_w3` PostgreSQL16 lane. Browser screenshots are test evidence, not shipping assets. Synthetic credential values are used throughout; the browser server forbids every provider request and checks its counter remains zero. Configuration/browser proof does not establish live credential validity, webhook delivery or a paid transaction.

Focused actual PostgreSQL16 results: 61 passed across payment-settings and checkout-session API tests, plus one new pending-online-order rotation-conflict test passed. Chromium passed 34 real native UI/API checks, including commit-then-drop/reload/manual replacement, malformed success, stale revision, delayed session/configuration responses after identity closure, session storage denial, manager revocation and staff denial. JavaScript syntax and Python compilation passed. Six shared native-client behavior checks passed. Fourteen legacy Razorpay configuration/checkout regressions passed; their outbound transport is synthetic.

The finish-review agent could not start (`agent thread limit reached`); an independent integrator source/render review is requested and will be recorded at integration. The documenter role was performed inline after reading its documenter reference because agent capacity was unavailable. No design-system files were changed: commerce.css tokens, button/input/nav/panel patterns, system type and responsive stacking were compared with the built page and captures. No shipping raster assets were added. Pre-existing commerce.css small table headers are outside this form's scope and were not canonized or changed.
