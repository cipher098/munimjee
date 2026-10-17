# Native account and onboarding slice

This adds the working `/v1` account journey behind `V1_AUTH_ENABLED=false` by
default. A fresh account creates Seller → Business → User → owner Membership in
one transaction. Business ID remains the legacy Seller ID. Native sessions use
`role=v1_user`, `purpose=v1_actor` and a persistent signed session ID; they never
become legacy seller tokens. Support impersonation remains unavailable.

## Working journey

Signup or password sign-in opens a business checklist. Business details save to
PostgreSQL with optimistic version checks. Sign-out/sign-in resumes those details.
Owners create one-use, seven-day invitation links, copy them privately and revoke
unconsumed links. Existing invitees must prove their account password before
joining; matching email/phone is never identity proof. New invited staff have no
legacy Seller identity. Revoked memberships are never resurrected by invitation.
The API supports membership revocation; owner transfer is deliberately separate.

Profile completion is persisted. Catalogue counts are derived from actual rows,
but this slice does not claim allocation/activation freshness or provider approval.
The checklist only links to registered workspace routes. Missing catalogue UI,
channel authorization, public storefront, payment canary and Parcel Desk connector
remain separate product gates. `onboarding_complete` remains false here.

## Session boundaries

- Cookie mutations require a current persistent session, matching session-bound
  CSRF cookie/header and exact allowed Origin. Explicit bearer credentials never
  fall back to browser cookies. Foreign supplied login Origins are rejected.
- Cookie identity changes revoke the previous native session and clear competing
  native, seller, dashboard and view-as cookies. Native logout revokes the exact
  session; logout-all increments the user's auth version and revokes all sessions.
- `V1_ENFORCE_LEGACY_ACCESS=false` preserves legacy authorization during staged
  rollout. When enabled, bearer seller, dashboard seller and account-linking gates
  check the active bridged owner/user/membership. Logout-all rejects older legacy
  tokens through an issuance cutoff. Fresh credential proof can sign in again.
- The enforcement flag also denies admin view-as access until separate expiring
  support grants exist. Existing delivery auth is unchanged. This is a rollout
  boundary, not a claim that legacy revocation is enforced with its flag off.
- Legacy GET logout never mutates a native session: it returns the native
  workspace, whose logout is a protected POST. Legacy login/signup reject foreign
  supplied Origins when rollout is enabled or any native cookie is present.
- Invitation responses are bound to the originating business/view generation.
  Business switches discard delayed results; identity changes clear invitation
  bearer links, invitee fields and cached private workspace DOM.
- Login inputs, invitation tokens and audit details are bounded. Tokens are hashed
  at rest; raw invitation links are returned once and are not sent by this code.
  Native/private responses use `Cache-Control: no-store`.

## Verification

Actual PostgreSQL 16.15 migrations through `0043_v1_auth`, P01 disposable lane
`auth_wave2` on loopback port 55442. No production database, Redis worker or provider
calls. Tests reset only `munimjee_test_auth_wave2` while holding its advisory lease.

- 93 focused auth/identity/legacy commerce safeguards checks passed; the final
  route/cache/link update was followed by all 12 HTTP onboarding checks passing.
  The final legacy CSRF regression brings HTTP onboarding coverage to 14 checks.
  An additional retained-ORM-context concurrency regression passes after explicit
  locked-row refresh; the ordinary route already released its clean weak refs.
  Without refresh, deliberately retained contexts reproduce two successful saves;
  with refresh, one succeeds and the other returns 409.
- 16 real Chromium assertions pass against the actual served app and migrated DB:
  desktop/mobile signup, profile persistence and resumed login, stale-save conflict,
  CSRF denial, separate-browser viewer invitation, role-limited controls, logout
  and logout-all. An actual committed invitation response is delayed while the
  browser switches businesses; its bearer link is discarded and logout clears
  invitee/link DOM state. Screenshots were inspected at 1365px and 390px; no horizontal
  overflow or browser JavaScript errors. No auth/profile/invite DTO mocks.
- Failure matrix covers expired/revoked/mismatched/revoked-inviter invitations,
  concurrent duplicate signup and invitation consumption, tenant existence hiding,
  staff denial, native session expiry/revocation/version mismatch, identity switch,
  bridged legacy signup, supported legacy revocation and flag-off compatibility.

Reproduce from repository root after installing backend dependencies and
`npm ci --ignore-scripts` in `frontend/storefront`:

```sh
TEST_DATABASE_URL=postgresql+asyncpg://wave2test:wave2-local-only@127.0.0.1:55442/munimjee_test_auth_wave2 TEST_LANE=auth_wave2 TEST_DB_RESET=1 PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_v1_auth_onboarding.py backend/tests/test_v1_auth_sessions.py backend/tests/test_v1_identity.py backend/tests/test_v1_identity_db.py backend/tests/test_commerce_safeguards.py -q -ra
TEST_DATABASE_URL=postgresql+asyncpg://wave2test:wave2-local-only@127.0.0.1:55442/munimjee_test_auth_wave2 TEST_LANE=auth_wave2 TEST_DB_RESET=1 PYTHONPATH=backend .venv/bin/python -m tests.run_v1_browser
```

The browser runner requires its own free loopback port 8012, creates no reusable
server and terminates it on success/failure. Server-side sockets remain restricted
to the validated test database. Browser requests outside that server are aborted.
Its screenshots are synthetic evidence under `artifacts/v1/auth-wave2/`.
