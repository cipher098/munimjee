# Independent bounded offline recovery QA

Frozen application source: `abab30aaf1ab94052344b0ef21d05b3922f260dc`.
Date: 18 October 2026. This is a finite QA workload, not an agreed commercial
pilot traffic forecast, production latency SLA or soak test.

## Inventory and selected acceptance gaps

Read the complete `go-live-plan.md` and independent-experience QA ownership contract.
Existing coverage includes import claim lease/redelivery/cancel/retry units
(`test_v1_import_jobs.py`), actual migrated single/concurrent recovery and final
transaction fencing (`test_v1_import_jobs_db.py`, `test_v1_import_integration.py`),
resolver admission/late failures (`test_v1_wave2_import_fetch.py`), website response
byte limits (`test_v1_import_jobs_fetch.py`), ingress unknown-effect/recovery
(`test_instagram_ingress_worker.py`), and actual Parcel Desk recovery/notification
semantics (`test_parcel_tracking.py`). Actual DB/Redis cases are not allocated here.

Selected additional acceptance conditions: finite multi-job service replay during
in-flight fetches; cancellation leaving a leased row recoverable after controlled
lease expiry; queue recovery/drain without duplicate candidate identities; network
I/O outside session transactions; and transport admission remaining occupied after
caller cancellation, then recovering once outstanding bounded work actually ends.
These use actual import service/runner/fetcher modules with synthetic persistence
and transports. Synthetic lock/row storage is not PostgreSQL locking/persistence
proof. No provider, actual credential, DB, Redis, server or ambient service is used.

## Workload and budgets fixed before execution

- Service workload: 24 website import jobs across two synthetic tenants, at most
  four active fetch callers; eight duplicate deliveries while first claims are
  active; four caller interruptions followed by a controlled 61-second logical
  clock advance; recovery batches at most 20. Each source response is below 4 KiB,
  one structured product, unknown stock/options and synthetic facts. Overall
  safety deadline 5 seconds per scenario. No wall-clock lease sleep.
- Transport workload: burst of 12 callers against the actual four-slot transport
  admission seam, backed by manually completed `concurrent.futures.Future`
  objects. No worker thread, DNS or socket is started by this fake pool. Only four
  requests may be admitted; cancellation must retain admission until future
  completion; one subsequent request demonstrates recovery. Individual fetch
  timeout 0.2 seconds and per-response maximum 4 KiB, overall scenario 5 seconds.
- Memory evidence is structural: finite job/candidate/response counts, exact body
  byte bounds and retained-work slot ceiling. No RSS/heap production benchmark.
- Observe durations only for reproducibility; no performance acceptance threshold
  beyond harness safety deadlines. Expected real pilot volume remains MISSING.
- Peer browser harnesses: review committed originals read-only for intercepted
  network, deny-by-default origin handling, synthetic configuration/fixtures,
  source hashes, effect boundaries and whether assertions prove their claims.

## Results

Three new offline scenarios passed. The focused composition with existing import
job/service, website fetch and independent wave2 fetch tests passed **112 tests,
zero skips**, in 0.67 seconds. Two existing Pydantic/Starlette deprecation warnings
were observed. Per-scenario informational durations and exact workload counters are
in `artifacts/v1/independent-offline-recovery/scoped-results.xml`; the exact command,
source/runner SHA256 values and limits are in `verification.json`.

Observed effects: 24 jobs across two tenants produced exactly 24 fetches, drafts and
audit receipts after eight in-flight redeliveries; replay and an empty drain added
nothing. Four interrupted callers left running leased jobs and no candidates;
a logical 61-second advance let the actual runner drain batches 20/4/0, producing
exactly 24 unique drafts and audits. Interrupted jobs had two attempts and the other
20 had one. Fetches occurred after the fixture transaction exited. A 12-caller
transport burst admitted four and rejected eight; cancellation retained four slots
until the backing futures completed, then a new request was admitted.

The first development run exposed two fixture defects: NULL comparison handling in
the synthetic SELECT evaluator and cancellation cleanup before its gate. Both were
corrected without changing production. No application failure was observed in the
three selected scenarios. The fixture serializes synthetic transactions globally,
does not implement commit durability, rollback, real row locks, PostgreSQL scheduling
or actual crash recovery, and cannot certify those behaviors. A self-review follow-up wraps each complete scenario in a five-second asyncio
deadline and also awaits the resumed transport task during failure cleanup. The
four-fetch caller
ceiling is the load generator's explicit limit, not a production worker limit.
The fake Future pool exercises the real transport's admission logic without creating
threads or measuring network throughput. Existing shared byte tests cover response
size rejection; new evidence is finite response counts/slots, not process memory RSS.

DB, Redis, real process restart/persistence, provider, physical device and long-running
soak gates remain unrun. Expected real commercial pilot traffic remains **MISSING**.
Browser peer original checkpoints, narrow followups and separately fetched-source comparisons are reviewed below. No release,
production throughput or latency SLA claim.


## Independent peer harness review

Read-only review of original committed scripts, docs, result/verification JSON and
Git blob hashes; this reviewer did not rerun the browser scripts or modify peers.

| Lane / exact original | Peer-reported result | Independent conclusion |
| --- | --- | --- |
| Storefront `faec01614c27578afd38bef750b9dc2205ee7c98` | 69 pass / 6 red, exit 1 | No safety or assertion blocker found. All six painted-text overlap assertions support one shared P2 missing-photo bag defect across three themes and two phone widths. |
| Onboarding `d92406e2f2d62c7db859cd4d0bf0e91544c24376` | 22 pass / 10 red, exit 1 | No safety/effect-boundary blocker found. Visibility snapshots and independently viewed screenshots support the two scoped P1 frontend privacy/context failures; switch401 hidden-DOM retention is separately scoped. Two nonblocking repeatability/assertion followups are recorded below. |

Both Python exporters load unchanged test safety before application imports; all
exported identities, tokens/links, facts and counts are synthetic. Both browser
runners create fresh Chromium contexts with service workers blocked, fulfill or
abort every HTTP request, deny unexpected origins/paths and never use route
continue/fetch or browser APIRequest to reach an ambient service. Onboarding also
denies WebSockets. No fixture server, actual DB/provider call or user browser is
used. Unexpected traffic and page errors are empty in both peer reports.

All reported native/renderer/module hashes were compared independently to frozen
`abab30a` Git blobs. Runner/exporter hashes, every storefront HTML fixture hash,
onboarding fixture hash and formatter/capability source hashes matched their exact
committed records. Before/after application hashes agree. Full comparisons and
reviewed runner/exporter SHA256 values are in `peer-review.json`.

Independently viewed `catalogue-320-missing-photo-overlap.png` confirms superimposed
bag title/price text; `session-revoke-401.png` confirms the still-visible synthetic
profile and invitation link after denial; `cross-identity-error.png` confirms B's
profile with A's prior supplied error marker visibly retained. These do not prove
real backend-sensitive error content, an authorization bypass, actual provider
revocation, persistence, physical-device acceptance or complete accessibility.
The suites keep all product failures red and carefully scope contrast/focus claims.

Two narrow onboarding harness improvements were sent to the owner/coordinator:

- Its runner records fixture SHA256 but does not automatically compare the exported
  formatter/capability source hashes to current source before execution. Current
  committed hashes independently match `abab30a`; future reruns should fail fast
  if stale DTO fixtures are used with changed formatter sources.
- The coordinator noticed `logout-storage` preserves `public-checkout-fixture`,
  an arbitrary unrelated key. The current test proves unrelated-key preservation;
  using the actual `munimjee.checkout.v1:<slug>` prefix from
  `frontend/storefront/src/checkout-attempt.js:15` will make the public namespace
  compatibility assertion precise.

These are test repeatability/fidelity improvements, not reasons to hide the real
privacy/layout failures. The tiny owner followup was subsequently reviewed below without changing
production or enlarging the original browser workload.


### Baseline onboarding followup reviewed

Committed `a3a3d6651121276d6b4aa289d7980e24992da6c2` resolves the two
nonblocking harness followups: source hashes are compared before browser launch
with bounded repository-relative paths, and logout tests the real
`munimjee.checkout.v1:synthetic` prefix. Nominal synthetic emails were also changed
to `example.com` so they conform to native validators. Independent blob checks
confirm the same 32 IDs/outcomes (22 pass, 10 red), unchanged `abab30a` native and
formatter source, and exact runner/fixture hashes. No application failure was hidden,
no new browser scenario was added, and this reviewer did not rerun the browser.

The coordinator subsequently supplied a **separate** fetched snapshot
`8ae97c2d57c0efda5a03a41a469bf9447739ee72` (runtime delta `52fdda8`). Its
onboarding comparison will receive a distinct review record when committed.
The baseline results above continue to describe `abab30a`. An unfetched local
`789db95`/migration 0056 report is not this review's source or evidence.


## Final independent review of fetched-source comparisons

Both comparisons below target only `8ae97c2d57c0efda5a03a41a469bf9447739ee72`
(runtime delta `52fdda8d84f261841a44ef6a84e38e78cd93f237`). Read-only Git blob,
script-diff, hash, artifact and semantic review found no safety/effect/semantic
blocker within their recorded synthetic scope. This reviewer did not rerun the
browsers or change their scripts. Baseline `abab30a` evidence stays historical.

**Storefront:** harness-only `51f24801a5beb7f39ee57f8739301c633b056272` and
separate docs/evidence `12c85209883825892e874dab7e68ddf3c2cd3a91` change only
trusted owned output paths. The assertion tail is byte-identical to the original;
all 75 names/outcomes match (69 pass / six cart-overlap reds). All 20 application
hashes match exact `8ae97c2`, fresh HTML fixture hashes match, and all 29 original
artifact/document files are preserved. There are zero page errors/external origins.
The 153 unhandled POSTs target only same-origin `/activity/contexts` and are denied
before any server. Activity coverage is **MISSING**: no successful, disabled or ready
activity response was fabricated, and these denials are neither activity success
nor a standalone product defect. The UI observations are bounded by denied optional
activity traffic.

**Onboarding:** harness-only `e0d819d18b185bfcf4a2e10466e2c8d6e3aa0c86` plus
`a7282ed267d09b4f28b3b22dba24495f59a834b7` and separate docs/evidence
`9642527196f2e80b0a0effd69678949be34074af` retain the same 32 IDs. The final
result is 27 pass / five real UX reds; raw 26/6 lost-response diagnostics remain.
All native, formatter and verification source hashes match exact `8ae97c2`, all
recorded artifact hashes match, and original baseline files are preserved. The
actual six-step formatter runs against absent/zero fake readiness rows; synthetic
readable CSRF cookie issuance/clear models the new client guard without replacing
it. Terminal 401 messages move to the visible sign-in error region while workspace
and private-value fencing assertions remain.

Five former failures now pass: business-switch401, invitation-revoke401, role-focus,
session-focus and cross-identity error. Five genuine failures remain: keyboard
entry focus, logout focus, scoped focus contrast, startup503 recovery action, and
long-name mobile reflow. There are no new classified product failures.

The existing lost-response case legitimately self-heals. Independent trace review
confirms exactly one synthetic commit; two expected-version-3 PUTs, with the retry
rejected409; actual frontend GETs returning identical full version-4 facts before
and after manual reload; exact rendered profile equality; no extra PUT on reload;
and a new Saved mutation at 304ms after the fresh GET responseEnd at about302.7ms.
Removing only the obsolete literal409-message requirement retains stronger
facts/effects/read-timing invariants. This certifies the bounded synthetic UI
recovery scenario, not actual database idempotency or durability.

No new scenarios, production files, schema, migration, provider, credentials, DB,
Redis, ambient service, user browser, customer message, charge or deployment were
added by this review. Runtime789db95/0056, actual migrated persistence/restart,
physical devices, full accessibility, provider acceptance, real pilot envelope and
soak remain outside this evidence. Exact hashes/mappings are in `peer-review.json`.
