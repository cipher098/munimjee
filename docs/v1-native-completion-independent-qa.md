# Independent native completion QA

18 October 2026. QA branch `codex/v1-qa-native-completion` preserves the prior
`ebf1404`, `51ebdf2`, and `d1223ea` evidence. This continuation owns tests,
runners, documentation and artifacts only. Feature source arrives only through
reviewed coordinator compositions; this branch makes no application or DDL edits.

## Final reviewed checkpoint

Reviewed feature composition: `79ea6480b0887d9c31a7f7d81b33ced1a649f5dc`.
Tested QA merge: `af71097c3d25903c527136e4a8d366f570751dc7`, with clean
application/static/migration/frontend source. Fresh result JSON files pin that
head and the individual source/runner hashes.

- Independent allocation DOM: **14 passed**, including the previously failing
  digest/account-change fence. Quantities include explicit zero and mixed
  per-SKU eligibility; product activation remains a separate authority.
- Independent private-theme DOM: **6 passed**.
- Independent public SSR/live DOM: **13 passed** across all three themes,
  including COD, synthetic online handoff, private order-status access, defaults,
  field projection and the final video palette background.
- Focused Python source/backend gates: **67 passed, 86 explicit DB skips**;
  the two new independent modules contribute **2 passed, 28 DB skips**.
- Browser reports show **zero page errors and zero external requests**.
  Chromium is **153.0.8010.12**. Desktop/mobile captures were visually inspected;
  these are browser viewport checks, not physical-device acceptance.
- Actual mounted browser runner: syntax checked and verified to reject an
  unallocated lane before connection/server startup; **not run against a DB**.

`wave4-native-completion/verification.json` records source hashes, exact counts,
remaining gates and unchanged payment-module hashes relative to `a2ea26d`.
Public/provider HTTP/SDK fixtures remain explicitly synthetic even though they
execute the actual SSR renderer, canonical decoder, payment-handoff and private
order-status modules.

## Evidence boundaries

| Check | Evidence type | What it establishes |
| --- | --- | --- |
| `test_v1_native_completion_import_http.py` | Actual `app.main` mount + actual P01 migrations, when provisioned | Explicit Cartesian allocation, totals/zero, private product receipt and exact replay, unsupported/unknown facts, stale/reimport/tenant/role/session/CSRF/disabled flag, observed PostgreSQL row-lock revocation for creation and replay |
| `test_v1_native_completion_theme_http.py` | Actual `app.main` mount + actual P01 migrations, when provisioned | Three themes: private saved draft/preview, explicit saved-design publication, separate store visibility, published-only SSR, query parameters confer no authority, observed PostgreSQL row-lock role/session rollback including receipt replay |
| Independent theme migration ancestry + no-session route checks | Actual source/imported application; no DB | Exact `0049_v1_storefront_settings` after actual `0048_v1_parcel_tracking`; native private routes reject unauthenticated requests before any DB query |
| `wave4_allocation_http_mock_browser.mjs` | Actual page/client source; **all API responses synthetic** | Allocation DOM, durable exact-body/key recovery, rapid click, late response, dirty facts, malformed receipt/storage, role/session cleanup, mobile keyboard and controlled digest identity fence |
| `wave4_theme_private_http_mock_browser.mjs` | Actual private editor/client source; **all API responses synthetic** | Saved-draft/publication separation in UI, exact recovery, rapid save, viewer reload, storage failure, late load and focus identity cleanup |
| Public fixture exporter + `wave4_public_theme_http_mock_browser.mjs` | Actual SSR renderer/order shell/live modules; **synthetic public-provider DTO, HTTP and payment SDK** | All three SSR/DOM themes, defaults, escaping/private-field projection, fixed palettes/mobile layout, actual frontend COD/online handoff and private order-status behavior |
| `run_wave4_native_browser.py` | Prepared actual mounted browser + held P01 migration/reset lease | Actual signup/native allocation/private receipt and theme publication without store publication; **not run remotely** |

Synthetic HTTP/provider/SDK tests do **not** establish persisted public-theme
projection, actual SQL lock behavior, migration execution, captured payments,
provider canaries or physical-device acceptance. Every browser JSON identifies
its mode, source head, individual source hashes, runner hash, Chromium version,
source stability and blocked external requests. Fixture exports additionally pin
their real renderer/router inputs and generated HTML hashes.

The independent DB fixture enables the actual storefront installer with a valid
HTTPS canonical origin if `app.main` was first imported while its flag was off.
It snapshots/restores `app.router.routes`, uses the actual publication provider,
and keeps caller-owned transaction commit/rollback. It does not install a fake
public route or substitute a service. Fixture facts/tenants are synthetic.

## Remote gates and historical findings

No P01 database URL/lane/reset allocation is provisioned in this remote QA
process. The coordinator confirmed unavailable Docker; the QA read-only
`docker info` availability probe did not respond within its bounded check and
was cancelled. No service was restarted, no database was reset, no credentials
were guessed and no production/provider/customer requests were made.

The 28 new persistence/lock-wait cases therefore report explicit DB skips. The
actual mounted browser runner is syntax-checked/prepared only. Static Alembic
ancestry proves the committed revision graph, not execution of that graph.

Historical wave 3 artifacts remain unchanged. Fresh continuation evidence is
under `artifacts/v1/qa-product/wave4-*`. Two pre-final independent reports are
retained in `wave4-native-completion/historical/`:

- `allocation-fieldset-matcher-harness-failure.json`: 11 passed, two QA harness
  failures. Playwright's disabled matcher on the fieldset itself did not reflect
  its native disabled descendants. The corrected check asserts the attribute
  and disabled quantity input. This was not an application defect.
- `allocation-digest-fence-before-fix.json`: all original 13 allocation cases
  passed; the added controlled-digest identity case failed on reviewed import
  source `ff4a4fd` in QA merge `9252188`. Releasing a paused command digest after
  focus/account fencing restored one old private command in session storage.
  The owner/coordinator received the reproducible finding and prepared terminal
  generation checks. This result is pre-fix evidence, not a final acceptance run.
  Final reviewed source passes the same independent controlled-digest case.

## Local integrator procedure

Only use the coordinator-allocated disposable P01 connection and lane. Keep the
existing exact URL/lane/reset validation and lease mechanism intact. Do not copy
an application `.env`, use a shared database, manufacture tables with
`create_all`, bypass the network guard or substitute SQLite.

From `backend`, with the allocated `TEST_DATABASE_URL`, matching `TEST_LANE` and
explicit `TEST_DB_RESET=1` already supplied securely:

```sh
python -m pytest tests/test_v1_native_completion_import_http.py tests/test_v1_native_completion_theme_http.py -q -rs
python -m tests.run_wave4_native_browser
```

The browser wrapper holds `tests.isolated_database.migrated_database()` across
actual migrations, server lifecycle and browser completion. Its only server is
`127.0.0.1:4322`; all external browser requests are aborted. A test-only native
capability-protected endpoint inserts literal fixture source facts. All subsequent
review/preview/catalogue/theme requests use actual mounted application routes.
The wrapper has no database, lane, credentials or provider fallback.

If local Playwright is not installed, the runner accepts an already installed
`MUNIMJEE_PLAYWRIGHT_MODULE` absolute module path and
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` absolute binary path. These configure the local
test runtime only; they do not modify application configuration.

Persist exact command/body evidence and resulting SQL/receipt/UI checks when the
local lane is run. Keep actual DB results distinct from the synthetic browser
directories and retain an explicit pending gate until that run succeeds.
