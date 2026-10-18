# Independent onboarding comparison — 8ae97c2

Compared application source `8ae97c2d57c0efda5a03a41a469bf9447739ee72`
(runtime source `52fdda8`, matching native/readiness files) with frozen baseline
`abab30aaf1ab94052344b0ef21d05b3922f260dc`. No production file or migration changed
in this QA lane. Only the original QA commits were composed into this separate
worktree; old production source was not cherry-picked. The reported local
`789db95`/0056 integration was not tested and is not this source or a certified RC.

**Same 32 scenario IDs: baseline 22 pass/10 fail; follow-up 27 pass/5 fail.**
Both runners exit 1 because real UX assertions remain red. Unexpected origins,
API paths, websockets and page errors are zero; native source hashes before/after
match the compared commit. All HTTP responses, cookie transitions and data remain
synthetic. These are actual unchanged frontend/formatter tests, not mounted DB,
provider, physical-device, screen-reader or full accessibility acceptance.

## Exact change in outcomes

| Old failing case ID | Follow-up | Evidence and boundary |
| --- | --- | --- |
| `session-switch-401` | Pass | Terminal sign-in message appears and workspace is hidden; no fallback into another business. Old hidden cached-content distinction remains recorded in baseline. |
| `session-revoke-401` | Pass | Revoke denial fences the workspace and clears invitation bearer value. A backend write is not inferred from a synthetic denial. |
| `role-focus` | Pass | Returning focus causes a session read; viewer controls are disabled and team controls hidden. |
| `session-focus` | Pass | Focus-time session expiry hides workspace and clears prior profile/invitation values. |
| `cross-identity-error` | Pass | A-context marker is absent after sign-out and different user/CSRF/business B sign-in. |
| `keyboard-transition` | **Fail** | Keyboard signup still leaves focus at BODY outside the new workspace. |
| `logout-focus` | **Fail** | Keyboard sign-out still leaves focus at BODY outside sign-in context. |
| `contrast-focus` | **Fail** | Author-provided solid 3px keyboard `:focus-visible` outline remains 2.3955:1 against opaque white, below the scoped 3:1 criterion. |
| `startup-error` | **Fail** | Initial 503 leaves both panels hidden without an explicit retry/sign-in action. |
| `long-business-name` | **Fail** | Valid unbroken 160-character name still produces 3062px document width at 360px. |

The other 22 baseline passing scenarios remain passing after semantic calibration
of the existing lost-response case described below. No new scenario was added.
No new product failure is classified by this comparison. Remaining UX fixes belong
to the local onboarding/UI owner; the QA lane did not edit production.

## Required fixture adaptations

1. The actual readiness formatter now produces six steps and reads active catalogue
   counts, channel/control observations, storefront/policy and a fresh scalar profile.
   The exporter runs that actual formatter/local_channels code against synthetic
   zero counts, absent account/control/store rows, false checkout policy and an
   explicit profile row. Both role checks still execute against injected fake access.
   Six execute results/two scalar results are asserted. This reads no credential or
   DB data; configured/approval/delivery readiness is never invented. An extra message
   acceptance step remains incomplete in the source output.
2. The actual client now requires a readable `v1_csrf` cookie matching session JSON.
   The isolated context gets a matching synthetic cookie initially, replaces it on
   mocked signup/login/invitation-accept responses (including identity change), and
   clears it on mocked logout. checkedSession is not replaced or bypassed. There is
   no real persistent native session or credential in these fixtures.
3. Two 401 cases observe the **visible terminal access-error** region instead of
   requiring an old private error region to retain text. Workspace-hidden and private
   link/value assertions remain unchanged; correctly clearing old errors is not red.
4. Output defaults/validated arguments target `comparison-8ae97c2/`. The original
   baseline result, fixture, screenshots, log and verification remain byte-identical
   to original QA commit `a3a3d66`. Formatter-source freshness still fails before
   launching the browser when any exported source hash differs.
5. Synthetic profile save behavior mirrors the native writer's complete profile
   replacement, including business type/country and null optional values. The case
   records the full submitted/read/rendered state, not just the changed name.

## Lost-response calibration, not a product regression

The raw comparison initially returned **26 pass/6 fail** because the baseline case
required the literal conflict message in profile-error. Raw first-pass and traced
diagnostic results/logs/runner snapshots are preserved beside the final result.
Snapshots are forensic source copies, not scripts intended to run from that nested
artifact directory. `profile-lost-response.png` belongs to that calibration run.

Ordered existing-case observations establish the actual recovery behavior:

- First PUT with expected_version 3 changes the synthetic record once to version 4;
  its response is lost. The UI shows Failed to fetch and does not acknowledge success.
- Retry performs fresh session reads, then sends a stale expected_version 3 PUT,
  which is rejected with 409. It does not commit a second change.
- An actual frontend GET of onboarding returns the complete saved version-4 profile.
  The rendered name, type, country, email and null-normalized optional fields match
  that exact response and the synthetic authoritative record.
- Browser resource/status observations show a new Saved status after the fresh GET
  completes (final trace: responseEnd about 302.7ms, status mutation 304ms). No new
  saved acknowledgement precedes that read.
- Explicit manual reload returns the same full facts/version, with one synthetic
  commit and only the two prior PUT attempts.

The coordinator reviewed that evidence and approved classifying it as genuine fresh
authoritative UI recovery. Only the obsolete specific-409-message requirement was
replaced. Strict single-commit, stale-retry rejection, complete fresh-read/render
equality, acknowledgement timing and manual-reload invariants now gate the same
case. No backend idempotency or migrated-schema success is inferred from this fake
record. The original red calibration remains available for audit.

## Reproduction and commit separation

From this comparison worktree:

```sh
env -u TEST_DATABASE_URL -u TEST_LANE -u TEST_DB_RESET /tmp/munimjee-release-ci-py311/bin/python backend/tests/independent_onboarding_experience_qa.py
node backend/tests/independent_onboarding_experience_qa.mjs > artifacts/v1/independent-onboarding-experience/comparison-8ae97c2/run.txt 2>&1
```

Harness-only adaptation is `e0d819d18b185bfcf4a2e10466e2c8d6e3aa0c86`;
narrow reviewed semantic harness correction is
`a7282ed267d09b4f28b3b22dba24495f59a834b7`. Documentation/comparison evidence is
committed separately so coordination can cherry-pick it without replacing the
baseline exporter with a formatter specific to this newer source.

`comparison-8ae97c2/verification.json` records exact source/runner/fixture/artifact
hashes, source-only boundaries, command exits, baseline preservation, case-ID deltas
and calibration history. The recovery/security peer receives the exact committed
harness for read-only review. No DB was allocated, no ambient service or user browser
was accessed, and no provider call, customer send, charge or deployment occurred.
Full V01/V1 acceptance remains open.
