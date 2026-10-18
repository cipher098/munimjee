# Assisted onboarding through existing business access

The native Onboarding workspace lists only active businesses the signed-in user
already belongs to. It lets an owner assign an existing active owner or manager
as the onboarding lead. Assignment changes responsibility only: no membership,
role, seller token, support grant or impersonation is created.

Open `/v1/assistance` or `/v1/businesses/{business_id}/assistance`. The six next
steps show business details, import review, catalogue/stock, channel checks,
publication/checkout and payments. Links appear only for mounted routes and
current capabilities. Account checks are explicitly local; provider approval,
live messaging/payment acceptance and complete onboarding are never inferred.
No customer, credential, provider account ID or raw source content enters this
projection. All pages/API responses are private and no-store.

The board API is `GET /api/v1/assistance/businesses?limit=20&after=<UUID>` with an
optional `assigned_to_me=true` filter. Detail and member choices live beneath
`/api/v1/businesses/{business_id}/assistance`; member choices and assignment
require `members.manage`. `PUT /assignment` uses a UUID idempotency key, expected
version, nullable assignee UUID and strict `reviewed:true`. `POST /open` records
an audited workspace opening under the actor's own identity. Direct business
reads remain separately authorized; an open receipt is not an access grant.

Actual migration `0050_v1_assistance` follows committed
`0049_v1_storefront_settings`. Assignment/actor composite foreign keys require
same-business Membership rows. Business `FOR NO KEY UPDATE` serializes initial
and later writes without conflicting with ordinary tenant foreign-key checks.
Version CAS, active-assignee SHARE locks, native reauthorization after waits and
the final caller-owned `business_mutation` guard protect the transaction. Assignment,
immutable exact-key command receipt and safe identity audit commit together.
Post-flush revocation rolls all three back. Receipts are actor/body/operation
bound and cannot be updated or deleted through SQL.

Unknown browser responses retain the exact command/body/key in sessionStorage
under `munimjee.v1.assistance-command:` scoped to native user, business and a
hash of the native CSRF secret. No automatic replay occurs after reload. Only a
matching command acknowledgement clears it. The exact typed
`assistance_assignment_stale` conflict is emitted after serialized receipt
absence and before mutation; it permits reviewing a new assignment. Other
failures retain the original action. A failed network-only access check clears
private DOM but preserves the journal for the same session; confirmed identity
change, logout or401 clears it. Current session projections remove revoked
nonselected businesses, member labels and newly unavailable controls/links.

Verification in the isolated console checkout: **36 passed** (17 actual migrated
PG16/API and19 pure contract cases), plus **24 actual mounted Chromium checks**.
The runner holds one P01 lease over reset, actual Alembic migration, server and
browser; all provider sockets are blocked. Browser cases cover native signup,
assignment/clear, lost committed response/reload/same-key recovery, actual
viewer invitation, two-business selection, delayed old response, external
membership revoke/downgrade and held old session response after replacement.
Artifacts are in `artifacts/v1/assistance/`. This feature checkout uses the exact
committed0049 migration as a local test dependency; only0050 is owned here.
Final central composition/profile-link/runtime checks are recorded separately.

The existing green/paper commerce interface is preserved. Desktop,390px viewer,
owner and session-ended captures were inspected; no horizontal overflow or
JavaScript errors occurred. The single detector run reported one inherited
linked commerce.css11px text warning; main body text is14px. Independent peer
source/render disposition is recorded with the final integration evidence.

Support grants, global sales access, analytics, verified customer-identity links,
live-provider acceptance and production rollout remain explicitly outside this
bounded slice. Existing membership access must be established through the normal
owner-reviewed invitation flow.
