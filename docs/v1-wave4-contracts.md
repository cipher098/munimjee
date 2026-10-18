# Wave4: seller settings, reviewed tracking recovery and assisted onboarding

Base: verified `a2ea26d7420e87697ef69b8c427a3f5a5ec61bf7`, 18 October 2026.
All workers retain GPT-6.1 Sol / high. Existing running projects, original
ParcelDesk and deployed services remain untouched. No real charge, customer send,
provider mutation or deployment is authorized by these local checks.

## Ownership

| Lane | Owned paths/work | Shared seam |
| --- | --- | --- |
| Local payment settings | New payment_settings router/static/tests/docs; narrow native configuration API/service/helper revision and transaction changes | Integrator mounts router, native nav and 3 static files; shared native cleanup adds gateway intent prefix |
| Local parcel review | New parcel_reviews domain, narrow existing parcel API/UI/helper extension, tests/docs | Existing ParcelAudit/links/worker/outbox; no new sender/enrollment path or DDL proposed |
| Local assisted onboarding | New assistance model/schema/API/domain/native workspace/tests/docs in munimjee-v1-sales-console | Integrator owns 0050 DDL/model/main/nav/package and final composition |
| Remote imports/themes/QA | Actual reviewed import allocation UI, persisted theme0049 and all-three public rendering, independent QA | Integrator owns main/config/package/shared native client/public payment shell; owners propose exact hooks |

Do not rewrite another lane's shared payment state machine, worker or storefront
shell. Isolated branches start from the verified base; preserve previous worktrees.
Each owner requests a migration before authoring it. Registrations/nav/package
changes are central, not competing feature commits.

## Migration and test reservations

- Remote `0049_v1_storefront_settings` → actual `0048_v1_parcel_tracking` remains
  reserved. No fake predecessor, proposed-DDL-only or create_all acceptance.
- Local `0050_v1_assistance` → actual 0049 is reserved for onboarding assignment
  and immutable assistance command receipts. It is additive and backfills no
  memberships/permissions. Domain code can proceed independently; actual 0050 DB
  proof waits for committed 0049, then rebuilds the exact chain.
- Payment/parcel propose no DDL. Further revisions require central allocation.
- Existing dedicated PostgreSQL 16 port 55442 only. Payment owns payment_w3,
  parcel owns parcel_w3; console and central integration use the coordinator's
  wave3_integration lane sequentially with P01 lease/reset guard. Never touch
  another lane or use production/environment fallback. No Redis allowance.
- Payment UI port 8162. Parcel coordinates 8155 connector/8156 native test ports.
  Console uses 8163. All fixtures use synthetic provider/SDK/refresh data and own
  exact process/nonce validation. Original previews/services are preserved.

## Native payment settings

Page `/v1/businesses/{business_id}/payments` inherits commerce.css and the native
V1 session/CSRF client. Staff/viewer receive access guidance with no configuration
GET. Existing native GET/PUT `/api/v1/businesses/{bid}/payments/razorpay` remain
business.write; no credential save calls a provider. Legacy `/commerce/razorpay`
request, verification and commit behavior remain unchanged.

Native responses add opaque `configuration_revision`: a server HMAC of a domain
separator and canonical current key ID/mode/enabled/encrypted secret ciphertext,
including a deterministic absent state. No raw credential or secret-derived
client digest is exposed. Native PUT optionally accepts `expected_revision` for
existing API compatibility; this UI always sends it. After Seller lock and
current native session/capability recheck, compare fresh scalar revision before
any mutation. Only that mismatch returns typed 409 `gateway_config_stale`.
Native writes flush under the held lock and use business_mutation before outer
get_db commit; safe fields and revision come from one snapshot. Legacy helper
keeps commit=True/provider verification by default.

A GET cannot prove a lost secret update. After an unknown PUT: erase secret
inputs/body; preserve only a nonsecret user/business/native-session-bound marker,
expected revision, intended key/mode/enabled and timestamp. No automatic retry or
'saved' claim from GET. Read current safe settings, then offer an explicit fresh
replacement requiring re-entry of both secrets, review and latest revision.
An old pending conditional PUT cannot overwrite that newer replacement. A
confirmed 200 can be a no-op with the same revision. Persisted prefix:
`munimjee.v1.gateway-intent:`; central identity/logout/401 cleanup clears it.
Configured/local encryption readiness is not a verified provider account/canary.

## Reviewed parcel recovery

Reuse immutable ParcelAudit and existing link/unlinked states; no DDL anticipated.
All operations remain under an authorized selected order. Audited idempotency
checks bind business/key/body/actor and precede preview expiry on exact retries.
Lock Order→Link; revalidate native session/capability after row/HTTP waits. Full
fingerprints include order, link identity/state/lease/snapshot and trusted current
connector configuration, not just the legacy revision counter.

- Reviewed resume uses fresh scoped resolve/read only, never ensure. Require
  exact owned tenant/instance/courier/AWB/remote identity and explicit label/status
  confirmation. Unknown/unowned/multiple/not-found stays manual review.
- Close stops the local association, preserves old row/history/audit and tells
  the operator uncertain remote records/in-flight provider effects cannot be
  recalled. It changes no fulfillment/payment/customer consent.
- Replacement atomically closes the old association and creates a durable new
  same-order link command only after fresh label preview and explicit old-effect/
  new-label confirmation. Same parcel identity is not a replacement. Existing
  process_link remains the only enrollment writer. Invalidate the old lease so
  an older worker response cannot revive the old association.
- Resume/replacement records a skipped current-milestone baseline and no outbox.
  A fresh scalar review boundary in existing revalidate_notification blocks
  older queued messages. Later genuine eligible milestones use the existing
  sender and current consent/UTILITY/connector checks. Review itself never sends.
- Test worker-in-flight, concurrent replacement, stale/revoked/config changes,
  old queued messages around review, lost response/exact replay, physical camera
  fallback and truthful no-dispatch/no-payment-change copy separately.

## Assisted onboarding console

This is normal membership-based assistance, not a support grant or impersonation.
Native actors can list only active businesses they already belong to. Assignment
never creates membership, changes role or grants access. No global seller list,
legacy admin view_seller or staff legacy seller token is introduced.

Routes/DTO proposal (owned together, exact fixtures published before consumers):

- `/v1/assistance` and `/v1/businesses/{bid}/assistance`: native Operate workspace.
- GET `/api/v1/assistance/businesses`: bounded cursor page of current accessible
  businesses; optional assigned-to-me filter. Current readiness, import issues,
  local channel account-check scope/time and store/catalogue/publication gates;
  no customer data, provider credentials/account IDs, source bodies or secrets.
- GET `/api/v1/businesses/{bid}/assistance`: current readiness.read projection.
  It never infers provider approval, successful live test or complete onboarding.
- GET `.../assistance/assignees`: members.manage only; active owner/manager
  memberships as eligible onboarding leads. No implicit sales-support role.
- PUT `.../assistance/assignment`: native CSRF + members.manage, strict
  idempotency_key/expected_version/assignee_user_id|null/reviewed:true. Under
  Business NO KEY UPDATE and assignment lock, validate eligible same-business
  member, current session/capability and version; atomically save assignment,
  immutable tenant command receipt and safe audit. Revoke/downgrade does not
  resurrect eligibility; projections mark the old assignment needs-review.
- POST `.../assistance/open`: current readiness.read/native mutation, UUID key;
  record an immutable audited open before validated navigation. It is not an
  access grant and normal direct membership reads remain separately authorized.

0050 models: one versioned assignment per Business, nullable assignee composite
FK to Membership(business_id,user_id), assigned-by composite FK; tenant-scoped
immutable command PK(business_id,idempotency_key), actor membership FK, bounded
operation/hash/result and immutable receipt trigger. Assignment and command
writes never commit internally. No source/product/order data is changed.

UI preserves the existing native green/paper world: membership business list,
assigned lead, concrete next action and honest blockers. Current capabilities
control links/actions. Pending commands are scoped to native user/business/session
and replay exact saved bodies/keys; stale selection responses cannot overwrite
current business. Focus/visibility/session replacement/401 clears private DOM and
intent. Central shared cleanup reserves `munimjee.v1.assistance-command:`.

Support grants, analytics, verified customer identity links, global sales access
and full onboarding/provider acceptance are explicitly deferred. Existing
capabilities are not expanded to simulate them. Final acceptance requires actual
migrated PostgreSQL 16, mounted native desktop/mobile/browser failure paths,
independent source/UI review and refreshed final regression/package evidence.
