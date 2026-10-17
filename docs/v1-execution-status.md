# V1 execution status

Updated: 18 October 2026. Coordinator branch: `codex/v1-integration`. Verified first-wave foundation: `7de7cd6`; preserved application baseline: `e7694ff`. This is a bounded implementation milestone, not full V1 acceptance or a production release.

## Wave 3 local integration

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

Current actual migration head is `0048_v1_parcel_tracking`; remote theme revision
0049 remains reserved, not shipped. The full wave3 checkpoint through `1ac880a` passed **1223 tests, 8 documented
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

Dedicated loopback PostgreSQL **16.15** container `munimjee-v1-wave2-pg16` uses port **55442** and isolated `munimjee_test_<lane>` databases. Integration uses `wave2_integration`; auth browser runs use `auth_wave2`; catalogue and channel workers own separate lanes. The original dedicated PostgreSQL 15/Redis test containers remain separate; existing sellerbot runtime containers are unchanged. Every reset validates explicit `TEST_DATABASE_URL`, `TEST_LANE` and `TEST_DB_RESET=1`, holds a PostgreSQL advisory lease and applies actual Alembic migrations. No `create_all` proof or production fallback is used. Tests strip dotenv/provider settings and block outbound provider sockets.

The current full chain is `0040 identity → 0041 catalogue → 0042 ingress → 0043 auth → 0044 checkout → 0045 channel operator → 0046 imports → 0047 import receipt → 0048 parcel tracking`. Wave3 central checks use the separate `wave3_integration` lane; 0049 is only reserved for remote theme work. Unreleased 0044/0045 schema changes require rebuilding disposable schemas from the real chain. Startup tests verify the single head, models, routers and recovery task registration. Local PostgreSQL 16 parity is verified; remote/CI PostgreSQL 16 execution is not implied.

Evidence: `artifacts/v1/auth-wave2/`, `artifacts/v1/storefront-integration/`, `artifacts/v1/catalogue-workspace/`, `artifacts/v1/channel-operator/`, `artifacts/v1/B20/` and the combined XML under `artifacts/v1/integration/`. First-wave exact results (**782 passed, 8 skipped**) and Redis transfer proof are preserved in `artifacts/v1/integration/2026-10-17-foundations/execution-status.md`.

Default-off rollout controls: `V1_AUTH_ENABLED`, `V1_ENFORCE_LEGACY_ACCESS`, `V1_IMPORTS_ENABLED`, `V1_STOREFRONT_ENABLED`, `V1_PUBLIC_PAYMENTS_ENABLED`, `V1_IMPORT_BRIDGE_ENABLED`, `V1_PARCEL_ENABLED`. Private parcel connector registry/origin configuration defaults empty. Public pages require a validated configured `PUBLIC_BASE_URL` and complete runtime assets; only the runtime JS/CSS directory is mounted. An optional explicit `V1_STOREFRONT_ASSETS_DIR` supports packaging. The existing backend-only Docker artifact remains unchanged. A separate allowlisted V1 package/image now passes local build and offline startup/static proof; existing deployment files/services are preserved. Source packaging commits `417cbee`, `8db5dca`, `6529550` are integrated as `d2b73a9`, `fc2e634`, `246350a`. The final integration image is `sha256:040c2625ed60a24f2dce2cabd1229da85fbe58afedeed59f00c98245b81f5b02`, Docker-reported 129636999 bytes, arm64, UID/GID 10001. Its 233-file context excludes environments, uploads, tests, fixtures, node_modules and keys; exact manifests and offline evidence are in `artifacts/v1/runtime-package/`. The package scripts are independently reviewed, including symlink/dependency guards and CID-only verified cleanup. No deployment is performed. Saved profile or credentials never turn the checklist into a full seller-ready/provider-approved claim. Support impersonation remains unavailable.

## Remaining product/release gates

- Complete deployment/migration/restore rehearsal and CI/multi-architecture certification. Local allowlisted image/startup/static proof is separate from deployment. Real SDK/provider/CSP/account-domain acceptance, physical-device critical flows and real product media remain open; SDK/provider transports in current browser evidence are synthetic.
- Remote native import progress/review/allocation UI must consume the reviewed bridge and pass the actual mounted workflow. The atomic private-product adapter API is implemented; approval still never publishes, activates or invents unknown stock. Seller-authorized Instagram retrieval remains provider-gated.
- Persistent seller selection/configuration of the three themes (reserved 0049) and actual public all-theme rendering remain open. Existing 22 theme checks use injected HTTP and do not close that gate.
- Native payment credential entry UI remains open; the protected local configuration API and exact-order seller recovery pane exist. Unknown legacy inventory allocations/reservations, gateway live settlement/refund and selected international destination acceptance remain migration gates.
- ParcelDesk local source connector and order-first barcode workflow are implemented. Private per-business provisioning/D1/TLS transport, physical-phone camera proof, permitted real utility-template delivery and reviewed resolution/replacement for review-required links remain open. No courier booking/new courier API is in scope.
- Separate explicit expiring support grants, assisted sales console, verified customer identity links, analytics and the remaining complete onboarding acceptance matrix remain V1 scope. Support impersonation remains denied.
- Current Meta permissions/approval and authorized real-provider consent/canaries remain external gates. No real customer message, provider mutation, paid transaction or production cutover has been performed.
