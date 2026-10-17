# V1 wave 2: authenticated product journeys

Base: verified `7de7cd68ce700e089bcf31e357aeebb08ea08299`, 17 October 2026.
This bounded wave adds usable native onboarding, gated SKU/order operations and
channel operator recovery, plus remote import persistence and storefront API
integration. It does not authorize production rollout, provider account consent,
paid/live sends or a claim that V1 is complete.

## Worktree and ownership boundaries

| Lane | Branch / new worktree | Owned work |
| --- | --- | --- |
| Local auth/integrator | codex/v1-auth-onboarding / munimjee-v1-auth-onboarding | Native sessions/signup/login, transactional seller bridge, invitation basics, business profile, resumable derived checklist and `/v1` app journey; shared registration and guarded legacy auth transition |
| Local catalogue | codex/v1-checkout / munimjee-v1-checkout | Reviewed product/SKU API, explicit reconciled activation, canonical commerce_orders SKU checkout/reservations and required uncertain-payment guard; narrow legacy commerce release/active-product protection |
| Local social | codex/v1-channel-operator / munimjee-v1-channel-operator | Paginated operator recovery UI, audited/idempotent reviewed replay/resolve, channel readiness and owner-only connection lifecycle with synthetic provider transports |
| Remote imports | Remote coordinator assigns | Durable authorized import/review jobs and persistence; consume catalogue approved-write seam; no implicit publication or untrusted factual inference |
| Remote storefront | Remote coordinator assigns | Real versioned public catalogue APIs, canonical product routes and preview/publication boundaries; consume SKU checkout only after activation contract |
| Integration/QA | Integration branch | Review each change, actual full Alembic chain, P01 test safety, PostgreSQL 16 parity and browser product journeys/failure matrix |

Running checkouts and Parcel Desk source remain read-only. Worktrees start from
the verified base; subsequent shared contract/migration commits are cherry-picked
explicitly. No worker resets another lane's database or queue. Parcel connector
implementation follows the SKU milestone or an explicit separate handoff; this
wave does not quietly grow into a third catalogue feature stream.

## Migration reservation

| Revision | Owner | Parent |
| --- | --- | --- |
| 0043_v1_auth | Auth/integrator | 0042_instagram_ingress |
| 0044_v1_checkout | Catalogue | 0043_v1_auth |
| 0045_v1_channel_operator | Social | 0044_v1_checkout |
| 0046_v1_import_jobs | Integrator (reviewed remote D20 models) | 0045_v1_channel_operator |

The integrator publishes 0043 early. A worker may build pure logic and test owned
DDL while predecessor work is pending, but only the actual complete chain counts
as migrated integration evidence. Do not invent predecessor files or silently
change revision identifiers. Remote D20 persistence is now allocated centrally as 0046. Further migrations
require another central reservation; do not collide with this chain.

## Native actor, session and mutation contract

- `app.api.v1.identity.current_actor` remains the read dependency; native tokens
  require a persistent active session, active user and current auth version.
- `app.api.v1.session.require_v1_mutation` returns the authorized `Actor` and adds
  browser mutation protection. Feature routes use it before their own tenant and
  capability checks. They do not create their own session/CSRF implementation.
- Native JWT: `role=v1_user`, `purpose=v1_actor`, `sub=User UUID`, `sid=session UUID`,
  signed expiry. No staff/support user receives a legacy `role=seller` token.
- Cookie `v1_session` is HttpOnly, SameSite=Lax and secure on HTTPS. Readable
  `v1_csrf` is bound by digest to the active session; cookie mutations require
  matching `X-CSRF-Token` and exact allowed Origin. Explicit bearer requests do
  not fall back to cookies and do not rely on cookie CSRF.
- `GET /api/v1/auth/session` returns the `/api/v1/me` fields plus `csrf_token` for
  the current native browser session. Unauthenticated/native-invalid responses
  are 401. Login/signup return native session actor data and set cookies.
- New routes: `/api/v1/auth/signup`, `/login`, `/logout`, `/logout-all`; business
  profile `/api/v1/businesses/{id}/profile`; membership invitations under
  `/api/v1/businesses/{id}/invitations`, token acceptance under `/api/v1/auth/invitations/accept`.
- Auth/invite routes are feature-gated by `V1_AUTH_ENABLED` (default false).
  Supported legacy auth enforcement is separately gated by
  `V1_ENFORCE_LEGACY_ACCESS` (default false). Isolated product tests enable both.
  New native sessions always require session validity; there is no insecure
  sessionless-native fallback. The compatibility flag is not a new auth bypass.
- Supported legacy bearer/dashboard/account-linking checks consult the bridged
  user/owner membership when enforcement is enabled. App-wide revoke-all blocks
  older legacy tokens through a revocation cutoff; membership/user revocation
  fails closed. Existing delivery auth and legacy workflows are preserved when
  the rollout flag is off. Versioned support impersonation remains denied.
- Login/logout clear competing V1/legacy/view cookies; switching identity revokes
  the previous native browser session. Existing native users must authenticate
  before invitation acceptance; email/phone alone never merges identities.
  Invitation bearer secrets are one-use, expiring, hash-stored and not sent by
  this code. No email-verification or provider-approval claim is implied.

## Tenant/capability and UI contract

Business ID remains Seller UUID. Every operation derives actor from the server,
checks the target membership and then its specific capability. Reads cannot reveal
foreign existence; protected mutations cannot accept actor/tenant authorization
from imported bodies. `members.manage` and channel connect/disconnect remain
owner-only. Operator review uses `automation.manage`; operator reads use
`inbox.read`. Support grants are a separate future expiring/audited authorization.

Native `/v1` UI must use real endpoints and persistence. Acceptance begins with a
fresh synthetic signup, edits business details, logs out/in, and resumes the same
checklist. Profile completion is persisted; catalogue/channel/publication/payment
readiness is derived from actual backend state. Do not turn a checkbox into proof
of a connected account, approved catalogue or provider canary. Each incomplete
step has an actionable reason and truthful pending/external status.

Existing operating UI is the visual reference. Separate feature HTML/JS/CSS files
avoid shared-shell collisions; the auth lane owns `v1_app`/`v1_client` foundations,
social owns `channel_operator` pages. Browser actions carry native cookies/CSRF.

## Catalogue/order activation contract

- Preserve catalogue.v1 preview semantics and `checkout_enabled=false`.
  Operational public reads use a distinct `catalogue.v2` contract, with explicit
  mode/activation and store checkout policy; publish representative fixtures.
- Proposed seller API prefix:
  `/api/v1/businesses/{business_id}/catalogue/products`; capability catalogue.read/write.
  Public API prefix `/api/v1/storefronts/{slug}` with product reads and `/checkout`.
- SKU checkout lines contain `sku_id` and quantity. Existing customer/address,
  payment choice and idempotency semantics remain authoritative on the server;
  client prices, stock and tenant identifiers never authorize an order.
- Explicit activation requires reviewed current allocation/fingerprint/revision
  and reservation reconciliation. It defaults off. No automatic migration of
  pending legacy reservations, and no fallback from an active SKU product to
  stale legacy stock even when checkout policy is disabled.
- Lock order: storefront → Product → mapping → SKU/reservations. Protect active
  Product stock/prices/variants from legacy writers. Release stock through the
  immutable order engine marker. Existing captured-payment authority and signed
  callback checks remain intact; unknown provider creation outcomes require a
  durable uncertain attempt and exact reconciliation before another POST.
- Once activated, legacy Product facts are a compatibility snapshot. Messaging
  consumers must use the SKU authority seam or hand off; they cannot promise
  price/availability from the frozen aggregate snapshot.

## Channel and import boundaries

Reviewing an unknown send requires authorization, explicit acknowledgement and
current eligibility; an expired/unknown provider window or another uncertainty
hold means resolve-only/handoff. Provider timestamps are persisted when signed;
old receipts without trustworthy time are not assumed eligible. Audits and
idempotency keys survive reload/retry. Resolve-without-replay never sends.

Channel readiness distinguishes configured, credential-valid, connected and
actually tested. Native OAuth state is bound to actor/business/browser and checked
at both ends; support cannot authorize the owner's accounts. Tests use synthetic
transports only; live Meta permissions, consent and message recipients remain P03.

Imported facts stay draft/reviewed with provenance and seller corrections. The
approved-write bridge creates canonical catalogue drafts/review records, not live
publication. Unknown extracted stock is distinct from explicitly untracked SKU
stock. No worker fetches private networks or executes source instructions.

## Evidence gate

Use a new isolated PostgreSQL 16 container if resources permit; exact P01 lane
URLs are allocated after local verification. Preserve the first-wave PostgreSQL
15 container and every running service. Each merge requires owned tests, negative
tenant/role/CSRF/session cases, actual migrated-schema checks and browser journeys
for its working UI. Record exact source SHA, counts/skips and external blockers.
Missing provider access/device evidence remains pending, while independent work
continues. This is not production/cutover permission.
