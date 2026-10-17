# V1 wave 3: reviewed imports, payment handoff and order parcel tracking

Base: verified `aa6ac940ef877a8a37baac39afec44268b49f84e`, 18 October 2026.
Workers remain GPT-6.1 Sol / High. This is another bounded implementation wave,
not authorization for production deployment, live payments, Meta consent,
courier/provider calls or customer sends. Existing running checkouts, services
and the original Parcel Desk project remain untouched.

## Ownership and shared seams

| Lane | New worktree/branch | Owned implementation |
| --- | --- | --- |
| Import bridge / integrator | munimjee-v1-import-catalogue-bridge / codex/v1-import-catalogue-bridge | New approval receipt model/migration, reviewed import-to-private-product service/schema/API/tests; central registrations, shared shell and integration |
| Public payments | munimjee-v1-online-checkout / codex/v1-online-checkout | New checkout-session schema/API/domain and `payment-handoff.js`, transport/security/browser tests and contracts; preserve existing COD and legacy Product payment behavior |
| Parcel tracking | munimjee-v1-parcel-integration / codex/v1-parcel-integration | New parcel models/API/service/native page/worker/tests; separate source-only Parcel Desk connector copy under work/parcel-desk-v1-connector with its own Git history |
| Remote imports/theme/QA | Parent coordinator assigns | Native import workspace consuming existing jobs/review and the new bridge; persistent seller theme settings; independent failure/UX review |

The integrator owns `main.py`, model registration, shared configuration,
`v1_client`/onboarding and shared storefront modules (`live-app`, canonical decoder,
public provider/bootstrap/CSP). Feature owners propose narrow hooks instead of
competing edits. Parcel owns a separate native order parcel page; the integrator
adds its link to the catalogue order view. Payment owns a dedicated client module;
theme work does not rewrite its state machine. Future static/runtime dependencies
must enter the explicit package/bootstrap allowlists.

## Migration reservations and test lanes

| Revision | Owner | Parent |
| --- | --- | --- |
| 0047_v1_import_catalogue_bridge | Import bridge / integrator | 0046_v1_import_jobs |
| 0048_v1_parcel_tracking | Parcel | 0047_v1_import_catalogue_bridge |
| 0049_v1_storefront_settings | Remote theme configuration | 0048_v1_parcel_tracking |

Payment currently reuses `SKUPaymentAttempt` and needs no DDL. Any additional
migration requires a new central allocation. No fake predecessor or `create_all`
proof: consume actual committed migrations and rebuild only the allocated lane.

Existing dedicated PostgreSQL 16 uses numeric loopback port 55442. New databases
are `munimjee_test_import_bridge_w3`, `munimjee_test_payment_w3`,
`munimjee_test_parcel_w3`, and `munimjee_test_wave3_integration`; `TEST_LANE` is the
matching suffix. P01 URL/reset validation, held migration/reset leases and blocked
provider networking remain mandatory. No worker uses another lane's database.
No Redis allowance is needed. Parcel's separately approved Node test transport
may reach only the explicitly hardcoded 127.0.0.1:8155 connector fixture, with
path/origin checks and redirects forbidden; this does not relax P01 or certify
production provider networking. Its native browser port is 8156.

New rollout flags `V1_PUBLIC_PAYMENTS_ENABLED`, `V1_IMPORT_BRIDGE_ENABLED` and
`V1_PARCEL_ENABLED` default false. Private parcel connector configuration defaults
empty; only explicitly provisioned exact Business/instance/origin bindings exist.

## Reviewed import-to-catalogue bridge

Existing job/review endpoints remain valid. Import approval alone still does not
publish, activate or overwrite catalogue inventory. New endpoints under
`/api/v1/businesses/{business_id}/imports/candidates/{candidate_id}`:

- `GET /catalogue-preview`: native actor and `catalogue.read`; current candidate
  revision, effective reviewed facts, unresolved/unsupported reasons, explicit
  allocation proposal and an existing receipt/product link when already created.
- `POST /catalogue-draft`: native mutation/CSRF plus `catalogue.write`; body
  `idempotency_key`, `expected_revision`, `seller_reviewed:true`, all five
  `confirmed_fields`, bounded `allocations[{options,stock_available,active}]`,
  optional explicitly reviewed `photo_urls` and `category_id`. No tenant/actor,
  arbitrary product ID, inferred title/price or browser price authority.
- The operation confirms a complete review-required candidate (or accepts its
  already approved current revision), creates a private canonical Product/SKUs
  using the existing reviewed writer, and saves provenance/receipt/audit in one
  transaction. A failure rolls all of that back. It never publishes, activates,
  enables checkout, changes another product or updates an existing reservation.
- Response `import-catalogue.v1`: receipt/candidate IDs, immutable approved
  candidate revision, product ID, catalogue URL, `creation_mode:private_draft`
  and `replayed`. HTTP201 is new; HTTP200 is an exact-key receipt replay after
  current authorization. A changed body/key collision or another attempt to
  create a product for the same source candidate is409.
- Source/extracted facts and seller overrides remain intact in the snapshot.
  Unknown stock stays unknown and blocks the bridge; it never becomes untracked
  inventory. INR decimal prices convert exactly to bounded minor units; other
  currencies require explicit correction, never conversion. Every supported
  option combination is explicitly allocated, with integer quantities summing
  to the confirmed total. More than500 combinations requires review/manual work.
  Website URLs, private upload blobs and evidence are not inferred photo URLs.
- The business/store/candidate write order and fresh authorization after lock
  waits fence concurrent reviews/bridge attempts. Tenant composite FKs and
  uniqueness enforce candidate/product ownership and one canonical creation.
  Reimport proposes review; it never silently overwrites the linked product or
  creates a duplicate under a fresh command key. Existing product editing and
  activation remain in the catalogue workspace.

## Public Razorpay handoff

`V1_PUBLIC_PAYMENTS_ENABLED` defaults false and applies to new versioned SKU
acceptance/advertising, preserving legacy Product payment behavior. New
`POST .../storefronts/{slug}/orders/{id}/checkout-session` uses the existing order
Bearer, no cookie fallback, and checks a supplied Origin against configured
canonical origin. It reuses the durable no-blind-retry gateway order guard.
`checkout-session.v1` exposes only the public provider key/order/amount/currency,
short-lived session capability, expiry, merchant/prefill and safe relative URLs.
All private capability/prefill/state responses are no-store.

The session JWT has distinct role `public_checkout_session`, purpose
`v1_public_checkout` and audience; it binds business/order/provider order and
exact amount/currency, expires within15 minutes and the reservation deadline,
and remains in memory only. It never enters a URL, SDK notes or stored order
confirmation. GET of the session path is a side-effect-free `checkout-state.v1`;
POST `/verify` uses the session Bearer and Razorpay success triple. Server
signature/captured-payment authority determines paid, never SDK success alone.
Ready existing orders may resume/verify when new acceptance is disabled; unknown
or requesting attempts never cause another provider POST without reconciliation.

SDK preparation occurs before accepting a new online order. Provider/local
credential readiness and the implemented client must all pass before online
payment is advertised. COD remains operational. Session, signature mismatch,
timeout, duplicate callback, reload, stale reservation, late capture and current
gateway changes require synthetic transport/browser evidence. Real provider
canaries remain an external acceptance gate.

## Parcel Desk integration

The initial machine connector binds exactly one configured Business and instance.
There is no shared browser-cookie authority. HMAC covers method, canonical path
and query, raw body hash, timestamp and request UUID, with five-minute skew,
durable nonce handling, rotatable key IDs and read/enroll/refresh scopes.
Machine operations are exact resolve, idempotent ensure, by-ID read and optional
refresh under `/integration/v1`. Unowned legacy duplicates require manual review;
they are never automatically assigned or disclosed to another tenant.

Munimjee configuration maps approved credential references to exact Business,
instance, allowed origin/key ID/secret and enabled state. DB links store the
reference only; browsers cannot submit connector credentials or arbitrary URLs.
An authorized order anchors preview (`scan_id,courier_id,awb`), then explicit
confirmation (`idempotency_key,candidate_token,expected_order_fingerprint,
confirmed:true`). The preview capability is actor/order/parcel/fingerprint bound
and expiring. A durable link command commits before external ensure; uncertainty
retains the stable command identity for scoped reconciliation/recovery.

One active parcel/order and parcel/connector is allowed initially. Unknown carrier,
ambiguous labels, camera denial and manual entry remain explicit. Local tracking
history appends/merges; older or terminal-regressing snapshots require review.
Tracking never changes order fulfilment/payment automatically. Milestone updates
use a new durable dedupe namespace and current explicit consent/template checks,
not the legacy once-only `order:shipped` key. Missing consent blocks notification,
not tracking. Native page: `/v1/businesses/{bid}/orders/{oid}/parcel`.

## Still outside this completion claim

Sales console, analytics, explicit expiring support grants, verified customer
identity links, full theme configuration/publication acceptance, legacy migration
reconciliation, international checks and provider approvals remain tracked scope.
No milestone silently removes them. Full migrated PostgreSQL16 tests, real native
browser journeys and independent source/UX failure review precede integration;
production deploy, real payments, Meta/courier calls and customer sends remain off.
