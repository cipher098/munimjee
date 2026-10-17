# V1 execution status

Updated: 18 October 2026. Coordinator branch: `codex/v1-integration`. Verified first-wave foundation: `7de7cd6`; preserved application baseline: `e7694ff`. This is a bounded implementation milestone, not full V1 acceptance or a production release.

## Integrated wave 2

| Lane | Reviewed source | Integrated behavior and limits |
| --- | --- | --- |
| Native identity/onboarding | Auth `87cc13f`, `6314f29`, `6b883f3`, `a395888`, `ed406a3`; integration authority fix `38c3da0` | Own-account signup/login, transactional Seller/Business bridge, persistent revocable native sessions, bound CSRF, invitations and roles, saved versioned profile and resumable checklist. Native staff never receive legacy seller tokens. Support grants remain denied. Legacy enforcement is separately gated. |
| Catalogue/orders | Domain `ed86ff9`, `7736c44`; workspace `95dae6f` integrated as `1518baf`; router/browser composition `f21cf55` | Private reviewed drafts, explicit current-snapshot activation, authoritative SKU reads/writes, separate store publication/checkout policy, stock reservation/release, protected seller order actions and native workspace. Durable unknown-payment creation guard uses synthetic transports. Existing legacy reservations are not silently migrated. |
| Channel operator | `9de66db`, `22a1595`, `beac174`, `7a95fc9`; evidence `b00a173` | Native queue/review/audit, current-policy replay eligibility, explicit no-replay closure, connection check/save/disconnect and OAuth binding. Activated SKU conversations hand off to a person. Unknown sends remain quarantined. Local account access is not provider approval or delivery proof. |
| Durable imports | Remote source through `64f2e4e`; central actual DDL/registration `c44f14c` | Durable job/draft/asset/audit persistence, bounded website JSON-LD extraction, DNS-pinned SSRF controls, original upload bytes, recovery/cancellation, override-preserving review and idempotent reimport. Native router and disabled-by-default periodic worker are composed. Seller import UI and approved import-to-catalogue bridge remain pending. |
| Storefront/QA foundation | Remote storefront through `2f70d45`, QA through `e360ca1`; integration selector correction `d606325` | Reviewed canonical server-rendering factory, strict public projection, three existing fixture themes and persisted uncertain checkout intents. The canonical live contract/provider is being connected locally; remote HTTP mocks do not prove that real customer journey. |
| Safety/integration | P01 plus `9402390`, actual head `0046_v1_import_jobs` | Exact disposable lane validation, blocked provider networking, held database reset/migration leases, actual PostgreSQL 16 migrations, private V1 no-store headers and default-off feature gates. No production actions. |

All implementation/review workers use GPT-6.1 Sol with high reasoning. Existing running application checkouts/services and the original Parcel Desk source remain untouched. The running checkout's plan was synchronized only for the first explicitly authorized documentation copy; current wave-2 edits stay in the integration worktree.

## Verification

Final combined backend result against the code through `f21cf55`: **1072 passed, 8 skipped, 0 failed** in **235.01 seconds**, using the actual full PostgreSQL 16 migration chain. Five skips are missing historical scenario cassettes; three Redis cases are intentionally unavailable under the P01 blocked-network pytest setup. Existing deprecation warnings remain. The earlier complete run found **1064 passed, 8 skipped and 3 failed**. Those three actual PostgreSQL 16 failures exposed retained ORM User/Membership authority after another transaction revoked or downgraded it. `38c3da0` now authorizes from fresh database values, also rechecking persisted session expiry/revocation/auth version and the legacy cutoff. The focused current-state/security/safety rerun passed **105 checks**; the prior auth/onboarding/identity/QA focused run passed **76**. An independent reviewer also reproduced current-role downgrade denial, preservation of unrelated dirty ORM fields, cached session/auth-version rejection and two concurrent atomic logout-all increments on its own actual PostgreSQL 16 lane; no substantive regression was found.

Independent integration browser checks on the actual mounted application, sequential leases on PostgreSQL 16 `auth_wave2` after the full 0046 chain:

- **16 native onboarding checks**: fresh signup, saved/resumed profile, conflict, CSRF, invitation role, delayed cross-business response handling and logout cleanup.
- **37 catalogue workspace checks**: nullable first-run store setup, reviewed private draft and lost-response same-key recovery, publication/activation/checkout gates, current SKU facts, COD order, cancellation stock release, sellout and stale-write conflicts, readonly viewer and mobile.
- **17 channel operator checks**: native signup/invitation, scoped pagination/review, audited no-delivery closure, eligible queued retry and expired-window rejection, synthetic connection GET/save/disconnect, session expiry and mobile viewer. Customer-send tasks are suppressed; provider GET responses are synthetic.
- Storefront foundation: **36 Node tests** and **22 Chromium HTTP-mock tests** passed, plus JavaScript syntax checks. This is not the pending actual API-backed customer checkout journey.

Additional worker/independent evidence: B20 reported **137 actual PostgreSQL 16 checks**; C20 final **33 DB/API + 13 pure** and the same **17 browser** cases; local import composition/domain/startup checks passed **194** including all nine formerly skipped real DB cases. Social independently reviewed the D20 composition and ran **8** actual migrated checks on its own lane with no substantive findings. These overlapping counts are not added into a unique total.

Independent A20 review reproduced legacy-route native-session CSRF and invitation bearer UI cross-business leakage; `ed406a3` fixed both and the reviewer reran the actual HTTP and controlled Chromium repros successfully. Independent channel review found an opposite-focus Product lock deadlock and a queued replay Business-active gap; `22a1595` fixes both with database regressions. Integrator source/render review accepted the bounded catalogue and channel interfaces, including the corrected attachment copy. An additional fresh Impeccable agent could not start because of the agent-thread limit; the external integrator review and disclosed documentation fallback are recorded, rather than claiming a separate fresh agent ran.

## Test environment and artifacts

Dedicated loopback PostgreSQL **16.15** container `munimjee-v1-wave2-pg16` uses port **55442** and isolated `munimjee_test_<lane>` databases. Integration uses `wave2_integration`; auth browser runs use `auth_wave2`; catalogue and channel workers own separate lanes. The original dedicated PostgreSQL 15/Redis test containers remain separate; existing sellerbot runtime containers are unchanged. Every reset validates explicit `TEST_DATABASE_URL`, `TEST_LANE` and `TEST_DB_RESET=1`, holds a PostgreSQL advisory lease and applies actual Alembic migrations. No `create_all` proof or production fallback is used. Tests strip dotenv/provider settings and block outbound provider sockets.

The full chain is `0040 identity → 0041 catalogue → 0042 ingress → 0043 auth → 0044 checkout → 0045 channel operator → 0046 imports`. Unreleased 0044/0045 schema changes require rebuilding disposable schemas from the real chain. Startup tests verify the single head, models, routers and recovery task registration. Local PostgreSQL 16 parity is verified; remote/CI PostgreSQL 16 execution is not implied.

Evidence: `artifacts/v1/auth-wave2/`, `artifacts/v1/catalogue-workspace/`, `artifacts/v1/channel-operator/`, `artifacts/v1/B20/` and the combined XML under `artifacts/v1/integration/`. First-wave exact results (**782 passed, 8 skipped**) and Redis transfer proof are preserved in `artifacts/v1/integration/2026-10-17-foundations/execution-status.md`.

Default-off rollout controls: `V1_AUTH_ENABLED`, `V1_ENFORCE_LEGACY_ACCESS`, `V1_IMPORTS_ENABLED`. Saved profile or credentials never turn the checklist into a full seller-ready/provider-approved claim. Support impersonation remains unavailable.

## Remaining product/release gates

- Complete the actual public storefront provider/contract and real API-backed customer browser flow; then verify publication, canonical origin/assets, all three themes and deployment packaging. No arbitrary Host-derived public origin or inactive/draft/legacy fallback.
- Seller import progress/review UI and the approved draft-to-catalogue adapter, honest unknown-stock handling and seller-authorized Instagram retrieval. Import approval alone never publishes or changes stock/orders.
- Legacy ambiguous allocation editor/reservation reconciliation and supported migration/rollback rehearsal; live gateway settlement and international destination checks.
- Separate explicit expiring support grants, assisted sales console, verified customer identity links, analytics and the remaining full onboarding acceptance matrix.
- Parcel Desk scoped machine connector, order-first barcode confirmation UI, append-only local tracking reconciliation and permitted notification dedupe/outbox. Barcode alone cannot identify an order. No new courier API or booking is in V1 scope.
- Current Meta permissions/approval, authorized provider consent/canaries, production secrets/deployment/restore rehearsal and physical-device critical flows. No real customer message, provider mutation, paid transaction or production cutover has been performed.
