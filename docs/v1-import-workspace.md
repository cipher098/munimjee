# V1 seller import workspace

18 October 2026. Allocation continuation: `codex/v1-import-allocation-ui`, based
on `a2ea26d` plus preserved workspace checkpoint `8e1aeb9`. The owner changes
only the import page/router, dedicated tests/runners/artifacts and this document.
No migration, shared auth/client, domain service, provider or production change.

The page `/v1/businesses/{business_id}/imports` uses native `v1_user` session,
current `catalogue.read` membership and the shared V1 API/CSRF client. Its shell
contains no seller facts and sends `Cache-Control: no-store, private` and
`Referrer-Policy: no-referrer`. APIs remain the authority for every read/write.

The previous rendered study remains in `artifacts/v1/import-workspace/`.
`allocation-design-study.html` and `.png` were rendered and inspected before
allocation implementation. Desktop keeps activity/candidates beside review,
with a sticky bounded list while reviewing allocations. Mobile stacks panels,
scrolls to selected review and uses labelled quantity inputs without overflow.

## Source, progress and review

- Authorized website sources use public HTTPS URLs. Original JPEG/PNG/MP4 uploads
  are bounded at 5,000,000 bytes and require explicit permission. Uploads send
  original raw bytes with current CSRF, same-origin credentials, no-store and
  redirect rejection. Original bytes are never saved in browser storage.
- Durable jobs expose state, attempt count, candidate count, revision and safe
  error codes. Eligible cancel/retry commands use expected revisions and stable
  keys; server backoff and retry limits remain authoritative. Bounded polling
  pauses after twelve checks, while hidden, or after increasing error backoff.
  Refresh/pagination epochs discard late polls and preserve editable candidate
  facts during ordinary job checks.
- Candidate evidence, extracted facts and seller overrides remain separate.
  Imported values render through textContent/form values, never HTML. Unknown
  price/stock/options stay unknown; explicit zero and no-options remain distinct.
  Structured options, price/currency and integer stock use typed inputs. Factual
  edits must be saved before review/draft submission; all five factual fields
  require explicit confirmation. Standalone approval/rejection remain available.
- Instagram retrieval honestly remains provider-capability pending, with original
  media and authorized website alternatives. No scraping, ETA or invented success.

## Reviewed private draft allocation

The UI consumes the frozen `docs/contracts/import-catalogue` and actual mounted
`GET /candidates/{id}/catalogue-preview` and `POST .../catalogue-draft` APIs.

A preview must match the selected candidate, current revision and effective saved
facts. Fact comparisons recursively sort object keys while preserving array order;
immutable command serialization/digests remain byte-for-byte unchanged. Bounded
response decoders validate every supported option combination exactly once,
integer/null proposed quantities, contract versions, state and receipt identity.
Malformed/stale previews withhold the form; selection/refresh/session epochs
ignore late responses. Unknown stock, unsupported price/currency/options, more
than 500 combinations, disabled bridge and missing storefront setup show actual
server issues and block draft creation. Unknown stock never becomes untracked.

Each supported combination has an explicit integer allocation, including zero.
Multiple SKUs start blank; the single-SKU confirmed total is shown for seller
review. A running total must match the saved confirmed total. Five separate
saved-fact confirmations and an explicit Create private catalogue draft action
send only revision, command key, review confirmation and allocations. Browser
facts, arbitrary product IDs and inferred source-page/upload photo URLs are never
sent to the bridge. All created SKUs explicitly use `active:false`; the UI says
so. Product activation, store publication, checkout and existing inventory remain
separate decisions.

A valid `import-catalogue.v1` receipt must match the candidate and exact current
business catalogue route, contain valid receipt/product IDs and preserve the
approved revision. Existing receipts replace creation controls with a catalogue
link and immutable product/revision details. A draft 409 clears the definitive
rejected command and refreshes actual candidate/preview state to discover an
existing receipt; browser product IDs in conflict payloads confer no authority.

## Recovery and identity fences

All mutations persist the exact body/key before sending. A preparation lock
prevents rapid submissions creating competing keys. The versioned envelope binds
actor, tenant and SHA-256 of the sign-in CSRF secret, plus timestamp/path/body and
integrity digest. The page validates allowlisted paths/body shapes and retains
network/5xx/malformed-success uncertainty across reload. Reload sends nothing
automatically; Retry saved action uses the exact stored command. Definitive
403/404/409/413/415/422 failures release that rejected request for review. Corrupt,
expired or unavailable storage blocks writes with reconciliation guidance.

Upload recovery stores only type/size/name/SHA-256 and stable upload/job keys.
After reload, the seller reselects exactly matching original bytes. After a valid
upload response, the pending intent atomically becomes the asset-backed job
command; a lost job response needs no second upload. Recovery lasts up to seven
days within the browser session and makes no cross-device claim.

Current session checks run before/after API calls and on focus/visibility return.
Changed actor, CSRF session or lost tenant read access clears all private page
facts and the `munimjee.v1.import-command:` prefix. Current read-only roles disable
all writes and saved retries; backend role/session/CSRF checks remain authoritative.
Terminal identity generations are rechecked after command/recovery digests and
upload-to-job digests before storage or private UI can be restored. Controlled
delayed-digest regressions cover all three waits. Shared auth cleanup/nav/main/runtime hooks are coordinator-owned and must be
verified in the composed checkout.

## Evidence and remaining gates

`backend/tests/browser/import_workspace.mjs` uses synthetic same-origin HTTP
fixtures and Chromium, blocks external origins, and makes zero provider calls.
`browser-results.json` records **150 passing checks**. It covers source permission,
raw byte/hash upload recovery, review/unknown/zero distinctions, stale revisions,
source XSS safety, current role/session/tenant fences, corrupt/unavailable storage,
rapid submit/poll races, full allocation totals, inactive payloads, lost draft
response/reload/same-body-key receipt replay, existing-source 409 reconciliation,
invalid receipts/previews, unsupported currency/combination limits, keyboard access
and 390px mobile overflow. Desktop/mobile full and focused captures are present.
These prove UI/transport behavior; they do not certify database/provider execution.

The dedicated actual native-page/role/CSRF tests collect and explicitly skip
without P01 configuration. The prepared `--native` journey uses native signup,
real protected APIs and actual migrations under a held P01 reset/migration lease.
Only source retrieval uses a protected synthetic worker hook. It now also creates
a private multi-SKU draft, loses the committed response, reloads/replays the exact
body/key, checks one canonical product, inactive persisted SKUs/confirmed stock,
existing receipt, checkout disabled and the store still unpublished. It has not
been executed in this worker environment: the disposable PostgreSQL lane is
unavailable, and shared Docker/services were not restarted or reprobed.

Run from `backend` with an isolated Python 3.12 environment:

```
python -m pytest tests/test_import_workspace.py -q
python -m tests.run_import_workspace_browser
# Only with the allocated P01 lane's explicit TEST_DATABASE_URL,
# TEST_LANE and TEST_DB_RESET=1 (no .env/database fallback):
python -m tests.run_import_workspace_browser --native
```

Use `PLAYWRIGHT_MODULE` for the available Playwright test module and optionally
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` for an existing local browser. Both modes reserve
only loopback port 4320, close only their own server, and must not run concurrently.
Actual mounted PostgreSQL/browser acceptance, final composed runtime packaging,
independent QA and physical-device/source-provider acceptance remain integration
or release gates. No production deployment, real provider request, customer
message or charge was performed.
