# Wave 3 independent product verification

Updated 18 October 2026. QA branch `codex/v1-qa-product`; starting application
source `aa6ac940ef877a8a37baac39afec44268b49f84e`. Scope is synthetic local
verification of the mounted native import workspace, canonical allocation seam,
and persistent theme settings. No provider, customer, payment or tracking
operations are authorized or exercised here.

## Current evidence

`backend/tests/test_v1_wave3_import_journeys.py` adds **11 collected actual HTTP /
P01 migrated-database cases** against the current application. On the initial QA
host run all **11 skipped**, because no disposable `TEST_DATABASE_URL`,
`TEST_LANE` and `TEST_DB_RESET=1` were allocated. This is collection evidence,
not a passing database or product claim. Artifacts are under
`artifacts/v1/qa-product/2026-10-18-baseline/` and identify the application base.

The tests import the actual registered app, obtain native sessions through signup,
use its bound CSRF token, and persist through actual Alembic migrations supplied
by `migrated_engine`. Only source retrieval is synthetic. The background worker
remains off; tests explicitly run a chosen synthetic job, never a live provider.
There is no metadata-created schema, alternate admin URL or dotenv fallback.

## Acceptance matrix

| Boundary | Independent check | Current evidence / remaining gate |
| --- | --- | --- |
| Website authorization | Explicit source consent; literal extraction only; no implicit ownership claim | Existing mounted API; workspace consent and browser assertions pending peer integration |
| Original upload | Exact bytes/hash preserved; same-key replay; changed-body conflict; two uploads of same bytes produce one candidate | New mounted DB journey; DB execution pending |
| Durable progress | A pending job is visible, claim commits before retrieval, reload reads current state | New mounted DB journey; browser reload pending |
| Cancellation | Cancel while synthetic retrieval waits; same-key cancel replay; late result produces no candidates | New mounted DB race; DB execution pending |
| Current authority | Role downgraded in another transaction during retrieval; late result fails with `authorization_revoked` | New mounted DB race; DB execution pending |
| Retry | Stable timeout code, durable manual backoff, same-key response replay, early claim no-op and later recovery | New mounted DB journey; DB execution pending |
| Review and factual uncertainty | InStock source text keeps numeric stock unknown; approval requires explicit factual overrides; stale revision fails | New mounted DB journey; DB execution pending |
| Separate activation | Import approval writes no Product, Storefront or CommerceOrder; does not activate or publish | New mounted DB journey; allocation seam pending |
| Instagram honesty | Connected synthetic account still yields persisted `provider_capability_pending`, zero candidates | New mounted DB journey; no live-provider proof |
| CSRF | All five import mutation surfaces deny unbound native requests before import writes | Five new mounted DB cases; DB execution pending |
| Tenant/read-only/session | Foreign tenant resources, viewer/staff mutations, expired/revoked sessions | Existing base security evidence; wave3 workspace/adapter cases pending |
| Reimports/rejection | Seller corrections preserved and rejected candidate not revived by changed extraction | Wave3 browser / additional mounted integration pending |
| Unknown vs untracked | Import null stock is unknown; canonical null is permitted only after explicit untracked allocation | Canonical wave3 contract pending; no guessing or auto conversion |
| Uncertain browser writes | Durable same-key reload recovery; malformed/corrupt/expired storage fences; auth transition cleanup | Workspace and canonical seam pending |
| Async response isolation | Delayed old-business response cannot overwrite current business/session view | Workspace integration pending |
| Theme private/public split | Draft save, private preview and explicit publish remain separate; no draft private fields in bootstrap | Theme persistence contract/model/migration pending |
| Theme concurrency | Stale version rejected; commit/lost-response exact replay safe; current readonly roles cannot mutate | Theme persistence contract/model/migration pending |
| Theme product continuity | All three seller-selected themes render responsive catalogue; existing public COD/status remain valid | Theme provider integration pending |
| Accessibility/layout | Native keyboard focus, labelled errors, 390px and desktop layouts with no horizontal overflow | Browser integration pending; no physical-device claim |

## Reproducible commands

From the QA worktree with its cached Python 3.12 venv:

```sh
PYTHONPATH=backend .venv-qa-wave3/bin/python -m pytest \
  backend/tests/test_v1_wave3_import_journeys.py -q -ra -p no:cacheprovider
```

Actual DB execution requires the coordinator-provided disposable PostgreSQL 16
lane and the P01 guarded reset/migration lease. Missing DB is an explicit skip,
never a pass. Browser execution uses reserved port **4322**, sequentially with
other QA runners; no service exposure or remote restart is attempted.

## Open gates

The frozen wave3 contract is not present at the initial base. Native import UI,
canonical approved allocation, theme DDL/service and public provider composition
must land under owner review before these can be product-verified together.
No peer application commit has been cherry-picked into this QA branch. Physical
devices, live provider permission/consent, media decoder/security operations,
production migration/rollback and production cutover are separate gates.

## Independent browser checkpoint (HTTP mocks)

The actual peer import page passed **6/6** independent Chromium checks with
synthetic HTTP responses: explicit consent/unknown-stock approval block; rapid
submit with one durable command key; delayed old poll rejected after explicit
refresh; changed identity clears evidence/forms/import commands; current viewer
controls disabled with 390px fit; and malicious source text stays literal.
The test serves captured actual peer HTML/JS/CSS bytes read-only. It does not mount
an alternate application implementation or claim database integration.

The actual peer theme editor passed **6/6** independent Chromium checks with
synthetic HTTP: viewer can read and reload at 390px; delayed old-session load
cannot repopulate a terminal fence; a committed/lost draft response reloads and
replays the exact operation/key, with publication only on its separate action;
rapid draft submit allocates one durable command; unavailable storage prevents a
new mutation; and changed identity clears all theme-command scopes and preview.
The preview response in this suite is explicitly an inert synthetic transport,
not proof of the theme renderer or public provider.

Both suites observed **zero page errors and zero external requests**. Their
JSON artifacts identify source base SHA, changed/untracked UI files, exact asset
SHA-256 values, runner digest, Chromium version and whether the source stayed
unchanged during the run. These are interim peer-source checks, not an integrated
release claim. The 390px screenshots were visually inspected; no horizontal
layout overflow was observed. Physical-device and full accessibility acceptance
remain pending.

Reproduce the HTTP-mock suites after installing the repository's locked Playwright
dependency in `frontend/storefront`:

```sh
node backend/tests/wave3_imports_mock_browser.mjs /path/to/reviewed/import-source
node backend/tests/wave3_themes_mock_browser.mjs /path/to/reviewed/theme-source
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE` may point to an already installed Chromium
binary. The QA host used cached Chromium headless shell revision 1243 with
Playwright 1.58.2; it did not download a new browser. Source and browser paths are
recorded only as local provenance, with no credentials or real customer data.

The actual mounted-app runner is prepared and syntax-checked, but **not run**:

```sh
PYTHONPATH=backend .venv-qa-wave3/bin/python -m tests.run_v1_wave3_browser
```

It requires the coordinator's explicit P01 disposable DB variables, reviewed UI
composition and the actual full Alembic chain. It starts only loopback port 4322,
holds the reset/migration lease for the complete browser lifetime, creates a real
native account and an explicitly unpublished synthetic Storefront, then exercises
consent → pending job → reload → synthetic literal extraction → factual review →
private approval. It separately checks zero catalogue products, unchanged
unpublished store and disabled checkout policy. The only extra test-server route
is an authenticated/current-write-capability synthetic worker trigger; it is
owned under `backend/tests` and never mounted by production `app.main`.

## Private browser-storage contract

Shared native identity transitions and 401 handling must remove every native
seller command prefix:

- `munimjee.v1.catalogue-draft:`
- `munimjee.v1.import-command:`
- `munimjee.v1.theme-command:`

Public customer checkout/status recovery has a separate lifecycle and must remain
intact. At the inspected base, shared `v1_client.js` clears only the catalogue
prefix. That integration gap has been reported to the coordinator; each new
page's own identity/fingerprint fence is independently verified above. Shared
all-prefix cleanup after composition remains a separate check.
