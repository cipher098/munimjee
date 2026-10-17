# V1 identity foundation (A10 first slice)

This is an additive identity foundation, not complete seller onboarding. It adds
`Business`, `User` and `Membership`, resolves authenticated actors, and exposes
read-only identity/readiness APIs. Legacy login, dashboard and seller endpoints
retain their existing behavior. Nothing in this slice connects provider accounts,
issues staff sessions, invites users, publishes stores or merges customer records.

## Compatibility and persistence

`Business.id` is the existing `Seller.id`, enforced by a foreign key. Existing
seller-owned tables keep their seller foreign keys. A `User.legacy_seller_id`
uniquely records the authenticated legacy seller account; phone and email are not
identity-linking evidence. Owner user and membership IDs use separate UUID5 names
under `uuid.NAMESPACE_URL`:

- `munimjee:v1:legacy-owner:{seller_uuid}`
- `munimjee:v1:legacy-owner-membership:{seller_uuid}`

Migration `0040_v1_identity` follows actual baseline revision `0039`, creates the
three tables, and backfills existing active and inactive sellers. Inactive sellers
receive inactive bridge records. Backfill uses bounded insert batches with
`ON CONFLICT DO NOTHING`. `services.identity.ensure_legacy_owner_bridge` provides
the same mapping for future signup transactions, while `backfill_legacy_owners`
provides a transactional maintenance helper. These helpers never commit.

No read request provisions an identity. A new legacy seller created after the
migration remains unavailable in V1 until an authorized signup integration or
backfill explicitly creates the bridge. This avoids regranting access from an old
session. Rerunning either backfill preserves disabled users/businesses, revoked
memberships and changed roles. A revoked membership must retain its row and
`revoked_at`; deletion is not the revocation mechanism.

Memberships require existing business/user rows and unique `(business_id,user_id)`.
Roles are constrained in the database. Deleting referenced tenants/users is
restricted. Each authorization checks user, membership, business and legacy seller
activity. Unknown and inaccessible businesses both return 404.

## Frozen capability matrix

| Capability | Owner | Manager | Staff | Viewer |
| --- | --- | --- | --- | --- |
| business.read, readiness.read | Yes | Yes | Yes | Yes |
| business.write | Yes | Yes | No | No |
| catalogue.read | Yes | Yes | Yes | Yes |
| catalogue.write | Yes | Yes | No | No |
| orders.read, inbox.read | Yes | Yes | Yes | Yes |
| orders.write, inbox.reply | Yes | Yes | Yes | No |
| automation.manage | Yes | Yes | No | No |
| analytics.read | Yes | Yes | No | Yes |
| channels.connect, channels.disconnect, members.manage | Yes | No | No | No |

Capabilities are derived from current database memberships, never from JWT role
claims. An unknown membership role grants nothing. Future V1 mutation endpoints
must call `require_business_access(db, actor, business_id, capability)` for their
specific capability; this foundation does not implement those mutations.

## Authentication and routes

The V1 resolver accepts the first credential in this order: explicit bearer header,
`v1_session`, `dashboard_session`, `seller_session`. A malformed explicit bearer
never falls back to a cookie. Signatures, subject and expiry are required.

- Legacy `role=seller` API bearer/session: subject is Seller UUID.
- Legacy seller dashboard cookie: `seller_id` is Seller UUID; subject may be email.
- Both legacy formats require the deterministic, active legacy owner user and an
  active **owner** membership. A downgraded member cannot keep owner privileges
  through an old legacy token. `view_seller` has no authority here.
- Native V1 credential: `role=v1_user`, `purpose=v1_actor`, `sub=User UUID`.
  It cannot pass the existing legacy `role=seller` dependency. This slice does not
  mint these credentials; an eventual login/invitation flow must use this distinct
  role and retain server-side membership checks.
- Admin/dashboard impersonation, delivery and support credentials are denied.
  Support requires a future separately authorized, audited, expiring grant. It is
  not a membership role in this contract.

| GET route | Result |
| --- | --- |
| `/api/v1/me` | User UUID, authentication method, accessible businesses/roles/capabilities |
| `/api/v1/businesses` | Active accessible businesses only |
| `/api/v1/businesses/{business_id}` | Explicitly authorized business view |
| `/api/v1/businesses/{business_id}/readiness` | Identity readiness and unevaluated onboarding gates |

Views allowlist ID, name, role and capability fields. They exclude credentials,
private catalogue values, contact identifiers and internal notes. Readiness has
`scope=identity_foundation`, `identity_ready=true` after authorization, and
`onboarding_complete=null`. Catalogue review, connections, publication and checkout
are explicitly `not_evaluated`; legacy `onboarding_state=active` does not prove V1
readiness.

## Integrator-owned registration

Add to `backend/app/models/__init__.py`:

```python
from app.models.identity import Business, User, Membership
__all__ += ["Business", "User", "Membership"]
```

Add to `backend/app/main.py` with its other router registrations:

```python
from app.api.v1.identity import router as v1_identity_router
app.include_router(v1_identity_router)
```

Future signup must flush the seller and then call
`await ensure_legacy_owner_bridge(db, seller)` **inside the signup transaction**.
Do not call this from authentication dependencies, and never issue legacy seller
tokens to manager/staff/viewer users.

## Verification and remaining gates

On 17 October 2026, 39 checks passed using Python 3.11 and a coordinator-allocated
local disposable PostgreSQL container. 31 pure checks cover authentication format,
signature/expiry, cookie precedence, capability limits, deterministic IDs and
response allowlists. Eight database cases run actual Alembic upgrade functions
from revision 0001 through 0039 in fresh rollback-only schemas, insert legacy
sellers, then apply 0040. No ORM `create_all` replaces migration coverage.

Database cases verify repeated migration/service backfills, preserved revocations
and downgrades, inactive tenants/users, unique/FK/role constraints, identical
unverified phones remaining separate users, two-tenant access, native viewer API
responses, denied admin impersonation and explicit bridging for new sellers.
Tests require `V1_IDENTITY_TEST_DATABASE_URL` to exactly match the coordinator's
allocated disposable test URL; they never target configured `DATABASE_URL`.
Each generated schema and its data disappear when its transaction rolls back.

Run from the worktree with synthetic settings and `PYTHONPATH=backend`:

```sh
.venv/bin/python -m pytest backend/tests/test_v1_identity.py backend/tests/test_v1_identity_db.py -q
```

Without the allocated database environment variable, the eight DB checks skip;
that is not a database validation pass. Existing Pydantic class-config and HTTPX
per-request cookie deprecation warnings remain. Integrator router/model registration
and independently rerunning the full integrated migration chain remain required.
Invitations, native login/token issuance, business creation UI, resumable onboarding,
verified customer links, sales assignments/support grants, audit events and full
readiness evaluation belong to later slices.
