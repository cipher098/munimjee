# V1 execution status

Updated: 17 October 2026. Coordinator branch: `codex/v1-integration`. Source baseline: `035b5da`; preserved application baseline: `e7694ff`. This is a bounded foundation milestone, not a V1 completion or release claim.

## Ownership and verified scope

| Worker | Host | Source branch / reviewed commit | Current scope | State |
| --- | --- | --- | --- | --- |
| identity-onboarding | This Mac | codex/v1-identity / f5b9419; integrated as 53f31ba | Business/User/Membership bridge, capability matrix, read-only `/api/v1` identity/readiness | Code verified and integrated; onboarding/login/invites pending |
| catalogue-commerce | This Mac | codex/v1-catalogue / 70b2dcd; integrated as 01f3a83 | Preview SKU snapshots, tenant constraints, reviewed stock allocation and fixtures | Code verified and integrated; API/checkout writer cutover pending |
| social-automation | This Mac | codex/v1-social / 1e3cfb5; integrated through 2b4d88a | Durable IG receipts, exact partial progress, reviewed legacy transfer and uncertain-send quarantine | Code verified and integrated; live provider/operator UI acceptance pending |
| qa-isolation | Mac mini dev | codex/v1-test-isolation / c289ddc+cfaebb1; integrated as d6a41ee+cba20a4 | Fail-closed test lanes, blocked live networking, actual Alembic fixtures and held reset lease | Code verified and integrated on local PostgreSQL 15; PostgreSQL 16 CI pending |
| imports | Mac mini dev | codex/v1-import-drafts / 94e29f1, reviewed source a58414b | Structured draft/review/reimport domain only | Pure checks verified and integrated; fetch/jobs/persistence/auth/UI pending |
| storefront | Mac mini dev + local integration review | codex/v1-storefront-scaffolding / c5a52c0; integrated/corrected through 8903bb7 | Fixture-only themes/cart/checkout preview aligned with frozen B10 DTOs | Code/browser preview verified and integrated; real API/checkout/publication/SEO/video pending |
| local integrator | This Mac | codex/v1-integration | Review, model/router/worker registration, migration order, portable P01 fixtures and evidence | Active; no production actions |

All new implementation workers use GPT-6.1 Sol with high reasoning as requested. Existing running application checkout/services and the original Parcel Desk project are not implementation targets. Only the owner-authorized `go-live-plan.md` copy is synchronized into `/Users/gothi/sellerbot` after committing the revised plan.

## Preparation and safety evidence

- P00: dirty source/runtime changes were preserved privately; reviewed application changes entered isolated baseline e7694ff. No secrets were committed and original runtime changes were not reset.
- P01: dedicated local PostgreSQL 15 and Redis 7 containers use loopback ports 55441/56441 on their own Docker network. Existing sellerbot containers are unchanged. The P01 validator requires a literal numeric loopback URL, exact `munimjee_test_<TEST_LANE>` name and explicit reset opt-in. Dotenv/provider settings are stripped and outbound sockets blocked except the validated test DB. A held PostgreSQL advisory lease covers schema reset, actual Alembic migration and each DB fixture.
- Integration tests use newly created `munimjee_test_integration` in that dedicated PostgreSQL container. Original per-worker databases remain separate. Identity and catalogue fixtures now use the portable P01 helper rather than hardcoded worker URLs. No runtime database is a fallback.
- P02: current shared decisions are in `v1-contract-decisions.md`. Identity and catalogue models are registered centrally. Actual migrations through `0041_v1_catalogue` run in the integrated DB fixtures; ORM `create_all` is not the integration proof. Social `0042_instagram_ingress` is registered and verified as the sole actual Alembic head after 0040/0041. Worker discovery and 30-second recovery scheduling have explicit startup checks.
- P03: current Meta permissions/accounts and Razorpay canaries remain unverified. Shipping scope changed by the owner: no new courier API or booking; use existing Parcel Desk tracking with order-first scan/confirmation. The current standalone tracker has shared cookie auth, no tenant field and no machine API; a scoped connector and refresh/deployment verification remain gates. See `v1-parcel-desk-integration.md`.
- Mac mini: GitHub push and Python/Node work are verified. Docker was unresponsive and available disk was approximately 11 GiB when inspected; database evidence currently comes from this Mac. Remote pure/browser results remain explicitly distinguished from local integrated checks.

## Actual verification

Final backend code is the tree through `deeacab92333f4035e9256b8104c85d077bc671b`; subsequent source change `8903bb73631784ba35d564859d166fa4f679f081` affects only the storefront review-state edge. Final browser/contract source is `8903bb7`. Logs and exact environment/results are in `artifacts/v1/integration/2026-10-17-foundations/`.

1. Final guarded full backend run: **782 passed, 8 skipped** in **121.09 seconds**. Five skips are missing historical LLM/scenario cassettes (`decide_greeting`, `awaiting_payment_lock`, `happy_path_accept`, `price_lock_consistency`, `walkaway_calls_bluff`). Three Redis-dependent pytest cases skip because P01 intentionally strips Redis opt-ins and blocks Redis sockets. No live cassette recording was attempted. Existing Pydantic/HTTPX deprecations remain.
2. The final full run includes actual Alembic head/reset-lease checks, all identity/catalogue/import tests, social partial-progress and quarantine regressions, and four startup checks for actual app routes, model registration, worker discovery/recovery schedule and the single `0040 → 0041 → 0042` chain.
3. Separate actual Redis→PostgreSQL composition proof passed on the allocated local Redis `/0` with unique keys and an isolated temporary schema in the identity disposable DB. It retained **four distinct missing-mid occurrences across two customers**, reused transfer IDs on retry, assigned fresh IDs to later identical buffers, kept new buffers after a stale trim, and committed receipts before trimming. All receipts stayed held for review; no send function ran. Only generated keys/schema were removed. This complements, and does not relabel, the three skipped pytest cases.
4. Storefront source passes **10 contract checks** and **8 actual local Chromium browser checks** (15.4 seconds), plus JavaScript syntax checks. Browser cases exercise all three themes, 390/1440 layouts, 320/768 overflow checks, variants, tracked/untracked/review stock, capped cart, checkout-preview boundaries and keyboard focus. Local review corrected string readiness, paise rounding, default option labels and empty-SKU review pricing; actual B10 DTO fixtures are consumed by tests. Generated screenshots stay in test output; original design evidence is preserved. Source detector returned no findings. This remains a fixture preview, not real checkout, publication, video or physical-device acceptance.
5. Import domain source was independently reviewed and initially rerun locally: **110 passed, no skips**. It is also covered by the final backend run. No URL fetcher, import job runner, storage adapter or publication is claimed.
6. Earlier checkpoint: 621 backend tests passed with five cassette skips before social/import integration; focused safety+identity+catalogue passed 172 with no skips. Initial social review reproduced duplicate media sending paths and lost batch tails; fixes replace legacy sending with reviewed durable transfer, track receipt component progress, preserve missing-mid multiplicity and quarantine uncertain threads across ingress/resume/nudge. Malformed nested signed payloads now return 400.

The guarded commands use `TEST_DATABASE_URL`, `TEST_LANE=integration`, `TEST_DB_RESET=1`, `PYTHONPATH=backend` and the isolated `.venv`:

```sh
.venv/bin/python -m pytest backend/tests -q -ra
npm --prefix frontend/storefront test
npm --prefix frontend/storefront run check
npm --prefix frontend/storefront run test:browser
```

## Remaining gates and decisions

- Social foundation is integrated, with live Meta/SQS ingress, actual provider sends, operator review UI/audit and staging cutover rehearsal still pending. Existing Redis backlog is transferred and held for explicit review; there is no automatic replay of uncertain historical sends. The unreleased 0042 migration includes processed indices; recreate disposable schemas carrying the earlier development version rather than treating them as current.
- Storefront fixture/DTO alignment is verified. Preview browser testing is not product testing of a published, API-backed store. Canonical server-rendered routes, real product media/video, APIs and checkout remain pending.
- Native login/invites, signup bridge wiring, app-wide session cleanup/revocation, audited support grants, canonical customer links and full seller onboarding remain pending. Current V1 membership revocation does not disable intentionally preserved legacy owner sessions.
- Catalogue services are preview foundations. No approved import→catalogue adapter, real SKU checkout writer, reservation migration, provider payment canary or seller order UI is completed by these commits.
- Parcel association/tracking connector, order dashboard scan UI, trusted machine access, local append-only tracking reconciliation, permitted customer notification outbox and authorized acceptance evidence remain design/implementation work. Barcode alone is not order identity.
- Provider approvals, production secrets/deployment, migration/restore rehearsal, international destination checks, PostgreSQL 16 CI, physical-device critical flows and the full product acceptance matrix remain pending.

No production deployment, live customer message, paid transaction, courier booking or release approval is performed or implied.
