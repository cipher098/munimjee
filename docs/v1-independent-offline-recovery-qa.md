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
Browser peer original checkpoints are reviewed below; narrow onboarding harness followup remains pending. No release,
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
privacy/layout failures. A tiny committed owner followup will be inspected without
changing production or enlarging the original browser workload.
