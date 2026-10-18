# Independent SEO acceptance

18 October 2026. This is bounded source/pure/ASGI verification against the frozen
remote base `e750e5a`, followed by SEO source commits `b57934a` and `387268e`.
It is not a release-readiness, real seller migration, actual database, browser,
physical-device, provider or domain acceptance claim.

The coordinator's ownership contract is `docs/v1-seo-contracts.md` at `1f00b39`.
This lane adds only new independent tests, a dedicated guarded mounted HTTP
harness, this report and dedicated evidence. The producer's implementation is
read-only here. CSV remains wholly local-owned, including reserved `0053 → 0052`;
local support/customer identity/analytics work is not integrated into this base.

## Result and provenance

| Selection | Result | Meaning |
| --- | --- | --- |
| Independent checkpoint `b57934a` | 103 passed, 4 failed, 7 skipped | Reproduced existing-resource ownership defect across slash aliases. |
| Independent final after `387268e` | 113 passed, 7 skipped | Synthetic providers and in-process ASGI transport; all current independent cases pass. |
| Affected SSR/bootstrap plus producer SEO tests after `387268e` | 177 passed, 7 skipped | Separately executed regression selection, not additional independent test authorship. |
| Harness environment/spawn proof | 2 passed | Pure fake-process checks; no Node/server/DB execution. |
| Mounted runner without allocated DB | Expected refusal, exit 1 | P01 guard stops before database connection, reset, subprocess or listener. |
| Actual migrated database and actual-main mounted HTTP | Pending | No allocated P01 lane/listener port supplied; no execution or success implied. |

The final selections total **292 passed, 14 skipped**. Seven skipped cases belong
to this independent suite; seven belong to the producer's actual-DB suite.
The cached interpreter is Python 3.11.16; Node v24.20.0 performed syntax validation
only. Deprecation warnings from existing Starlette/Pydantic dependencies remain.

Raw output and JUnit are retained separately:

- [Initial red checkpoint](../artifacts/v1/seo-independent-qa/checkpoint-b57934a.txt)
  and [JUnit](../artifacts/v1/seo-independent-qa/checkpoint-b57934a.xml).
- [Final independent run](../artifacts/v1/seo-independent-qa/independent-final.txt)
  and [JUnit](../artifacts/v1/seo-independent-qa/independent-final.xml).
- [Affected regression run](../artifacts/v1/seo-independent-qa/affected-regression.txt)
  and [JUnit](../artifacts/v1/seo-independent-qa/affected-regression.xml).
- [No-lane guard refusal](../artifacts/v1/seo-independent-qa/mounted-no-lane-refusal.txt)
  and [machine-readable verification/source hashes](../artifacts/v1/seo-independent-qa/verification.json).
- [Harness environment/spawn proof](../artifacts/v1/seo-independent-qa/harness-environment-proof.txt)
  and [JUnit](../artifacts/v1/seo-independent-qa/harness-environment-proof.xml).

The post-review harness proof preserves the credential-free Node allowlist already
committed in `fd09de0`. An initial concern was based on an earlier in-progress draft;
no committed credential-propagation defect was found. The small follow-up extracts
the existing filter into a pure helper and verifies the actual subprocess-call
boundary with fake processes. Synthetic database/provider secrets, Node injection
variables and proxy/loader settings stay out of Node's environment; PATH, HOME,
temporary-directory/locale settings and the explicit QA port remain allowed.
The server retains the sanitized P01 environment it needs. This adds verification
without changing application behavior or claiming any actual mounted execution.

## Independently reviewed risks

The tests use independently constructed synthetic provider data and `.example.test`
inventories. They do not import the producer's fixtures. Guarded migrated cases
reuse the pre-existing native signup/catalogue fixture only for setup; their SEO
assertions are independent.

- Root-level `/sitemap.xml` and `/sitemap-store-{slug}.xml` preserve sitemap
  directory scope for the homepage, product and category URLs. Namespace, UTF-8
  serialization, XML escaping, unique locations, strict location length, no fake
  `lastmod`, configured origin and bounded whole-document failures are covered.
- Discovery rejects invalid/duplicate/over-capacity provider slugs. A thousand-store
  synthetic boundary is included completely. Malformed projections fail closed
  with redacted 503; unpublished or foreign snapshots return 404. Private fields,
  orders, capabilities and provider error bodies do not enter discovery output.
- Redirects use only explicit reviewed inventory, empty by default. Exact source
  scheme/Host/raw path and no query are required. Tests cover injected forwarded
  headers, duplicate Host, ports/case, percent encoding, backslashes, traversal,
  protocol-relative/external targets, wildcard/parameter paths, protected paths,
  duplicate keys/sources/slash aliases, invalid review metadata and forged direct
  dataclasses. Target publication is rechecked on every request.
- Configured origin controls, malformed/leading-zero/out-of-range ports, ambiguous
  authorities, userinfo, Unicode/IDNA aliases, query/fragment and unsafe HTTP origins
  are rejected before route installation.
- Existing routes/mounts declared before or after installation remain protected.
  Tests include concrete versus dynamic routes, crossing dynamic patterns and
  startup collision checks after final route registration.
- The request fence rejects only known source/discovery slash and encoding aliases
  before Starlette can emit a request-host-derived implicit redirect. Unrelated
  normal slash handling remains 307; an existing internal-double-slash route is
  preserved or conservatively rejected at startup, never masked by a 404 fence.
- The baseline private order shell remains usable after public unpublication and
  never embeds a query-supplied capability. Actual existing capability API behavior
  after unpublication has a separate guarded DB case and remains unexecuted here.

Review caught malformed-provider exception classification, route intersection
direction, overlapping dynamic patterns and pre-handler slash normalization issues
during source work. The committed `b57934a` checkpoint then independently reproduced
four concrete slash-alias resource collisions: `/old-dress` versus `/old-dress/`,
both registration orders. `387268e` fixed them and narrowed fence recognition to
preserve internal duplicate slashes. Red evidence is preserved; final tests passed.

## Repeat the pure/ASGI selections

Run from `backend/` using the cached interpreter. The shared test safety hook
disables dotenv/provider settings and blocks outbound networking. Omitting
`TEST_DATABASE_URL` intentionally skips actual DB cases; it cannot prove migration.

```sh
env -i PATH="$PATH" HOME="$HOME" \
  /tmp/munimjee-release-ci-py311/bin/python -m pytest -q \
  tests/test_v1_seo_independent.py tests/test_v1_seo_independent_db.py

env -i PATH="$PATH" HOME="$HOME" \
  /tmp/munimjee-release-ci-py311/bin/python -m pytest -q \
  tests/test_v1_seo_independent_harness.py

env -i PATH="$PATH" HOME="$HOME" \
  /tmp/munimjee-release-ci-py311/bin/python -m pytest -q \
  tests/test_v1_storefront_rendering.py tests/test_v1_storefront_bootstrap.py \
  tests/test_v1_seo_publication.py tests/test_v1_seo_publication_db.py
```

## Pending guarded actual PostgreSQL 16 execution

An operator must separately allocate a disposable P01 lane on a numeric loopback
endpoint, an exact database name `munimjee_test_<TEST_LANE>`, disposable simple
credentials and a distinct unused listener port. This report allocates nothing.
Do not use an existing source, shared-service or production URL, and do not start
Docker, create a database, weaken guards or substitute another database engine.
These commands reset only the explicitly allocated database's `public` schema.
The existing P01 helper requires explicit reset opt-in and holds its advisory lease
through the whole migrated test/server lifecycle and cleanup.

After those operator-owned values exist, run from `backend/`:

```sh
env -i PATH="$PATH" HOME="$HOME" \
  TEST_DATABASE_URL="$ALLOCATED_TEST_DATABASE_URL" \
  TEST_LANE="$ALLOCATED_TEST_LANE" TEST_DB_RESET=1 \
  /tmp/munimjee-release-ci-py311/bin/python -m pytest -q \
  tests/test_v1_seo_independent_db.py \
  --junitxml=../artifacts/v1/seo-independent-qa/actual-db.xml
```

The URL grammar is exactly
`postgresql+asyncpg://<disposable-user>:<disposable-password>@127.0.0.1:<allocated-port>/munimjee_test_<allocated-lane>`
or numeric `[::1]`, without URL escapes, parameters, DNS names or hidden overrides.
The seven cases cover two-tenant publication, draft exclusion, seller/business/
product/SKU/activation/unpublish revocation and an existing COD order capability
after unpublication. A passing actual run must contain seven executed cases with
zero skips; all-skipped output is a failed acceptance gate.

## Pending actual-main mounted HTTP execution

The dedicated runner is
`backend/tests/run_v1_seo_independent_mounted.py`, server
`backend/tests/v1_seo_independent_server.py` and local-only Node probe
`backend/tests/v1_seo_independent_mounted.mjs`. Run **only through the runner**:

```sh
env -i PATH="$PATH" HOME="$HOME" \
  TEST_DATABASE_URL="$ALLOCATED_TEST_DATABASE_URL" \
  TEST_LANE="$ALLOCATED_TEST_LANE" TEST_DB_RESET=1 \
  MUNIMJEE_SEO_QA_PORT="$ALLOCATED_SEO_QA_PORT" \
  /tmp/munimjee-release-ci-py311/bin/python -m tests.run_v1_seo_independent_mounted
```

There is no DB or listener-port default. Missing/invalid values fail before any
listener/probe. The runner first holds the validated P01 lease and performs actual
migrations. Its actual main-app child binds only `127.0.0.1` and must emit an owned
post-bind marker before any HTTP request is sent. A bind failure never triggers a
probe against an unrelated service. The child/probe have bounded waits and terminate
before the lease closes. Node receives no database/provider credentials, follows
no redirects and sends requests only to that literal loopback origin.

The probe creates synthetic native sellers, publishes/activates catalogue products,
checks foreign/draft exclusion and source-origin safety, places synthetic COD only,
unpublishes and checks sitemap/redirect revocation plus old order capability access.
It opts out of customer updates and sends no provider request. It writes only check
names/statuses, never cookies, tokens, buyer/order payloads or DB credentials.

On successful actual execution the runner/probe generate `mounted-actual.json`
and raw SHA-256 manifests `mounted-source-before.json` / `mounted-source-after.json`
under the dedicated artifact directory. Manifests cover application Python,
storefront source assets and all three harness files. Any source change during
execution invalidates the run. Those actual artifacts are deliberately absent
from this handoff because no actual lane/listener was allocated. This is HTTP
mount verification, not Chromium, physical-device or real-provider acceptance.

## Remaining gates

Actual PostgreSQL 16 and actual-main mounted execution are pending. Real supported
legacy URL inventory, ownership/domain/provider authority, DNS/TLS/routing, traffic
reconciliation, customer order-link migration, rollback rehearsal, browser/device
acceptance and G0–G6 remain separate gates. Synthetic mappings establish redirect
infrastructure only. Default inventory remains empty; no actual seller URL has been
invented, enabled or accepted. This work does not close full V12/M07 or authorize
production cutover.
