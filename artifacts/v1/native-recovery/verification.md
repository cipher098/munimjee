# Native recovery verification

Base: `2d70c44`. Runtime feature: `7ed507d947fada2520a9dc76eaef148f6cd32f71`
plus `04f9bc07f9631318ecabe323ceb14e62cac46677` (legacy publication held before
POST). Test/capture followups: `6c54e33`, `689b7c4`. No runtime changes occur in
those test-only followups. The final runtime finish is
`3693c967157a50a0309bbeda60189a9e5ce5ca82`: human frozen-fact recovery summaries,
with the exact replay envelope unchanged. The final 30-check run records that
exact source SHA and UI hashes. This is a local feature branch for integration;
central 0050/full-suite composition is checked separately.

## Independently confirmed findings

Source review confirmed the importer awaited its native guard without a final
fence check at JSON/raw-upload dispatch; theme success accepted any shaped record
and then cleared intent after a GET; unclassified 4xx erased uncertain actions.
The parent independently reviewed 7ed507d and found no additional bounded source
blocker, and suggested the implemented pre-POST legacy publication hold.

`baseline.txt` / `baseline-results.json` record **3 baseline reproductions** on
actual app.main and actual migrated PostgreSQL through 0049. The browser serves
the two original JS files directly from `git show 2d70c44:backend/static/...`.
Original theme code clears the saved command after a well-shaped old 200 even
though the real write committed. Original import code dispatches JSON and raw
upload after a terminal local fence.

The fence reproduction uses a test-only wrapper that first awaits the **real**
native session guard and then queues the concurrent terminal fence as a
microtask before its caller continues. It changes no native session, API/domain
result or provider transport. This is deterministic scheduling evidence, not a
claim to have reproduced a spontaneous server revocation event. The local
backend actually receives the baseline post-fence request; the fixed source
sends zero such requests.

## Actual mounted recovery matrix

`browser.txt` / `browser-results.json`: **30 passed** on the actual application,
real native signup/session/CSRF, real 0049 migration chain and real persisted
import/theme commands. UI source hashes and checkout SHA are recorded in JSON.
Only loss/intermediary/old-body responses and the scheduling wrapper above are
controlled. Mutations first reach the real backend where the case calls for a
post-commit failure. No API/domain writer is mocked.

Coverage:
- Draft save and publication: old 200, wrong draft/public config, wrong published
  revision, dropped response, and unclassified 409/422 after a real commit.
- A correct acknowledgement followed by an older GET keeps the exact command.
- Existing published snapshot remains bound while saving a later draft.
- Reload never automatically POSTs; explicit retry uses identical body/key and
  confirms the original persisted result/version.
- Legacy format-1 saves recover with their original body. A legacy publication
  without its original config stays preserved and sends no further POST.
- Jobs: unclassified 403/404/409/413/415/422 and dropped response after a real
  commit, followed by same-key retry and exactly one persisted job.
- Uploads: unclassified 409/422/drop after actual asset persistence, followed by
  reselecting exact original bytes and same upload key; only one job is created.
- Real typed stale theme/importer rejection permits explicit refresh, with no
  new accepted command; unclassified conflicts remain held.
- JSON mutation, JSON read and raw upload all send zero requests after the
  controlled concurrent fence. Private state and pending storage clear.

Command from this worktree root, with the integrator's explicitly allocated
TEST_DATABASE_URL and `TEST_LANE=parcel_w3 TEST_DB_RESET=1`:

```
PYTHONPATH=backend python -m tests.run_native_recovery_browser
```

P01 exclusively leases/resets the approved lane and runs actual Alembic through
0049; no create_all/fake-chain shortcut. The harness sets native flags before
importing actual app.main and owns only 127.0.0.1:8156. Workers and provider
networking remain off. External browser requests are denied. Baseline mode uses
`--baseline`. A focused `--preview-only` check verifies the embedded private
heading is visible and recaptures the recovery viewports; this is not a full
preview visual certification.

## Actual typed-error HTTP checks

`backend.xml` / `backend.txt`: **3 passed**, no skips, one existing Pydantic
class-config deprecation warning. Actual app.main + P01/0049 checks prove theme
and importer receipt replay precedes stale revision rejection. Typed stale
rejection produces no extra theme command, candidate change, import audit,
bridge receipt or Product; idempotency collisions remain unclassified strings.

```
PYTHONPATH=backend python -m pytest backend/tests/test_native_recovery_http.py \
  -q --junitxml=artifacts/v1/native-recovery/backend.xml
```

New fixtures use synthetic `@example.com` identities and valid `shop.example.com`
source URLs, without mail or retrieval. Initial use of inherited `.test` fixtures
was rejected by real email/URL validators before domain work. Those shared
fixtures were not changed here; the integrator independently fixed that drift.

## Separate controlled HTTP regressions

- `theme-http-mock.txt`: **6 passed**, zero failures.
- `import-http-mock.txt`: **164 checks passed**.

These use the actual static modules with synthetic HTTP and are **not** DB or
provider evidence. The importer mock ran on an owned static server at 8155,
preserving the original 4320 default and existing previews. An initial mock run
hit an old role-downgrade click race;
`import-http-mock-initial-failure.txt` preserves that failed run. Later generic
4xx expectations were also aligned before the passing rerun; the initial failed
run did not reach those assertions. Associated
regression fixtures now assert the new typed rejection contract, direct queued
submission guards and retention of every unclassified error.

## Render and review scope

- `desktop-import-unconfirmed.png`: full desktop, uncertain action retained,
  human summary of the frozen website/source permission, competing new operations
  withheld. Wire UUIDs and request JSON are absent; browser assertions verify
  the summary while existing exact-replay checks still pass.
- `mobile-publication-unconfirmed.png`: actual 390×844 recovery viewport with
  explicit uncertainty and same-action retry.
- `mobile-confirmed-publication.png`: actual 390×844 confirmed publication
  viewport after exact retry; no store visibility/checkout claim.

Capture waits verify the embedded private heading separately. Mobile captures
are scoped viewports, not blank offscreen full-page iframe evidence. No HTML,
CSS, typography, palette or shared design files changed. The incumbent native
system is preserved; no new visual system or DESIGN.md repair is claimed.
One detector invocation on the two changed JS files is recorded in
`design-detect.txt`: regex-only, not a parsed-page accessibility certification.
Independent integrator review accepted the bounded source and theme renders,
then identified the importer wire-detail summary as one finish issue. The
requested textContent-only fix and refreshed desktop capture were independently
scored resolved: readable frozen website/source permission, unchanged exact
command. Final bounded native recovery UI/source verdict: accepted. No additional
reviewer capacity or broader accessibility certification is claimed.

## Boundaries

Runtime edits are limited to the two assigned native JS modules and the narrow
receipt-first typed-error domain/API seams. No DDL, shared V1 client/main/package,
server registration, payment shell, provider permission or production service
changes. No real provider/customer/carrier call or deployment. Native 401 cleanup
still follows the shared privacy policy; recovery does not cross sign-ins.
Unclassified repeated errors and older unverifiable publication intents require
owner reconciliation; they never silently generate a new key. Private connector
deployment/D1/TLS/physical-device/provider acceptance gates remain
unchanged and outside this work.

## Service cleanup

The owned static mock server was stopped after its run. Before final evidence
commit, both 8155 and 8156 had no listening socket. Port 8155 is now reserved
for the integrator's full suite and will not be bound by this worker. The
separate central mounted check uses only 8156 and parcel_w3.
