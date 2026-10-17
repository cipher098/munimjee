# Catalogue workspace verification — 2026-10-18

Source: new native workspace router/static files, existing catalogue.v2 APIs, native auth dependencies including the shared nullable-response fix ca7233c. PostgreSQL 16 disposable checkout lane; P01 reset lease and actual Alembic migrations through 0044. No live provider calls, customer sends, or payments.

Observed results:

- `python -m pytest backend/tests/test_catalogue_workspace.py -q`: 3 passed, 1 existing Pydantic deprecation warning (3.59s).
- `python -m tests.run_catalogue_workspace_browser`: 37 real catalogue browser checks passed.
- `node --check backend/static/catalogue_workspace.js` and browser script syntax check passed.
- Python workspace router compilation passed.
- `impeccable detect --json` on the new HTML/CSS/JS returned `[]`.
- Desktop owner and 390px owner/viewer renders captured and visually inspected; mobile document widths fit the viewport.

Browser coverage: actual native signup and separate viewer invitation acceptance, fresh nullable storefront setup, INR decimal conversion, lost post-commit draft response and same-key recovery without duplication, DOM escaping, explicit publication/product activation/checkout policy gates, stale activation rejection and review reset, public authoritative SKU reader, policy-off checkout rejection, server-priced COD order, protected seller order confirmation/cancellation with reserved-stock restoration, SKU sellout rejection, concurrent inventory edit rejection with current product/list refresh, and read-only viewer controls.

This evidence certifies the bounded seller flow and real APIs on an isolated lane. Customer-facing remote storefront UI, legacy variant allocation editor, Parcel Desk connector, live gateway settlement and deployment remain separate workstreams. Independent integration review is recorded by the coordinator; these captures are not self-certification of those workstreams.

## Independent integration check

The integrator reviewed the owned source, desktop owner and 390px owner/viewer renders and found no substantive blocker in the bounded workspace. The actual application now mounts the workspace router; the browser harness no longer adds duplicate catalogue/workspace registrations. All **37 real browser checks passed again** on the separate `auth_wave2` PostgreSQL 16 lane after migrations through **0046** and current-authority fix **38c3da0**. The captures in this directory were refreshed from that run. Native onboarding separately passed **16** real browser checks and the channel operator passed **17** against the same integrated source, in sequential isolated database leases. These checks do not cover a published customer storefront or live provider behavior.
