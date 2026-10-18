# Native import allocation and persisted public themes

Base: `a2ea26d`, 18 October 2026. Preserve prior branch checkpoints. This continuation
uses GPT-6.1 Sol/high for the coordinator and every explicitly configured worker.
No production deployment, provider/customer messages, real charges or shared
service restarts are authorized.

## Ownership

- Import UI: `codex/v1-import-allocation-ui`, worktree `munimjee-wave4-imports`.
  Own import workspace page/router, dedicated tests/runners/artifacts and docs.
  Consume the frozen `docs/contracts/import-catalogue` schemas and existing APIs;
  do not change bridge/domain or shared auth code.
- Theme settings: `codex/v1-theme-publication`, worktree `munimjee-wave4-themes`.
  Own theme models/schema/service/router/page/tests and the reserved migration
  `0049_v1_storefront_settings` after actual `0048_v1_parcel_tracking`.
  The coordinator delegates narrow additive public design hooks in
  `services/storefront_publication.py`, `v1/storefront/rendering.py`,
  `frontend/storefront/src/live-app.js`, and `live.css`, plus a dedicated theme
  helper. Preserve all payment composition; do not edit payment-handoff,
  checkout-attempt, checkout sessions, order-status, or canonical payment APIs.
- Independent QA: `codex/v1-qa-native-completion`, worktree `munimjee-wave4-qa`.
  Own independent tests/runners/evidence/docs only. Read peer source without
  changing it; use reviewed composition commits when supplied.
- Coordinator: `codex/v1-native-composition`. Own shared main/model registration,
  native navigation, V1 private-storage cleanup and runtime asset allowlists.
  Do not edit the feature-owned files while workers run.

## Frozen behavior

The import UI uses the actual catalogue-preview/catalogue-draft bridge. Unknown
stock blocks allocation, while explicit integer allocations cover every supported
combination exactly once and sum to the confirmed quantity. Persist the exact
body/key before requests; immutable retries survive lost responses and reloads.
Approval/allocation creates a private draft only. Activation, store publication,
checkout and existing inventory remain separate decisions.

Theme writes use `business_mutation('business.write')` with caller-owned database
transactions, including replay; current session/role is rechecked after lock waits
and before commit. Draft save and private preview never change public design.
Explicit design publication promotes only saved allowlisted configuration and
never flips Storefront.published or product/checkout authority. Public provider,
SSR and DOM render only validated published configuration; blank fields use
existing theme defaults. Palettes map to fixed tokens, and text is escaped or
rendered through textContent. All three themes retain actual COD/online payment
and private order-status behavior. No theme query parameter grants authority.

Shared cleanup adds `munimjee.v1.import-command:` and
`munimjee.v1.theme-command:` to all existing authentication transition/401 paths.
Pages also independently fence old identity/tenant/session responses and storage.

## Verification limits

Use P01's exact disposable lane validation and held reset/migration lease. Do not
invent credentials or use another lane. If Docker/PostgreSQL is unavailable,
record explicit database skips and prepare actual mounted tests for the local
integrator. Synthetic HTTP, provider fixtures and physical-device checks must be
labelled separately. Inspect desktop/mobile captures, preserve bounded source
retrieval and prohibit external provider/customer/payment requests.
