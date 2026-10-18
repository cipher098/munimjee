# Remaining V1 acceptance delta

18 October 2026. Frozen source **`e750e5a5a78da74390572d116f5c98649a7334a1`**;
application baseline `dd36b0dab568684d6c8ee6c66d47e27a76b9fca4`.
Ownership contract: `docs/v1-seo-contracts.md` at
`1f00b39a419cf1d47280edff020eb1c684593bb2`, read in the coordinator checkout.
The entire [go-live plan](../go-live-plan.md), existing audit and its 58-row matrix
were read. **V1 is not release-ready.** This supplement assigns no green score and
closes no historical row. It changes no product, shared plan, audit or migration.

The actionable [inventory](../artifacts/v1/acceptance-delta/inventory.json) contains
15 bounded work items with owners, source references, exact acceptance criteria,
independent next steps and separate external/operational gates. Its `coverage`
map retains all 58 V/A/G/M/X rows; overlapping references are not a progress count.
All 25 source references carry immutable Git commits, SHA-256 and line anchors.

## Work that remains code-owned

These are proposed next assignments, not permission for this documentation lane to
edit another owner's files. Existing local ownership takes priority.

| Item / owner | Frozen source finding | Bounded next work and completion evidence |
| --- | --- | --- |
| D01 — imports/Instagram; catalogue_commerce approves seam | `collect_claim` requires an injected owned-media provider; worker `_drain` supplies none. This is an implementation gap independently of credentials. | Agree adapter/credential/error contract with the local import owner first. Wire supported owner-bound retrieval through worker/runner; use fake transport for account/media mismatch, expiry/revocation, timeout/rate-limit, bounds, cancellation/restart, multi-product unknown facts, provenance and replay/override tests on migrated schema. Actual authorized retrieval is a later gate. No remote CSV/parser/API/schema edits. |
| D02 — channels + catalogue; AI QA | Activated products deliberately hand off; current-SKU answers are missing in both Instagram and WhatsApp paths. | Add read-only current public SKU fact resolution and send/resume recheck. Test variant ambiguity, unknown stock, changed price/stock/mapping, tenant isolation, context switches, takeover/pause/consent/window and deduplicated unknown-reel resume. Never remove the legacy safety guard just to obtain replies. Real delivery remains separate. |
| D03 — operations/QA + business | No approved pilot envelope or measured latency/error/backlog/mobile report is established. | Build bounded fake-provider synthetic load/report tooling now; keep missing rates/budgets MISSING until approved. Record p50/p95/p99, errors, queue age/depth/drain, recovery, source/runtime/seed and failure thresholds; distinguish lab from field/device data. Execute only on allocated runtime. |
| D04 — operations + domain owners | A comment cap already exists (250 per seller/action kind/hour); it is not a complete pilot usage/alert system or a Meta quota. | Inventory existing controls, then define tenant usage/overload behavior and redacted stuck/unknown-operation signals. Verify concurrent/replayed actions cannot bypass limits or duplicate effects. Review alert ownership, acknowledgement/escalation, pause/recovery and support runbook against agreed pilot limits. |
| D05 — QA/runtime + domain owners | Durable fixture/recovery slices exist; combined process/Redis restart proof remains missing. | Add bounded isolated fault checkpoints across imports, ingress/sends, payment creation, stock and parcel updates. Assert no duplicate effects, retained unknown outcomes and pending/consent/lease reconciliation. Run the three historically skipped Redis cases on a separately allocated namespace; never restart shared services. |
| D06 — local onboarding/foundation + acceptance | `onboarding_view` permanently reports False and catalogue/storefront action-required. | After local composition, derive readiness from authoritative persisted state, retaining genuine external blockers. Prove complete fresh self-service and support-assisted journeys through native UI/API, logout/resume, revoked support and no DB edits. Prepare QA fixtures now; local owner owns implementation. |
| D07 — independent QA + storefront/channels | Historical fragments do not constitute the final matrix or full AI/accessibility coverage. | Maintain deterministic AI/current-SKU/mixed-language/malicious-source fixtures with predeclared soft thresholds; hard limits are zero tenant disclosure, invented price/stock or unauthorized financial action. All three themes need full purchase/state/error journeys at 360/390/768/1440 and keyboard/focus/labels/contrast. Pin final candidate and app/harness hashes. |
| D08 — business + commerce/migration | Frozen canonical checkout is IN address/six-digit postcode and INR only. | Confirm Dharaa destination/address/shipping/charges/payment/display requirements before assigning code. If migrating, implement and test each supported destination and explicit unsupported cases; otherwise preserve the existing international purchase route or defer that migration. Conditional scope is not waived. |

D01 needs an explicit handoff because import code overlaps the local CSV owner.
D02, D03, D04, D05 and independent D07 fixtures can progress without provider
credentials once their files/contracts are assigned. DB/process execution needs a
separately allocated isolated lane. D04 requires a control inventory before claiming
absence: existing caps, durable receipts and uncertainty handling must be preserved.

WhatsApp currently accepts WABA/phone/token through native `connect` UI/API.
E01 therefore includes a supported-self-service-flow decision: confirm the official
connection mode/account eligibility, identify any missing client/server signup
code, and assign it to channels before canaries. A credential form does not prove
supported self-service signup; unknown provider requirements are not invented here.

## Local and parallel ownership — no duplicate implementation

| Item | Reported delta relative to frozen source | Required handoff / acceptance |
| --- | --- | --- |
| L01 CSV — catalogue_commerce, wholly local | Ongoing; absent from e750 source. Earlier remote CSV assignment is superseded. | Product per row; stable document UUID + product_ref; reserved `0053 → 0052`. Exact local commit, bounded validation/replay/overrides/provenance, private draft review and ordered migrated/native evidence. No remote parser/import/UI/schema/model/migration writes. |
| L02 support — local foundation | Explicit expiring grants/global sales; local `0051` ongoing. | Exact source + scoped, expiring, revoked/foreign denial and audited credential-safe support use; complete assisted journey. Board assignment alone does not grant access. |
| L03 customer links — local CRM | Verified identity/provenance/history; local `0052` ongoing. | Exact source + verified link basis, tenant denial, revoke/audit and unified order/conversation history; matching name/phone is insufficient. |
| L04 analytics — local analytics | **Reported integrated locally at `3556850`; not integrated into e750.** `git cat-file -t 3556850` found no object here. No fetch/source/test review performed. | Obtain full commit/evidence and verify composition. Known dataset must reconcile visits/views/enquiries/checkout/placed/paid/cancelled/revenue/conversion/automation, excluded test activity and unknown attribution; payment authority/COD/refund/denominator definitions stay explicit. No completion credit from report alone. |
| S01 SEO — publication + independent QA | Parallel implementation; not part of frozen e750 evidence. | Review exact stable source and independent adversarial evidence before composition. Sitemap/explicit-inventory redirects can close a bounded infrastructure gap only. |

The source/local-report distinction is deliberate: absence at e750 does not assert
that another checkout lacks the feature now. This lane did not inspect or merge
local uncommitted/team changes. Coordinator owns composition and migration order.

## Full V12 remains a migration gate

Retain default-off installation, configured canonical origin, active published-only
sitemaps and fail-closed redirect validation. Default redirect inventory is empty;
synthetic `.example.test` mappings prove infrastructure behavior only. Full V12,
A21 and M07 require the **actual supported legacy URL inventory**, confirmed source
ownership/domain/provider routing authority, canonical destination reconciliation,
old customer order-link compatibility and a migration/rollback rehearsal. Review
third-party subdomain authority explicitly. New SEO code cannot retroactively pass
those requirements or authorize DNS/routing changes.

## Execution and external gates remain distinct

- R01: reviewed CI/package/restore source already exists at e750. Run final actual
  migrated PG16/held-lease proof and affected mounted journeys; build/smoke the new
  locked image on amd64/arm64. Source-archive determinism is not OCI execution.
  Reuse guarded dual-lane restore and schema/data reconciliation; separately prove
  prior/current application/worker switch or forward fix preserves newer orders,
  reservations, identities and pending work. A generic newer-order SQL probe is
  insufficient. No destructive downgrade or old-backup overwrite.
- E01/G3: current Meta supported accounts/permissions, owned media, authorized
  comment/DM/WhatsApp recipients and delivery/revoke/reconnect evidence; actual
  Razorpay test SDK/CSP/domain/callback/webhook/capture and failure/cancel/late paths;
  private ParcelDesk D1/TLS/machine trust, confirmed existing-parcel refresh and
  permitted update. Uploaded media and fake transport remain separately labelled.
  Shipment booking/new courier APIs remain outside V1.
- E01/X05/G4: real iPhone/Android login, checkout and camera/touch, approved seller
  media/policies and final self-service/assisted acceptance. Viewport emulation is
  not physical-device validation.
- G5/G6: named pilot scope/limits, operational owner, monitoring/support, final backup,
  owner approval and controlled production rollout/reconciliation. No production
  cutover or real-provider action is performed/authorized by this supplement.

Docker unavailability is accepted without another probe. Saved hosted billing-lock
zero-step failures remain execution blockers; no retries or billing changes occurred.
These boundaries do not convert D01–D08 or local product work into external-only gaps.

## Verification and final-candidate handoff

Run the read-only supplement verifier from repository root:

```sh
python3 artifacts/v1/acceptance-delta/verify.py
python3 -m unittest discover -s backend/tests -p test_v1_release_audit_evidence.py -v
```

Results are in [verification](../artifacts/v1/acceptance-delta/verification.json)
and [historical audit checks](../artifacts/v1/acceptance-delta/historical-audit-checks.txt).
These are evidence-integrity checks, not new product acceptance. No DB/provider,
Docker, DNS/routing, hosted retry, shared restart or production operation was run.

At e750 the existing historical verifier already reads recorded Git blobs for
final-gates/native/payment/recovery hashes. Preserve this correct historical
semantics when local composition changes current files. Verify new candidate
acceptance separately: exact final SHA, local migration chain, affected APIs/UI,
actual migrated tests and app/harness before/after hashes with capture manifests.
For screenshot-only import-harness attribution, the historical audit's minimal
refresh is the 47-check native import runner; additional local product changes need
their own affected coverage. Do not relabel the historical 1,417-pass PG16 run or
896-pass/562-skip remote regression as proof of later source.

First dispatch bounded D02/D03/D05 or missing D07 fixtures after file allocation;
resolve D01 import seam and local L01–L04 source handoffs in parallel. Compose only
reviewed exact commits, then refresh affected acceptance rows and retain all
provider/device/domain/operational gates. No aggregate release score is provided.
