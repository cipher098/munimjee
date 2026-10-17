# V1 seller import workspace

18 October 2026. Worker `codex/v1-import-workspace`, based on verified wave-2
`aa6ac940ef877a8a37baac39afec44268b49f84e`. No migration, provider mutation,
publication, stock write, application service/model change or production action.

The private page at `/v1/businesses/{business_id}/imports` requires the native
feature gate, `v1_user` sign-in and current `catalogue.read` membership. Its static
shell carries no seller facts and returns `Cache-Control: no-store, private` and
`Referrer-Policy: no-referrer`. The API remains the authorization authority;
every write uses existing `catalogue.write`/native CSRF dependencies.

The rendered local study is `artifacts/v1/import-workspace/design-study.html`
and `design-study.png`. It was reviewed before the main UI implementation; the
integrator also reviewed it. Source cards sit above job activity and candidate
review. Desktop keeps the lists beside details. Mobile stacks the sections,
keeps the list scrollable and scrolls to the chosen review panel.

## Operating behavior

- Website import requires explicit seller permission and a public HTTPS source.
  Original JPEG/PNG/MP4 uploads are bounded at 5,000,000 bytes, with explicit media
  permission. Uploads use a thin raw-byte transport with current shared CSRF,
  same-origin credentials, no-store, redirect rejection and 401 cleanup. They
  are never passed through the shared client's JSON body serialization.
- Job state, attempts, candidate count, revision and safe error code come from
  durable APIs. Pending means waiting for worker progress; no ETA or successful
  extraction is inferred. Eligible cancel/retry actions carry expected revision
  and immutable idempotency keys. Server backoff and its three-attempt limit
  remain authoritative. Provider-pending retry is withheld because capability
  must be resolved externally first.
- Jobs and candidates use bounded 50-record cursor pages. Automatic job checks
  stop after twelve checks, increase delay to at most fifteen seconds, back off
  further on errors, pause while hidden and do not replace candidate edits.
  Refresh explicitly reloads current candidates and replaces unsaved edits.
  An epoch/cursor check discards polls that finish after refresh/pagination.
- Review preserves extracted source evidence and seller overrides separately.
  Text is rendered with `textContent` or form `.value`; source URLs are displayed
  as text. No imported HTML is executed and no arbitrary source media is loaded.
  Unknown price/stock/options stay unknown. Zero stock and an explicitly empty
  options list are distinct reviewed choices. Structured option names/values,
  decimal price/currency and integer quantity are edited through typed fields.
- Saving factual changes and approving are separate requests. Approval requires
  five explicit confirmations and resolved title, price, stock and options.
  Rejection requires a reason. Stale revisions show a conflict and require
  refresh; no automatic merge/review decision occurs.
- Instagram source creation is disabled, with truthful provider capability copy
  and original-media/website alternatives. Existing failed records decode the
  actual `provider_capability_pending` code; no scraper, invented success or ETA.
- Approval alone never creates a catalogue product. The allocation adapter
  contract is absent at this checkpoint. Approved candidates show an explicit
  pending handoff and a catalogue link for manual reviewed draft preparation.
  Do not label that link as automatic transfer. No activation/publication UI is
  added here.

## Recovery and identity fencing

Every mutation is preserved in session storage before sending. One preparation
lock prevents rapid repeated submissions allocating competing command keys.
The versioned envelope includes actor, business, SHA-256 of the sign-in CSRF
secret, timestamp, request path/body and integrity digest. Destinations and body
shapes are allowlisted. Corrupt, expired or inaccessible storage blocks new
writes and surfaces reconciliation guidance. Network failures and 5xx retain the
exact request/key across reload; no request is sent automatically on reload.
Definitive 403/404/409/413/415/422 responses clear that rejected request and let the
operator review server state before forming another decision.

Upload recovery persists only original media type, byte count, filename,
SHA-256 and stable upload/job keys. Original bytes are never stored in the
browser. After reload the seller must reselect exactly matching bytes; a name
alone is insufficient. Once an upload result is validated, the upload intent is
atomically replaced with the stable asset-backed job command before its POST.
A lost job response then needs no second upload. Recovery is per browser session
and retained for up to seven days; it is not a cross-device recovery claim.

Session checks run before/after data requests and mutations and on window
focus/visibility return. A changed user, CSRF session or lost business access
hides private UI, clears forms/results and clears this page's import command
prefix. Current read-only roles disable all writes, including saved retries.
The backend independently rechecks current authority on every request.

## Required integrator hooks

These are deliberately not edits to shared files owned by the integrator:

1. Import `app.api.v1.import_workspace.router` and mount it in `app/main.py`.
2. Add `import_workspace.html`, `import_workspace.css`, `import_workspace.js` to
   the runtime packager's `STATIC` allowlist in `scripts/v1_runtime_package.py`.
   The baseline package does not include them. Existing package/image results
   must not be described as certifying this new page until rebuilt and checked.
3. Add `munimjee.v1.import-command:` to shared private cleanup alongside
   `munimjee.v1.catalogue-draft:` for login, signup, invitation acceptance,
   logout, logout-all and 401 in `backend/static/v1_client.js`. Local page checks
   already clean up on detected session changes; shared cleanup is needed even
   when a different native page performs sign-in/logout. Do not touch public
   customer checkout recovery keys.
4. Link imports from the native business/catalogue navigation as appropriate.
5. Freeze the real reviewed allocation adapter contract before adding an
   automatic handoff button. No guessed endpoint/schema is emitted by this UI.

## Verification

`backend/tests/browser/import_workspace.mjs` currently passes **56 behavioral
Chromium checks** using synthetic same-origin HTTP mocks, with zero provider
calls. Cases cover source permission, typed fields and unknown/zero distinction,
separate approval, source XSS safety, same-key lost-202 replay after reload,
raw upload lost-201 recovery and exact-file fencing, upload-to-job transition
with lost-202 recovery, stale revisions, viewer/current-role downgrade,
changed session during response, raw-upload 401 cleanup, corrupt/unavailable
storage, rapid submit fencing, retry limits/provider gate, late-poll discard and
390px mobile overflow. Desktop/mobile captures and machine-readable results are
in `artifacts/v1/import-workspace/`. These are UI/transport proofs, not database
or live provider acceptance.

The new native page/role/CSRF tests in `backend/tests/test_import_workspace.py`
collect successfully and report **3 skipped** without an explicit P01 lane. No
DB URL is guessed and no schema is created from ORM metadata. The dedicated
`--native` browser runner applies actual migrations under a held P01 lease,
uses native signup and real protected APIs, exercises lost-response replay and
review, and invokes `run_job` only through a test-only protected synthetic
fetcher hook. This native script is prepared and syntax checked but has **not
been run** by this worker; actual migrated DB acceptance remains pending.

Run from `backend` using this worktree's isolated Python 3.12 environment:

```
../.venv/bin/python -m pytest tests/test_import_workspace.py -q
../.venv/bin/python -m tests.run_import_workspace_browser
# With explicit TEST_DATABASE_URL, TEST_LANE and TEST_DB_RESET=1 only:
../.venv/bin/python -m tests.run_import_workspace_browser --native
```

Set `PLAYWRIGHT_MODULE` to the installed Playwright test module when it is not
available under `frontend/storefront/node_modules/@playwright/test/index.mjs`.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` optionally selects the existing local browser.
Both browser modes exclusively use port **4320** and close only the process they
started. Do not run modes concurrently. Existing previews/services are preserved.

Python compile checks and Node syntax checks pass for owned files. Shared route
mount, package inclusion/cleanup changes, native migrated DB/browser results,
live source/provider consent, approved draft handoff and physical-device
acceptance remain integrator/release gates.
