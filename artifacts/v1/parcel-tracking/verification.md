# Synthetic local Parcel Desk verification

Two real local services: actual Munimjee main/native auth/API with migrated PG16,
and separate Parcel Desk Worker.fetch + SQLite on8155. P01 owns the exclusive
parcel_w3 database/reset lease for the full browser/service lifetime. Python
production HTTP remains blocked; the approved test-only Node bridge permits only
exact127.0.0.1:8155/integration/v1 with no redirects. Carrier fetch is hard-failed.
This is a local transport seam, not deployed or provider-HTTP proof.

- 20 actual PG16/two-service tests plus5 actual application startup checks pass.
  Covers tenant/capability/CSRF, membership/session revocation during actual row
  lock and HTTP waits, composite actor FK/checks/append-only history, concurrent
  parcel uniqueness, durable crash recovery and lost response replay, partial and
  regressing history, terminal conflict, consent-independent tracking, milestone
  dedupe and current configuration fences. Real outbox sender tests revoke
  connector/configuration/consent during approval refresh: zero synthetic sends.
  Accepted and uncertain synthetic submits are each invoked once; uncertainty is
  not retried. Registry removal during remote enrollment preserves remote
  uncertainty as review_required.
- 10 separate Node SQLite/HMAC/queue checks pass, including restart-persistent
  command/nonce identities, tampered signatures/body/scopes/tenant, unowned legacy
  duplicate denial and private event-field projection.
- 17 actual Chromium scenarios pass through production router registration:
  native signup, reviewed SKU activation/published COD order, View order → parcel
  page, real local ZXing decoding of synthetic canvas camera frames, ambiguous
  courier manual choice, explicit label check before enrollment, real two-service
  link and refreshed history, no-consent tracking, unchanged payment/dispatch,
  mobile/reload, camera-denied manual entry, postcommit response loss/reload/same
  command, wrong-command ACK retention, typed invalid-preview-only reset, general409 same-command recovery, and real same-user login replacement /
  logout-revoked-session fences that clear customer, history, raw label and saved
  private intent on focus or401. All browser requests remained same-origin;
  fixture controls used only the reserved loopback connector.
- Detector ran once on authored HTML/CSS/mainJS/scanner: `[]`.

Required inspected captures: desktop-confirm-label.png (1365 wide),
mobile-tracking-history.png, mobile-manual-linked.png and mobile-session-ended.png (390 wide). They use
actual persisted synthetic records. The camera uses synthetic frames, not a
physical device. No real provider/template/customer send or courier lookup ran.

A fresh GPT-6.1 Sol/high finish-review spawn was rejected with `agent thread limit
reached`; no retry loop. Integrator independently reviews source and captures.
Documentation fallback compared the ordinary extension against commerce.css,
catalogue_workspace.html/css, parcel_tracking.html/css and these captures: no
incumbent design-system files were rewritten. Palette retains green #2e5141,
ink #27302d, paper #f6f7f3; existing system type, white panels, quiet rules and
44px controls continue. No new visual world or theme persistence is claimed.
