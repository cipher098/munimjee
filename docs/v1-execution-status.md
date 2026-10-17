# V1 execution status

Updated: 17 October 2026. Coordinator branch: `codex/v1-integration`. Source baseline: `035b5da`; preserved application baseline: `e7694ff`. This is a bounded foundation milestone, not a V1 completion or release claim.

## Ownership and verified scope

| Worker | Host | Source branch / reviewed commit | Current scope | State |
| --- | --- | --- | --- | --- |
| identity-onboarding | This Mac | codex/v1-identity / f5b9419; integrated as 53f31ba | Business/User/Membership bridge, capability matrix, read-only `/api/v1` identity/readiness | Code verified and integrated; onboarding/login/invites pending |
| catalogue-commerce | This Mac | codex/v1-catalogue / 70b2dcd; integrated as 01f3a83 | Preview SKU snapshots, tenant constraints, reviewed stock allocation and fixtures | Code verified and integrated; API/checkout writer cutover pending |
| social-automation | This Mac | codex/v1-social / 313c2b4 reviewed | Durable IG receipt foundation with safe legacy cutover, partial-consumption accounting and uncertainty quarantine fixes | Review fixes in progress; not integrated |
| qa-isolation | Mac mini dev | codex/v1-test-isolation / c289ddc+cfaebb1; integrated as d6a41ee+cba20a4 | Fail-closed test lanes, blocked live networking, actual Alembic fixtures and held reset lease | Code verified and integrated on local PostgreSQL 15; PostgreSQL 16 CI pending |
| imports | Mac mini dev | codex/v1-import-drafts / 94e29f1, reviewed source a58414b | Structured draft/review/reimport domain only | Pure checks verified and integrated; fetch/jobs/persistence/auth/UI pending |
| storefront | Mac mini dev | codex/v1-storefront-scaffolding / c5a52c0 | Fixture-only theme/cart/checkout-preview scaffold | Held for catalogue readiness DTO mismatch; real API/checkout/publication/SEO/video pending |
| local integrator | This Mac | codex/v1-integration | Review, model/router/worker registration, migration order, portable P01 fixtures and evidence | Active; no production actions |

All new implementation workers use GPT-6.1 Sol with high reasoning as requested. Existing running application checkout/services and the original Parcel Desk project are not implementation targets. Only the owner-authorized `go-live-plan.md` copy is synchronized into `/Users/gothi/sellerbot` after committing the revised plan.

## Preparation and safety evidence

- P00: dirty source/runtime changes were preserved privately; reviewed application changes entered isolated baseline e7694ff. No secrets were committed and original runtime changes were not reset.
- P01: dedicated local PostgreSQL 15 and Redis 7 containers use loopback ports 55441/56441 on their own Docker network. Existing sellerbot containers are unchanged. The P01 validator requires a literal numeric loopback URL, exact `munimjee_test_<TEST_LANE>` name and explicit reset opt-in. Dotenv/provider settings are stripped and outbound sockets blocked except the validated test DB. A held PostgreSQL advisory lease covers schema reset, actual Alembic migration and each DB fixture.
- Integration tests use newly created `munimjee_test_integration` in that dedicated PostgreSQL container. Original per-worker databases remain separate. Identity and catalogue fixtures now use the portable P01 helper rather than hardcoded worker URLs. No runtime database is a fallback.
- P02: current shared decisions are in `v1-contract-decisions.md`. Identity and catalogue models are registered centrally. Actual migrations through `0041_v1_catalogue` run in the integrated DB fixtures; ORM `create_all` is not the integration proof. Social `0042_instagram_ingress` remains pending review/integration.
- P03: current Meta permissions/accounts and Razorpay canaries remain unverified. Shipping scope changed by the owner: no new courier API or booking; use existing Parcel Desk tracking with order-first scan/confirmation. The current standalone tracker has shared cookie auth, no tenant field and no machine API; a scoped connector and refresh/deployment verification remain gates. See `v1-parcel-desk-integration.md`.
- Mac mini: GitHub push and Python/Node work are verified. Docker was unresponsive and available disk was approximately 11 GiB when inspected; database evidence currently comes from this Mac. Remote pure/browser results remain explicitly distinguished from local integrated checks.

## Actual verification

1. On identity/catalogue/P01 integration source, the guarded full backend run passed **621 tests, skipped 5** in **107.81 seconds**. All five skips are missing historical LLM/scenario cassettes (`decide_greeting`, `awaiting_payment_lock`, `happy_path_accept`, `price_lock_consistency`, `walkaway_calls_bluff`); no live recording was attempted. Existing Pydantic/HTTPX deprecations remain.
2. Focused integrated safety+identity+catalogue run passed **172 tests, no skips** in **9.84 seconds**, including actual Alembic head and reset-lease checks, backfill/revocation/tenant negatives and catalogue stock/review constraints.
3. Import domain source was independently reviewed and rerun locally: **110 passed, no skips** in **0.07 seconds**. This is structured-data domain verification, not importer product acceptance. Remote source/evidence commits are preserved in Git and `artifacts/v1/D10/`.
4. Social branch pure/worker checks passed **17 tests** before review fixes. Independent local temporary-schema reproductions found two P1 blockers: media can reach the send phase through both legacy Redis and durable ingress, and screenshot+address batches mark an unprocessed address receipt completed. Nested malformed payloads also raised unhandled errors. The social owner is fixing all three and adding uncertainty quarantine; original source is not integrated.
5. Remote storefront owner reports contract/browser preview checks on mobile/desktop, stock limits, keyboard focus and explicit checkout-preview labels. Local review found `readiness.state=reviewed_sample/variant_stock_review` does not match frozen B10 string readiness (`needs_review/default_backfilled/reviewed/stale`). Hold integration until actual B10 DTO fixtures pass. No real video/checkout/publication/SEO or physical-device result is claimed.

The guarded commands use `TEST_DATABASE_URL`, `TEST_LANE=integration`, `TEST_DB_RESET=1`, `PYTHONPATH=backend` and the isolated `.venv`:

```sh
.venv/bin/python -m pytest backend/tests -q -ra
.venv/bin/python -m pytest backend/tests/test_test_safety.py backend/tests/test_v1_identity.py backend/tests/test_v1_identity_db.py backend/tests/test_v1_catalogue.py backend/tests/test_v1_catalogue_db.py backend/tests/test_v1_catalogue_migration.py -q -ra
.venv/bin/python -m pytest backend/tests/test_v1_import_drafts.py -q
```

## Remaining gates and decisions

- Review and rerun social fixes, register its model/worker/recovery schedule, verify actual `0040 → 0041 → 0042` Alembic chain and cross-path uncertain-send behavior before integration.
- Align storefront fixtures with frozen catalogue DTOs. Preview browser testing is not product testing of a published, API-backed store.
- Native login/invites, signup bridge wiring, app-wide session cleanup/revocation, audited support grants, canonical customer links and full seller onboarding remain pending. Current V1 membership revocation does not disable intentionally preserved legacy owner sessions.
- Catalogue services are preview foundations. No approved import→catalogue adapter, real SKU checkout writer, reservation migration, provider payment canary or seller order UI is completed by these commits.
- Parcel association/tracking connector, order dashboard scan UI, trusted machine access, local append-only tracking reconciliation, permitted customer notification outbox and authorized acceptance evidence remain design/implementation work. Barcode alone is not order identity.
- Provider approvals, production secrets/deployment, migration/restore rehearsal, international destination checks, PostgreSQL 16 CI, physical-device critical flows and the full product acceptance matrix remain pending.

No production deployment, live customer message, paid transaction, courier booking or release approval is performed or implied.
