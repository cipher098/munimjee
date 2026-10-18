# V1 execution status

Updated: 18 October 2026. Coordinator branch: `codex/v1-integration`. Verified first-wave foundation: `7de7cd6`; preserved application baseline: `e7694ff`. This is a bounded implementation milestone, not full V1 acceptance or a production release.

## Wave7 current composition and pending gates

Prior verified/pushed checkpoint `abab30a` remains the accepted complete actual0053
baseline: 1950 passed,8 documented skips, plus native-import47/CSV74/SKU5 mounted,
SEO28 mounted HTTP, locked315-file arm64 image and separate restore53 evidence.

The frozen current actual0055 composition `3820d14` completed on the new disk-backed
PG16 lane with **2325 passed,2 failed,8 skipped in982.14s**. This is not acceptance.
Both failures are fixture compatibility: the new tenant FK rejects a deliberately
foreign comment-action row, and a V1-only nullable activity field was forwarded
into the legacy checkout schema. Raw log/XML are retained in
`artifacts/v1/integration/wave7/full-0055.*`; corrections retain the DB rejection
assertion and the independent legacy-writer test. A fresh complete gate is required.
No old tmpfs database is used.

Activity0054 is composed with shared public-shell/new-order-only provenance and
ungated bounded retention cleanup. Central actual customer-shell8 journeys and
retention/startup13 checks pass; owner final74 Python/19 mounted/28 Node remains
separate. Channel producers remain null/uninstalled. Owned Instagram through
5141177 is composed: isolated final467 checks and33 mounted checks pass on new
PG16; exact private-byte/provenance and late-authority findings are fixed. Both
provider capability gates remain false. Documentary principal/type/missing-original
compatibility followup is isolated and not covered by those prior results.

Comment safety0055 is reviewed/composed through88882f7: owner92 checks plus a
5-check tail (one overlapping expanded case) pass on actual0055. Native comment
management and durable inferred-WA visibility are owned next in0056, not complete.
Channel/session repairs through0f5e5f0 are reviewed/composed:126 focused
actual0055/mixed checks,25 actual-main browser checks and17 controlled-JS checks
pass. Native onboarding through52fdda8 is reviewed/composed:190 focused
(170 synthetic provider/parser/transport +20 native actual-DB) and6 actual-main
browser journeys pass. Session/role changes discard private results and staged
invitation/session writes roll back before commit. Local setup now advances from
current facts; authorized messaging acceptance remains explicitly unavailable.
Their confirmed failing-before-fix source/HTTP repros remain preserved.
Native comment0056 service/schema has an initial134-pass actual-chain gate;
final preview/browser/source review is still underway. Current composition is
not covered by the older2325-pass run. No later full-suite, runtime-image, release,
provider entitlement or live-delivery acceptance is implied.

DB-heavy work is serialized on disk-backed55443 only. Catalogue owns channel
hardening and compatible legacy WA generation writers; integrator owns native
workspace/readiness and composition; social owns0056 and independent review.
Remote mobile/accessibility/offline QA dispatch is now confirmed active after the
connection recovered; no result is credited before its exact reviewed handoff.
Exact ownership is in `docs/v1-wave7-contracts.md`.

## Wave6 verified bounded checkpoint

Test-infrastructure interruption,18 October08:16UTC: the old dedicated PG16
container's1GiB memory cgroup held RAM-backed PGDATA (observed1.7GiB retained
data/WAL), and a signal9 backend termination triggered recovery. The full
`0e658fc` gate was interrupted with1278 passed/8 skipped/72 migration-fixture
errors; it is **not acceptance**. Raw full logs/XML and cgroup/container evidence
remain under `artifacts/v1/integration/wave6/`. Earlier completed gates below
remain separate. No old container/database/archive was modified or removed.
A new bounded2GiB disk-backed dedicated PG16 container uses loopback55443;
`wave6_integration` and `instagram_w6` are its guarded lanes. DB-heavy runs are
serialized across peers. The fresh disk-backed complete0053 gate passes **1950 tests,8 skipped,0 failed
in852.31s** at invocation `b608f6f` (runtime `0e658fc`; later status-only
commits do not change tested runtime). Five missing historical cassettes and three
Redis cases without an allocated TEST_REDIS_URL are the documented skips. No tests
resume on the unstable old tmpfs instance.

Base verified/pushed32de1ac. Reviewed release tooling, CSV0053 and SEO/legacy
redirects are composed locally; no new release claim. Actual0053
focused gate passes372 checks after repairing the shared native import fixture's
middleware/startup teardown (the initial361-pass/11-error run is retained). Actual
central app.main CSV browser passes74 checks; mounted SEO passes28 actual HTTP
checks (not a device/browser claim). The complete regression is now green. A new
315-file locked arm64 image from `b608f6f` passes all three offline startup/asset
modes with per-file hash equality, no network/DB attempt and CID-only cleanup.
Final central native-import47 and SKU5 mounted reruns pass on actual0053. Native
import pre/post application and harness hashes match. The activity owner final
newpayment_w6 gate also passes74 Python/19 mounted/28 Node, with shared integration
next; it is not part of this complete1950 composition. Current
trusted flags stay off by default.

SKU fact replies are reviewed and composed through8712dcc (owner runtime741a45b:
227 passed/3 existing Redis skips and5 mounted journeys). The reproduced first/last
product selection in conflicting buffered reels/reply-to turns is fixed by frozen
whole-batch agreement, including activation/rollout/vision crossover withholding.
The real failed-before-fix evidence is retained. The existing WA legacy guard now
uses a nonblocking savepoint/handoff under Account locks;2 migrated regressions
pass. Central complete acceptance and final5 mounted journeys are green. The rollout
stays off.

V10 owner-consented observed activity reserves0054 after0053. Peer source/API/UI
is independently reviewed within its bounded contract, with final new-lane checks
queued; public shell/order/producer/retention registrations are integrator-owned
and not yet installed. Uninstalled channel metrics remain null, not zero.
Owned Instagram integration is isolated atb5a3bb7 plusd69dadb/c4794bb fixes:
generation/CAS fences, atomic exact originals and private readers. The initial
new-disk lane404 checks and33 mounted checks pass atb5a; independent source review
then found optimized-assert integrity and late-authority gaps, fixed in source
with optimized checks. Final race/mounted reruns remain pending. Both retrieval
and carousel capability gates stay closed; official primary API compatibility is
now has an official documentation packet. It identifies unresolved principal
wrapper/account-type compatibility and unavailable licensed-audio originals; docs
do not clear a provider canary or enablement gate. Integrator owns the shared service/config/main/package and
legacy-writer seams.

V08 independent actual tests reproduce5 queued-comment safety failures
(pause/inactive/reconnect/post-claim pause/stale activated-product copy), with18
other safety episodes passing. This blocks broader V08 acceptance. Social owns
the reserved0055→0054 source repair under frozen tenant/generation/claim/audit
constraints. Native comment management and durable visibility for withheld
inferred WA followups remain separate code work, not provider-only gates.

Release-only actual0052 restore and current-create→old-read→current-read package
proofs are integrated as historical evidence, not relabelled0053 acceptance. The
new head compatibility review adds a retained CSV original/pending-job fixture.
A fresh dedicated0053 pair passes53 checks, zero skips, including actual dump/restore
and newer target-only order preservation; exact evidence is in
`artifacts/v1/release-rehearsal/local-pg16-w6/`. This new pair has no package-switch
proof yet. Hosted billing/nativeamd64,
old writers/browser routing and production remain open. Exact ownership is in
`docs/v1-wave6-contracts.md`, with final proof/failures in `docs/v1-wave6-validation.md`.
The prior Wave5 checkpoint remains preserved below.

## Wave5 verified checkpoint

Base `3082f1a`; ownership and consent/proof definitions frozen in
`docs/v1-wave5-contracts.md`. Integrator owns explicit owner-consented read-only
support grants and their separate assistance view (0051); catalogue owns truthful
order-cohort analytics (no DDL); social owns dual authenticated endpoint-control
consent and customer links (0052), plus independent support security review. All
workers remain GPT-6.1 Sol/high. Remote CI/restore/rollback/multi-architecture
rehearsal is independent and cannot authorize production changes.

Wave5 functional source `515c538` passes the complete actualPG16.15/0052 gate:
**1524 passed,8 skipped,0 failed in651.33s**. Five missing historical cassettes and
three Redis/P01 cases remain the documented skips. The initial1514-pass/seven-failure
run is preserved; all seven missing-native-asset packaging fixture failures were
fixed by d369656 and the complete rerun is clean. Focused97 and Node80 also pass.

Final actual app.main browser gates pass support31, analytics21, customer links14
and existing native import47. Native import records queried0052, unchanged pre/post
application and harness hashes and both capture hashes. Separate owner results and
initial failures remain preserved; counts are overlapping and not summed. Exact
sources, failure matrix and evidence paths are in `docs/v1-wave5-validation.md`.
Independent peer source/render/security reviews accepted the bounded slices; a
fresh additional reviewer was capacity-blocked and is not claimed.

Read-only owner-consented support grants and dual-inbound customer control proofs
are default-off; trusted support allowlist defaults empty. No implicit membership,
impersonation, source-history merge or provider/customer outcome is authorized.
Order-cohort analytics does not yet measure visits/conversion/automation outcomes;
missing sources and unknown test classification are explicit.

Release tooling remains isolated in codex/v1-release-integration. Its fresh-pair
PG16 dump/restore53-check run passes without skips and preserves a newer target-only
order; an actual old/current package journey is separate. A hash-locked arm64 image
passes three offline modes; the one amd64 cross-build attempt failed legacy-builder
platform metadata. Native amd64 and hosted CI (saved billing-lock failure) remain
open. No daemon change/prune, production restore or snapshot overwrite occurred.

Next code-owned work: reviewed CSV0053 (owner159 focused/74 mounted, central gate
pending), reviewed SEO/legacy redirects (central migrated/mounted gates pending),
authoritative activated-SKU fact replies, owned Instagram retrieval and an explicit
V10 first-party measurement contract. These are not all external permission gates.
Historical importer hash review resolved applicationdd36b0d versus screenshot-
harness47b1b83 attribution; the final47 rerun now records both hash sets. Real
provider approvals/canaries and physical-device tests remain separate.

## Wave 4 local integration

The current candidate composes native import review/allocation, persisted configuration
and publication of all three storefront designs, native payment credential settings,
reviewed parcel resume/closure/replacement, and a membership-scoped assisted onboarding
board. Contracts remain in `docs/v1-wave4-contracts.md`. Actual migration head is
`0050_v1_assistance`, following `0049_v1_storefront_settings` and the preserved
0048 parcel revision. Every implementation and review worker retains GPT-6.1 Sol/high.

The board provides current per-business readiness, assigned owner/manager, safe import
issue counts and explicit links into the existing workflows. Assignment and opening
are audited; ordinary membership never becomes support impersonation or global sales
access. Import approval still creates a private inactive product and preserves unknown
stock; design publication, product activation, storefront publication and checkout
policy remain separate controls. Native credentials are saved without a provider call,
and uncertain secret replacement requires manual re-entry with conditional revision.
Parcel review preserves old links/history and suppresses old queued notifications;
review itself sends nothing.

Current central evidence: **1,417 backend tests passed, 8 documented skips,
0 failures** on actual migrated PostgreSQL 16 in **541.55 seconds**; **77 Node**
checks passed. Mounted browser evidence includes **37 assistance**, independent
**36 payment settings**, and **29 native import/persisted-theme/COD**, **47 native import**, **20 parcel
review**, and independent **30 native recovery** checks.
Final records and exact sources are in
`docs/v1-wave4-validation.md`. The final `dd36b0d` image passes all three offline
modes and runtime hashes (286 allowlisted files, nonroot, no network/database).
Backend source is `257b273`; the subsequent importer presentation/test-only diff
has no backend or migration changes. Counts are not summed across overlapping
suites. These results supersede historical pending statements below.

No provider outcome, complete V1 or deployment is claimed. Analytics, explicit
expiring support grants, verified customer identity links, global assistance access
and the complete onboarding acceptance matrix remain visible scope.

## Wave 3 historical checkpoint

The following preserves the earlier verified checkpoint; Wave 4 above supersedes its
then-pending native import, theme, payment-settings and parcel-review statements.

Base `aa6ac940ef877a8a37baac39afec44268b49f84e` is preserved. Contracts and
ownership remain frozen in `docs/v1-wave3-contracts.md`; all workers use
GPT-6.1 Sol / high. Source through `dd44d89` now composes the reviewed bridge,
public payment shell and native ParcelDesk workflow. This remains local test
acceptance, with every new rollout flag off by default.

| Slice | Integrated source and evidence | Current limit |
| --- | --- | --- |
| Reviewed import bridge | `a085c71`, `5e43aac`, `a86867a`, `e4bac16`; central through `54a4a67`. Actual 0047 immutable tenant receipt, atomic explicit approval/private Product+SKU creation, exact known-stock allocation and provenance, same-key recovery across reimport. **37 focused actual PG16 checks**, no skips/failures. | Complete native import review/allocation UI and browser journey still pending remote integration. No automatic publication/activation or unknown-stock conversion. |
| Native transaction authority | `5b46137`: native catalogue/order mutations revalidate current session/capability before caller-owned commit, including lock waits and provider GET reconciliation. Business/Seller non-key locks avoid proven FK lock inversions. **83 focused actual PG16 checks**, no skips/failures. Final import-session mount guard `dd44d89` adds create/upload/review/cancel/retry wait-revocation rollback; the combined focused rerun passed **64**. | This guard requires writers to avoid internal commits/external sends. Legacy workflows retain their existing boundary. |
| Online payment handoff | Payment owner `04de4b3` integrated as `2a1dc60`, shared composition `1ac880a`. Purpose-separated ephemeral session capability, existing durable attempt/capture authority, SDK preparation before a new order command, exact interrupted/lost verification recovery and retained order method. **38 actual app.main/native/guest browser checks**, **61 Node**, **19 migrated projection/publication/bootstrap checks**. | SDK/provider are synthetic. Both SKU initialization aliases now enforce the new gate (`9729441`); native exact-provider reconciliation/recovery is now included in the 38-check browser proof, including selection and session privacy fences. Real SDK/domain/CSP and captured-payment canaries remain external gates. |
| ParcelDesk tracking | Owned `431f444`, `d46bb30`, `df5fc7e`, `8914fb0`, central registration `7cc0b18`; source-only connector `2f85e53`. Actual 0048, scoped HMAC/durable commands, order-first scan/confirmation, lease recovery/cache history and current-policy existing WhatsApp outbox hook. Central **25 actual PG16/two-service/startup checks** plus **18 actual production-bootstrap browser checks**. Connector **10 SQLite/HMAC/queue checks**. | Synthetic camera proves wiring; physical phone, private provision/D1/TLS transport and permitted real delivery remain open. Review-required link resolution/replacement UI is not implemented. |
| Existing storefront paths | Shared payment composition reran **25 actual COD browser checks**, **22 incumbent HTTP-mock/theme checks**, **66 actual native catalogue checks** after the session fence, syntax and **61 Node checks**. | Persistent seller theme configuration and public rendering still await actual remote 0049 integration; all-theme mock proof is not persistent-theme acceptance. |

Independent existing-worker source/render review reproduced a stale pending read
replacing a newer verified paid state, then verified the epoch fix keeps both
UI and stored confirmation paid. Parcel review fixed native session privacy and
courier-selection races; the final captures and delayed-preview regressions were
independently accepted. A fresh additional agent could not start because of the
thread limit; no such review is claimed. Raw central results are under
`artifacts/v1/integration/2026-10-18-wave3-*`, public payment captures under
`artifacts/v1/public-payment/`, and parcel captures under
`artifacts/v1/parcel-tracking/`. Overlapping counts are not added together.

At the Wave 3 checkpoint the actual migration head was `0048_v1_parcel_tracking`;
remote theme revision 0049 was still reserved. The full wave3 checkpoint through `1ac880a` passed **1223 tests, 8 documented
skips, 0 failures** in **363.48 seconds**, using actual PG16 migrations. The
payment alias/DTO followup `626d62f` is integrated as `9729441` after that
checkpoint; Final-source application `dd44d89` passed **1248 tests, 8 skips, 0 failures** in **377.61 seconds** on actual migrated PostgreSQL 16. The eight skips remain five missing historical scenario cassettes and three Redis cases blocked by P01. Raw final results are `artifacts/v1/integration/2026-10-18-wave3-final.{xml,txt}`. The refreshed `dd44d89` runtime image
passed three offline modes and all per-file/manifest hashes, with 258 allowlisted
files (39 static, 12 storefront); exact evidence is in
`artifacts/v1/runtime-package/wave3-final-*`. Earlier wave2 image hashes do not
certify new payment/parcel files. The original ParcelDesk and running application
remain untouched. No live provider call, customer send, paid transaction or
production deployment was performed.

## Integrated wave 2

This table preserves the earlier wave2 checkpoint. The current wave3 results above
supersede its then-pending payment/bridge/parcel statements.

| Lane | Reviewed source | Integrated behavior and limits |
| --- | --- | --- |
| Native identity/onboarding | Auth `87cc13f`, `6314f29`, `6b883f3`, `a395888`, `ed406a3`; current authority `38c3da0`, private browser cleanup `837b7b0` | Own-account signup/login, transactional Seller/Business bridge, persistent revocable native sessions, bound CSRF, invitations and roles, saved versioned profile and resumable checklist. Native staff never receive legacy seller tokens. Support grants remain denied. Legacy enforcement is separately gated. |
| Catalogue/orders | Domain `ed86ff9`, `7736c44`; workspace `95dae6f` integrated as `1518baf`; durable reload recovery `831aa9e` as `bdf8bce`; final browser composition `7675f36` | Private reviewed drafts, explicit current-snapshot activation, authoritative SKU reads/writes, separate store publication/checkout policy, stock reservation/release, protected seller order actions and native workspace. Durable unknown-payment creation guard uses synthetic transports. Existing legacy reservations are not silently migrated. |
| Channel operator | `9de66db`, `22a1595`, `beac174`, `7a95fc9`; evidence `b00a173` | Native queue/review/audit, current-policy replay eligibility, explicit no-replay closure, connection check/save/disconnect and OAuth binding. Activated SKU conversations hand off to a person. Unknown sends remain quarantined. Local account access is not provider approval or delivery proof. |
| Durable imports | Remote source through `64f2e4e`; central actual DDL/registration `c44f14c` | Durable job/draft/asset/audit persistence, bounded website JSON-LD extraction, DNS-pinned SSRF controls, original upload bytes, recovery/cancellation, override-preserving review and idempotent reimport. Native router and disabled-by-default periodic worker are composed. Seller import UI and approved import-to-catalogue bridge remain pending. |
| Storefront/QA foundation | Remote foundation through `2f70d45` and `e360ca1`; actual provider/COD `e8a7c3c` as `a9c5474`, bootstrap `8a42e54`, configured seller link `530f7e3` | Published activated-SKU server rendering, strict canonical API projection, COD checkout with exact same-key uncertain replay and protected session-held order status. Actual native-to-public browser journey is verified. Default presentation is catalogue; persistent seller theme selection and online payment UI remain pending. |
| Safety/integration | P01 plus `9402390`, actual head `0046_v1_import_jobs` | Exact disposable lane validation, blocked provider networking, held database reset/migration leases, actual PostgreSQL 16 migrations, private V1 no-store headers and default-off feature gates. No production actions. |

All implementation/review workers use GPT-6.1 Sol with high reasoning. Existing running application checkouts/services and the original Parcel Desk source remain untouched. The running checkout's plan was synchronized only for the first explicitly authorized documentation copy; current wave-2 edits stay in the integration worktree.

## Verification

Final product-follow-up combined backend result against application code through `7675f36`: **1090 passed, 8 skipped, 0 failed** in **247.82 seconds**, using the actual full PostgreSQL 16 migration chain. The separately added packaging suite then passed **10 pure checks**, and the final-source image passed **3 offline smoke modes**. The previous checkpoint through `f21cf55` passed 1072 with the same eight skips in 235.01 seconds; it is preserved as earlier evidence. Five skips are missing historical scenario cassettes; three Redis cases are intentionally unavailable under the P01 blocked-network pytest setup. Existing deprecation warnings remain. The earlier complete run found **1064 passed, 8 skipped and 3 failed**. Those three actual PostgreSQL 16 failures exposed retained ORM User/Membership authority after another transaction revoked or downgraded it. `38c3da0` now authorizes from fresh database values, also rechecking persisted session expiry/revocation/auth version and the legacy cutoff. The focused current-state/security/safety rerun passed **105 checks**; the prior auth/onboarding/identity/QA focused run passed **76**. An independent reviewer also reproduced current-role downgrade denial, preservation of unrelated dirty ORM fields, cached session/auth-version rejection and two concurrent atomic logout-all increments on its own actual PostgreSQL 16 lane; no substantive regression was found.

Independent integration browser checks on the actual mounted application, sequential leases on PostgreSQL 16 `auth_wave2` after the full 0046 chain:

- **16 native onboarding checks**: fresh signup, saved/resumed profile, conflict, CSRF, invitation role, delayed cross-business response handling and logout cleanup.
- **66 catalogue workspace checks**: nullable first-run store setup, reviewed private draft and commit/lost-response/reload same-key recovery, corrupt/expired/storage-failure fencing and session/business isolation, publication/activation/checkout gates, current SKU facts, COD order, cancellation stock release, sellout and stale-write conflicts, readonly viewer and mobile.
- **17 channel operator checks**: native signup/invitation, scoped pagination/review, audited no-delivery closure, eligible queued retry and expired-window rejection, synthetic connection GET/save/disconnect, session expiry and mobile viewer. Customer-send tasks are suppressed; provider GET responses are synthetic.
- Storefront: **45 Node tests** and **22 Chromium HTTP-mock/theme tests** passed, plus syntax checks. A separate **25-check actual native/API-backed Chromium journey** passes through the production bootstrap: seller workspace opens its configured public link, current SKU publication, COD, status after reload/unpublish, four uncertain POST outcomes with same-key replay, stock rejection/recovery and no-COD browse-only behavior. The shared native transport/cleanup has **5 behavioral Node checks**.

Additional worker/independent evidence: B20 reported **137 actual PostgreSQL 16 checks**; C20 final **33 DB/API + 13 pure** and the same **17 browser** cases; local import composition/domain/startup checks passed **194** including all nine formerly skipped real DB cases. Social independently reviewed the D20 composition and ran **8** actual migrated checks on its own lane with no substantive findings. These overlapping counts are not added into a unique total.

Independent A20 review reproduced legacy-route native-session CSRF and invitation bearer UI cross-business leakage; `ed406a3` fixed both and the reviewer reran the actual HTTP and controlled Chromium repros successfully. Independent channel review found an opposite-focus Product lock deadlock and a queued replay Business-active gap; `22a1595` fixes both with database regressions. Integrator source/render review accepted the bounded catalogue and channel interfaces, including the corrected attachment copy. An additional fresh Impeccable agent could not start because of the agent-thread limit; the external integrator review and disclosed documentation fallback are recorded, rather than claiming a separate fresh agent ran.

## Test environment and artifacts

Dedicated loopback PostgreSQL **16.15** container `munimjee-v1-wave2-pg16` uses port **55442** and isolated `munimjee_test_<lane>` databases. Current central integration uses `wave3_integration`; settings and parcel/recovery workers use their separately allocated `payment_w3` and `parcel_w3` lanes. Earlier wave2 evidence used `wave2_integration` and `auth_wave2`. The original dedicated PostgreSQL 15/Redis test containers remain separate; existing sellerbot runtime containers are unchanged. Every reset validates explicit `TEST_DATABASE_URL`, `TEST_LANE` and `TEST_DB_RESET=1`, holds a PostgreSQL advisory lease and applies actual Alembic migrations. No `create_all` proof or production fallback is used. Tests strip dotenv/provider settings and block outbound provider sockets.

The current full chain is `0040 identity → 0041 catalogue → 0042 ingress → 0043 auth → 0044 checkout → 0045 channel operator → 0046 imports → 0047 import receipt → 0048 parcel tracking → 0049 storefront settings → 0050 assistance`. Current central checks use the separate `wave3_integration` lane; both 0049 and 0050 are actual migrated revisions. Unreleased 0044/0045 schema changes require rebuilding disposable schemas from the real chain. Startup tests verify the single head, models, routers and recovery task registration. Local PostgreSQL 16 parity is verified; remote/CI PostgreSQL 16 execution is not implied.

Evidence: `artifacts/v1/auth-wave2/`, `artifacts/v1/storefront-integration/`, `artifacts/v1/catalogue-workspace/`, `artifacts/v1/channel-operator/`, `artifacts/v1/B20/` and the combined XML under `artifacts/v1/integration/`. First-wave exact results (**782 passed, 8 skipped**) and Redis transfer proof are preserved in `artifacts/v1/integration/2026-10-17-foundations/execution-status.md`.

Default-off rollout controls: `V1_AUTH_ENABLED`, `V1_ENFORCE_LEGACY_ACCESS`, `V1_IMPORTS_ENABLED`, `V1_STOREFRONT_ENABLED`, `V1_PUBLIC_PAYMENTS_ENABLED`, `V1_IMPORT_BRIDGE_ENABLED`, `V1_PARCEL_ENABLED`. Private parcel connector registry/origin configuration defaults empty. Public pages require a validated configured `PUBLIC_BASE_URL` and complete runtime assets; only the runtime JS/CSS directory is mounted. An optional explicit `V1_STOREFRONT_ASSETS_DIR` supports packaging. The existing backend-only Docker artifact remains unchanged. A separate allowlisted V1 package/image now passes local build and offline startup/static proof; existing deployment files/services are preserved. Source packaging commits `417cbee`, `8db5dca`, `6529550` are integrated as `d2b73a9`, `fc2e634`, `246350a`. The historical wave2 integration image is `sha256:040c2625ed60a24f2dce2cabd1229da85fbe58afedeed59f00c98245b81f5b02`, Docker-reported 129636999 bytes, arm64, UID/GID 10001. Its 233-file context excludes environments, uploads, tests, fixtures, node_modules and keys; exact manifests and offline evidence are in `artifacts/v1/runtime-package/`. The package scripts are independently reviewed, including symlink/dependency guards and CID-only verified cleanup. No deployment is performed. Saved profile or credentials never turn the checklist into a full seller-ready/provider-approved claim. Support impersonation remains unavailable.

## Remaining product/release gates

- Complete deployment/migration/restore rehearsal and CI/multi-architecture certification. Local allowlisted image/startup/static proof is separate from deployment. Real SDK/provider/CSP/account-domain acceptance, physical-device critical flows and real product media remain open; SDK/provider transports in current browser evidence are synthetic.
- Native import progress/review/allocation and the private-product bridge are composed locally. Approved real sources and seller-authorized Instagram retrieval remain provider-gated; approval never publishes, activates or invents unknown stock.
- Persisted seller configuration/publication and public rendering of all three designs are composed locally through actual 0049. Synthetic missing-media fallbacks are verified; real approved catalogue media and physical-device acceptance remain open.
- Native payment credential entry and exact-order seller recovery are composed locally; configuration is explicitly not live connection verification. Unknown legacy inventory allocations/reservations, gateway live settlement/refund and selected international destination acceptance remain migration gates.
- ParcelDesk local source connector and order-first barcode workflow are implemented. Private per-business provisioning/D1/TLS transport, physical-phone camera proof, and permitted real utility-template delivery remain open. Reviewed local resolution/replacement now preserves historical associations and audit. No courier booking/new courier API is in scope.
- Separate explicit expiring support grants, global sales access, verified customer identity links, analytics and the remaining complete onboarding acceptance matrix remain V1 scope. The current assistance board requires existing business membership. Support impersonation remains denied.
- Current Meta permissions/approval and authorized real-provider consent/canaries remain external gates. No real customer message, provider mutation, paid transaction or production cutover has been performed.
