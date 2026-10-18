# Bounded SEO implementation and independent QA handoff

18 October 2026. Based on reviewed release composition `e750e5a`, preserving the
latest recovery fixes. Tested composed source: `4da0b9f`. **CSV is wholly local-owned
by catalogue_commerce**: product per row, stable document UUID + product_ref,
reserved `0053 → 0052`. This remote batch makes no CSV/import, migration, recovery
UI, shared backend dependency or `app/main.py` changes. Local support/customer
links/analytics remain separate integration work; analytics `3556850` is reported
locally and is not part of this frozen base.

## Implemented behavior

- `/sitemap.xml` lists current active/published store sitemaps.
  `/sitemap-store-{slug}.xml` lists only that store's validated public home,
  activated products and referenced categories. Root-level files keep the canonical
  store home within [protocol directory scope](https://www.sitemaps.org/protocol.html#location).
  XML is UTF-8, escaped, bounded and canonical-origin bound, with no fabricated dates.
  Capacity overflow fails closed instead of silently dropping URLs.
- `V1_STOREFRONT_LEGACY_REDIRECTS` defaults to `[]`. Explicit reviewed entries bind
  exact source scheme/Host/raw path to a validated canonical store/product/category
  destination. The destination is checked against current publication on every
  request. No source queries, arbitrary external targets, guessed seller mappings,
  private/order destinations, wildcard redirects or real routing writes are added.
- Startup checks reject existing, later-registered, dynamic and slash-equivalent
  route collisions. A narrow ASGI fence stops implicit slash redirects before
  request authority can enter a Location header, preserving unrelated routing.
  Private order capability pages and legacy `/shop` routes retain their behavior.
- Existing `V1_STOREFRONT_ENABLED` controls installation. Direct router consumers
  must also install `install_seo_request_fence`; real storefront bootstrap does so.

Only five application files change: storefront protocol, storefront bootstrap,
the single configuration field, publication provider and new `storefront/seo.py`.
No new schema is required.

## Pushed source and integration

| Branch | Worker head | Coordinator integration |
| --- | --- | --- |
| `codex/v1-seo-publication` | `e8873f8b92e283170d3e848b7dfa5a7821cfbd3d` | Original commits `b57934a`, `387268e`, `e8873f8` |
| `codex/v1-seo-independent-qa` | `8cf923b30d3463e0d2e4d05d0067b7f23734a8d0` | Only QA-owned `fd09de0`, `8cf923b`; omit duplicate source cherry-picks `f1fbe1c`/`ac6a7a7` |
| `codex/v1-acceptance-delta` | `383159c214f267aadfc0282574f15693229c78b6` | Frozen-source remaining-work inventory |

`codex/v1-seo-coordination` composes these reviewed originals and retains contracts,
independent checks and handoff artifacts. Its later documentation/evidence commits
do not change the application source tested at `4da0b9f`. Worker configurations
were explicitly GPT-6.1 Sol/high with fresh contexts.

## Verification actually performed here

- Full composed backend, Python 3.11.16: **1,153 passed, 576 skipped**, zero
  failures/errors, 8.50 seconds. Skips remain unexecuted DB/provider-dependent cases;
  they are not acceptance passes. Raw/JUnit: `artifacts/v1/seo-coordination/final-backend.*`.
- Independently authored SEO cases: **113 passed, seven actual DB cases skipped**.
  Two additional environment/spawn-boundary checks passed. Producer new SEO cases:
  **142 passed, seven actual DB cases skipped**. These selections overlap the full
  suite and are not added to its total.
- Preserved the initial independent **103 passed / four failed / seven skipped**
  checkpoint. The four failures exposed slash-alias resource ownership conflicts;
  all pass after `387268e`. Malformed provider data, dynamic/concrete/mount/late
  collisions, Host/raw-path/query attacks and private order regressions are covered.
- Fresh actual `app.main` source startup with publication enabled passed final-route
  validation and retained legacy/order routes. No DB/provider call or listener was
  involved; this is startup/source verification, not mounted acceptance.
- Runtime context contains **289 files**, including the new SEO module; repeated
  archives with different source timestamps matched. No new image was built or run.
- All **24 producer hashes** and **11 QA hashes** match composed files. Node harness
  syntax passed. The mounted runner refused missing DB allocation with exit 1 before
  connection, reset, subprocess or listener. Actual mounted execution was not run.

See `artifacts/v1/seo-coordination/final-verification.json`,
`docs/v1-seo-publication.md` and `docs/v1-seo-independent-qa.md` for exact commands,
separate evidence and remaining gates. Historical PG16/image/browser records retain
their original source attribution and are not repurposed to certify this feature.

## Local execution still required

After composing with the local `0051`/`0052`/`0053` work, allocate an exclusive P01
numeric-loopback PostgreSQL16 lane with exact `munimjee_test_<TEST_LANE>` name and
`TEST_DB_RESET=1`. Run both new DB suites plus required migrated lease/full backend
regressions. All **14 new DB cases must execute without skip**. The existing P01
lease/reset policy remains unchanged; no production/admin URL fallback exists.

Then run `python -m tests.run_v1_seo_independent_mounted` from `backend/` with the
allocated lane and explicit unused `MUNIMJEE_SEO_QA_PORT`. The dedicated runner holds
the lease, waits for its owned actual-main child to bind, uses only literal-loopback
HTTP, creates synthetic catalogue/COD fixtures and reconciles unpublish/order access.
Its actual output and before/after source manifests are deliberately absent here.
This is HTTP acceptance; browser/device coverage remains separate. Use the detailed
sanitized environment commands in the independent QA document.

No Docker probe/restart, hosted retry/billing change, real provider, DNS/routing write,
charge, production access or deployment occurred. Hosted execution remains blocked
by the previously recorded account billing lock. New locked-image amd64/arm64 builds
and offline smoke, real PG16 restore and approved application rollback/forward fix
remain release gates.

Full V12/A21/M07 still requires the actual supported legacy URL inventory, source
ownership/domain/provider authority, canonical destination/order-link reconciliation
and migration/rollback evidence. No real mapping has been enabled. The supplement
`docs/v1-acceptance-delta.md` retains the other code-owned gaps and local ownership;
provider/device/operational gates remain separate. **V1 is not release-ready.**
