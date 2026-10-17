# Catalogue workspace verification — 2026-10-18

Source: new native workspace router/static files, existing catalogue.v2 APIs, native auth dependencies including the shared nullable-response fix ca7233c. PostgreSQL 16 disposable checkout lane; P01 reset lease and actual Alembic migrations through 0044. No live provider calls, customer sends, or payments.

Observed results:

- `python -m pytest backend/tests/test_catalogue_workspace.py -q`: 3 passed, 1 existing Pydantic deprecation warning (3.64s).
- `python -m tests.run_catalogue_workspace_browser`: 66 real catalogue browser checks passed.
- `node --check backend/static/catalogue_workspace.js` and browser script syntax check passed.
- Python workspace router compilation passed.
- `impeccable detect --json` on the new HTML/CSS/JS returned `[]`.
- Desktop owner and 390px owner/viewer renders captured and visually inspected; mobile document widths fit the viewport.

Browser coverage: actual native signup and separate viewer invitation acceptance, fresh nullable storefront setup, INR decimal conversion, lost post-commit draft response and same-key recovery without duplication, DOM escaping, explicit publication/product activation/checkout policy gates, stale activation rejection and review reset, public authoritative SKU reader, policy-off checkout rejection, server-priced COD order, protected seller order confirmation/cancellation with reserved-stock restoration, SKU sellout rejection, concurrent inventory edit rejection with current product/list refresh, and read-only viewer controls.

This evidence certifies the bounded seller flow and real APIs on an isolated lane. Customer-facing remote storefront UI, legacy variant allocation editor, Parcel Desk connector, live gateway settlement and deployment remain separate workstreams. The coordinator independently reviewed the recovery/link source and accepted it; these captures are not self-certification of those workstreams.

Recovery follow-up: commit-201/drop → reload → explicit same-key retry leaves exactly one Product. A malformed 201 body keeps the saved command and its retry returns that same Product. Corrupt/expired/changed envelopes, persistence failures, altered hidden form input, native-session replacement, foreign-user/business scope and 401 are exercised. No new command is posted automatically. The public-link contract is tested with explicit transport-supplied canonical/unsafe URLs; default-off behavior uses the real private API. Shared cleanup dependency837b7b0 is consumed. The coordinator reported no substantive source-review blocker before this final run.

Focused post-change rerun: 3 backend checks passed (3.64s), 66 recorded browser checks passed, and all 5 shared native transport/cleanup Node checks passed. New 390px recovery capture was visually inspected; mechanical detector returned `[]`.

## Independent integration check

The integrator reviewed the source, desktop owner and390px owner/viewer renders with no substantive blocker. The actual application mounts this router; central browser harnesses no longer add duplicate registrations. Before the recovery follow-up, **37 real browser checks passed again** on the separate `auth_wave2` PostgreSQL16 lane through0046 and authorityfix38c3da0. Native onboarding separately passed16 and the channel operator17. The pending final integration rerun will verify the expanded66-check recovery source. The original binary capture conflict was resolved in favor of the worker's newer66-check renders; no application-source conflict occurred.
