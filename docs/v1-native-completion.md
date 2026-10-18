# Native import allocation and persisted public design composition

18 October 2026. Base `a2ea26d`; application checkpoint
`79ea6480b0887d9c31a7f7d81b33ced1a649f5dc` on
`codex/v1-native-composition`. This document supersedes the prior standalone
feature notes' pending shared-hook statements for this composition only.
Actual PostgreSQL acceptance remains the local integrator's next gate.

## Implemented behavior

The native setup and Catalogue pages link to Imports and Store design. Both
pages are mounted on the actual app, require native tenant access, and retain
the shared no-store error policy. Shared authentication transitions and401
responses clear catalogue, parcel, import and theme private command prefixes.
Public customer checkout recovery keeps its separate lifecycle.

Imports consumes the frozen actual `catalogue-preview`/`catalogue-draft` bridge.
Sellers resolve factual uncertainty, explicitly allocate every supported SKU
combination, match the confirmed integer stock total, and confirm the five saved
facts. Unknown stock never becomes untracked inventory. Each SKU has an explicit
inclusion choice for later product activation, initialized from the validated
server proposal. An all-false choice is retained with a reconciliation warning.
Creation itself leaves Product inactive, creates no CatalogueActivation, does
not publish the store or enable checkout, and never updates an existing linked
product on reimport. The prepared native journey separately exercises explicit
Catalogue activation after proving private creation.

Exact command bodies and idempotency keys survive uncertain responses and reloads.
Existing receipts are validated against the current candidate and native business
route. Session/tenant/role checks, generation fences, bounded decoders, and digest
continuation checks prevent late responses from restoring old private data or
commands. Original media, source facts and seller overrides remain separate.

Theme draft and published configurations persist in two registered models under
the single reserved head `0049_v1_storefront_settings`, whose predecessor is
`0048_v1_parcel_tracking`. Actual Alembic DDL is committed; no schema is created
from metadata. Save and publish use `business_mutation('business.write')`, so
current session and role are checked before the caller-owned transaction commits,
including after lock waits and on exact receipt replay.

The actual public provider reads only published configuration after existing
store/tenant publication authorization. SSR and the real live renderer validate
the same allowlist, map three palettes to fixed tokens, and escape/render text
safely. All three themes honor seller text and presentation toggles; category/PDP
routes, COD, online payment and protected order status retain their authorities.
Draft save/private preview never changes public design. Design publication never
publishes a store, activates a product or changes checkout/payment settings.
Payment handoff, checkout recovery and order-status modules are unchanged from
`a2ea26d`.

## Evidence and limits

The coordinator and all three workers were explicitly configured GPT-6.1 Sol/high;
actual latest-turn metadata was checked for each at dispatch. Ownership is frozen
in `v1-native-completion-contracts.md`; original checkpoints/worktrees are preserved.

Final composed checkpoint `48e049c` passed **842 backend checks, with512 explicit
skips and zero failures/errors**, after the independent QA commit was integrated.
The skips are509 unallocated database cases, two unallocated Redis cases and one
missing provider cassette. `final-backend.{txt,xml}`, `final-backend-source-sha.txt`
and `verification.json` under `artifacts/v1/native-completion/` pin that run.
All independent QA source hashes match the composed files. The final runtime
context is byte-identical to the application checkpoint described below; no
Docker image build/smoke or actual PostgreSQL execution is implied.

- At composed checkpoint `cec16d8`, the full backend suite passed838 and skipped484:
  481 missing disposable DB allocation, two missing Redis allocation, one missing
  provider cassette. See `artifacts/v1/native-completion/backend.{txt,xml}` and
  `source-sha.txt`. These skips are not passing database/provider evidence.
- After final theme/preview composition, focused Python checks passed91 with24
  explicit DB skips. The Node suite passed77, including shared cleanup and the
  existing payment/recovery tests. See `final-focused.txt` and `final-node.txt`.
- Import owner evidence:164 Chromium behavioral assertions using synthetic
  same-origin HTTP, including delayed digest/session races, immutable recovery,
  complete allocation, eligibility choices, keyboard behavior and mobile layout.
  The three native page tests explicitly skip without an allocated P01 lane.
- Theme owner evidence:15 native editor browser cases using mocked HTTP, plus18
  actual SSR/live-renderer journeys using a synthetic published provider and
  mocked orders/SDK/payment/status transport. All themes have inspected desktop
  and mobile captures; the video collection palette contrast was corrected.
  These results do not establish PostgreSQL persistence or real payments.
- Runtime context at application checkpoint79ea648 contains272 files (2,853,454
  bytes), all six native assets, `published-design.js` and actual0049 DDL. The
  explicit package/bootstrap allowlists and missing-asset checks are updated.
  `runtime-manifest.json` records exact file hashes. Docker build/smoke was not
  run because the remote Docker probe was unavailable; no service was restarted.

Independent QA commit `8aecf18085d4b43b30f7a895553a4b469270922e` adds actual-main
mounted import/theme HTTP cases, observed PostgreSQL row-lock revocation cases,
and a guarded actual native browser runner. Its33 source-pinned synthetic-HTTP
browser checks passed:14 import allocation/recovery, six private theme, and13
public SSR/live/COD/synthetic-online/private-status checks. All reported zero page
errors and external requests. Its detailed matrix is in
`v1-native-completion-independent-qa.md`; historical pre-fix race evidence is
retained and labelled. Actual mounted database/browser execution remains pending.

## Local PostgreSQL verification

Run only on the integrator's explicitly allocated disposable PostgreSQL16 lane
using P01 `TEST_DATABASE_URL`, matching `TEST_LANE` and `TEST_DB_RESET=1` with the
held migration/reset lease. Do not copy production configuration or credentials.
The focused acceptance files are:

- `backend/tests/test_import_catalogue.py`
- `backend/tests/test_v1_native_completion_import_http.py`
- `backend/tests/test_v1_native_completion_theme_http.py`
- `backend/tests/test_v1_theme_settings.py`
- `backend/tests/test_v1_theme_publication.py`
- `backend/tests/test_v1_mutation_boundary.py`
- `backend/tests/test_v1_startup.py`

The prepared actual native browser targets are
`PYTHONPATH=backend python -m tests.run_wave4_native_browser` and
`PYTHONPATH=backend python -m tests.run_import_workspace_browser --native`.
Their synthetic retrieval/state hooks live only in excluded test modules; none
is mounted or packaged by the runtime app. The runner holds the P01 lease for its
whole lifetime and fails before connecting or starting a server without a lane.

No production deployment, live provider/customer messages, real charges or shared
service restarts were performed. External provider/physical-device acceptance and
production migration/runtime rehearsal are separate from this source checkpoint.
