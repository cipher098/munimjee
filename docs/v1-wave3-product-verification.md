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
