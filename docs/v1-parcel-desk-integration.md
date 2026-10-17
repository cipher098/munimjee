# Existing parcel tracking in the order dashboard

Design proposal, 17 October 2026. V1 shipping uses parcels already booked outside
Munimjee: open an order, scan its label, confirm the courier/AWB and order, link
the parcel, and display tracking updates to the customer. Online courier booking,
label purchase, shipping charges and carrier account onboarding are outside this
workflow. Registering an existing AWB for tracking is not courier booking.

This document is based on read-only local source inspection. No Parcel Desk file,
live database, deployment, carrier or customer was changed/contacted. All adapter
routes, authentication and tables described as proposed below remain unimplemented.

## Existing engine and verified interfaces

Source exists at:
`/Users/gothi/Documents/Codex/2026-10-13/ee/outputs/parcel-desk`.
No `AGENTS.md` was present in that directory or its inspected parent chain. The
existing React scanner, Cloudflare Worker, D1 store and provider adapters should be
reused; Munimjee must not build another courier polling engine.

| Current interface | Verified behavior and integration consequence |
| --- | --- |
| `GET /api/public/config` | Business display name, courier list and public origin. Not an authorization source. |
| `POST /api/login` | Shared staff username/password; same-origin check; HMAC expiry cookie, 12-hour lifetime. No user/tenant claims or scoped machine token. Do not copy this password or cookie into Munimjee/browser code. |
| `GET /api/shipments` | Shared authenticated instance; newest 300 unrevoked rows, including customer/phone/reference/tokens. No pagination, exact lookup, per-ID GET or change cursor. Cannot serve as a complete tenant-safe sync feed. |
| `POST /api/shipments` | Normalizes AWB by removing whitespace and uppercasing; validates supported courier and `[A-Z0-9-]{6,35}`. Stores an existing AWB, allocates tracking capability, then attempts refresh. Success is `201 {id,token}`. Duplicate courier/AWB is `409 {error,id}`, including an already-revoked row. No caller idempotency key. |
| `POST /api/shipments/{id}/refresh` | Requires staff cookie and matching Origin. Response `ok` describes refresh-queue processing, not successful courier lookup. Inspect persisted error, events and checked time. A recently successful check can return without a new lookup. |
| `POST /api/shipments/{id}/revoke` | Sets `revoked=1`; hides the shipment and invalidates public access. It is not a parcel cancellation or order unlink operation. |
| `GET /api/public/track/{token}` | Anonymous capability read; accepts 8-character or legacy 48-hex tokens; returns courier/AWB/status/events/ETA/check time, generic error and business name. No contacts. Returns 404 for missing/revoked. Reading does not refresh the courier. |
| Public page `/t/{token}` | Reads the public API every 60 seconds. Staff UI rereads its list every 15 seconds. These UI reads do not create a courier refresh cadence. |
| Worker scheduler | Calls the existing refresh queue. No incoming courier webhook handler or outgoing integration webhook/change feed is implemented. |

Evidence: `worker/index.js:7-10,33-55`, `src/main.jsx:6,9,12-23`, and
`migrations/0001_initial.sql:1`. Shipments have no business/order tenant column;
`UNIQUE(courier,awb)` applies to the entire D1 instance. `reference` is optional
free text, not a foreign key or proof of order/customer identity.

Supported provider IDs are fixed by `worker/providers.js:1-7`:

| Courier ID | Display name | Existing lookup path |
| --- | --- | --- |
| `tirupati` | Tirupati | Existing direct website parser |
| `aakash_ganga` | Aakash Ganga | Existing direct website parser |
| `skyking` | Skyking | Existing direct API adapter |
| `shree_maruti` | Shree Maruti | Existing direct API adapter |
| `dhl` | DHL Express | Existing 17TRACK adapter, carrier code 100001 |
| `fedex` | FedEx | Existing 17TRACK adapter, carrier code 100003 |
| `ups` | UPS | Existing 17TRACK adapter, carrier code 100002 |

These are verified implementation facts, not fresh provider/deployment availability
claims. 17TRACK registration is bounded by the configured monthly quota (default
100); failed registration releases the local quota reservation. Preserve that
behavior in the existing engine, including its uncertain-operation test needs.

Refresh details (`worker/refresh-queue.js:2-10`, `worker/index.js:11-29`): independent
60-second shipment leases, recovery after worker termination, scheduled batch size
8, unsuccessful/unfinished retry eligibility after 15 minutes and successful checks
after six hours. Scheduled refresh excludes `Delivered` and `Returned`; an explicit
refresh can still select them. Manual refresh has a 10-minute recent-success
shortcut. Worker-level timeout is 22 seconds; individual requests use 20 seconds.
Only `wrangler.jsonc:22-25` declares a 15-minute cron. The inspected alternate
`wrangler.dharaa.jsonc` and `wrangler.short.jsonc` omit triggers; verify the actual
deployment configuration before promising any live refresh schedule.

## Order context and confirmation

1. A signed-in seller with order-fulfilment permission opens an authorized
   `commerce_orders` order and chooses **Link parcel**. The page displays its order
   number, customer and current fulfilment state throughout the flow. Global scan
   intake must require selection of a specific authorized order first.
2. Reuse the barcode scanner in the order dashboard: start the camera on entry,
   stop tracks on cancel/hidden-tab/unmount, and require consistent detections.
   Keep manual AWB entry and optional existing photo intake available when camera
   permission/readability fails. Show simple processing progress/approximate ETA
   where processing takes time; technical implementation messages stay out of UI.
3. Barcode output proposes AWB and a courier hint. It never selects an order or
   proves recipient identity. The present scanner rejects multiple distinct
   barcode candidates and leaves many numeric formats courier-unknown. Current
   prefix hints include 391, 2603, 446, 4100, 87 and UPS 1Z; all require seller
   confirmation. Preserve leading zeros and the exact normalized AWB as text.
4. Resolve courier/AWB within the configured business connector. Show selected
   order, courier, AWB, existing tracker status/check time and any prior order link.
   Require courier selection when unknown; require explicit choice or manual entry
   when several barcodes/candidates exist. Never choose based on digit count,
   recipient OCR, customer phone, optional reference text or another tenant's data.
5. Seller confirms **Link this parcel to order MJ-…**. The backend rechecks order
   access, candidate expiry, current order version and existing parcel bindings
   before committing. A parcel already linked elsewhere is a conflict requiring
   authorized resolution; do not silently move it or reveal the other customer.
6. Link confirmation does not prove carrier handover, delivery or payment. Keep
   **Mark dispatched** as an explicit seller operation using existing payment and
   order transition checks. Polling must not bypass those checks or change stock,
   payment, refunds or cancellation state. A cancelled order may retain historic
   tracking; linking it requires deliberate historical association, not dispatch.

Scanner evidence: `src/barcode-scanner.jsx:6-15`, `src/barcode-result.js:2-7`,
`src/label-courier.js:1-25`. Actual phone-camera acceptance still needs a physical
device check; reading scanner code is not that evidence.

## Proposed tenant boundary and adapter API

Initial supported connector: one configured Parcel Desk instance belongs to one
Munimjee Business. Persist an operator-approved binding between `business_id`,
connector/instance ID and an allowlisted HTTPS base URL. Request bodies cannot
select another instance, arbitrary host or business identity. Do not expose the
existing global shipment list or shared staff login through a proxy. Supporting a
shared tracker instance across businesses requires real tenant columns, compound
uniqueness and scoped queries first; it cannot be simulated with UI filtering.

Minimum future extension to Parcel Desk, implemented in an isolated tracker
branch only after coordination and release authorization:

| Proposed machine route | Required contract |
| --- | --- |
| `GET /integration/v1/shipments:resolve?courier_id=…&awb=…` | Exact lookup in this instance's authorized scope. Return 0/1 safe summary or explicit revoked/conflict state. Never enumerate contacts or search all instances. |
| `POST /integration/v1/shipments:ensure` | Idempotently enroll an already-booked courier/AWB for tracking after seller confirmation. Body includes command UUID and courier/AWB only; no unnecessary customer phone/name. Return stable tracker shipment ID and existing/new outcome. Replay the same command safely after timeout; changed body with same UUID conflicts. Existing uniqueness is an additional guard, not complete command idempotence. |
| `GET /integration/v1/shipments/{shipment_id}` | Exact authorized snapshot, including active/revoked state, courier/AWB, raw status/events/ETA, last successful and attempted check times, generic error, snapshot version and public-link capability when allowed. A stale/missing link is explicit. |
| `POST /integration/v1/shipments/{id}:refresh` | Optional bounded refresh request through the existing queue/leases/quota/timeouts. Return accepted/cached/running state separately from courier lookup success. Not required on every order-page view. |

These endpoints do not exist today. Minimal V1 sync can poll exact linked IDs;
no new change cursor or webhook is required initially. If later scale needs a
cursor feed, it must include revocation tombstones, snapshot revisions and durable
cursor retention semantics; the existing newest-300 list is not an equivalent.

Use dedicated, rotatable machine credentials scoped to the configured instance and
Business. A concrete proposed request signature is HMAC-SHA256 over method,
canonical path/query, SHA256(body), Unix timestamp and random request ID, with
key ID in headers. Verify freshness (five-minute maximum skew), replay cache and
body size before lookup/mutation; TLS is mandatory. Keys remain server-side and
separate from `SESSION_SECRET` and staff passwords. Key rotation supports a bounded
old/new overlap. An operator binds the scope; a caller-provided business header is
not authority. Polling workers load credentials from the authorized connector,
never from scanned labels or public tracking URLs.

Proposed Munimjee order routes:

- `POST /api/v1/businesses/{business_id}/orders/{order_id}/parcels/preview` accepts
  normalized AWB/courier input and a client scan ID. It authorizes the order,
  resolves an existing tracker candidate without creation, and returns a short-lived
  signed candidate bound to actor/business/order/connector/courier/AWB and current
  order version. Unknown or ambiguous courier requires resolution before a candidate.
- `POST …/parcels` accepts command UUID, candidate token, expected order version and
  literal seller confirmation. Recheck current membership/role, order and link
  state. Commit a durable pending command, invoke tracking enrollment outside the
  DB transaction, then reconcile the stable result into an active link. A timeout
  becomes `enrollment_unknown`, never a fabricated success or a fresh-key retry.
- `GET …/parcels` returns authorized active/history links and safe tracking cache.
  Unlink/replacement is an explicit audited operation with expected link revision;
  it preserves history and does not revoke the remote parcel or cancel the order.

The exact route spelling and order-version mechanism require consumer review before
freezing. No new migration number is allocated by this proposal.

## Data ownership and reliable synchronization

Munimjee owns Business authorization, `commerce_orders` identity, order-to-parcel
association, actor confirmation/audit, notification consent and delivery. Parcel
Desk owns the stable tracker shipment ID, public capability, carrier adapters,
provider registration/quota, refresh scheduling and current courier snapshot.
Do not put order truth into Parcel Desk's editable free-text `reference` field.

Proposed Munimjee entities are additive, assigned to the integrator before coding:

- Connector binding: Business, immutable instance identifier, allowlisted origin,
  credential reference, enabled/revoked state and health/check timestamps.
- Order-parcel link: tenant/order composite FK, connector, stable remote shipment
  ID, normalized courier/AWB, link revision, active/superseded/unlinked state,
  confirmation actor/time, command/idempotency record and reconciliation state.
  Tenant-scoped uniqueness prevents one remote parcel being active on two orders.
  First V1 UI supports one active parcel per order; replacements remain historical.
  Split shipments need an explicit UI/contract extension before being claimed.
- Immutable observed tracking events: link ID, source identity, raw time/status/
  description/location, optional normalized UTC time, observation time and event
  dedupe hash. Keep a bounded raw snapshot/checksum and synchronization state.
  Hash event identity from instance/shipment plus raw event fields when upstream
  lacks IDs. Event text remains untrusted data and is safely rendered as text.
- Durable customer-update outbox: link/milestone identity, template/policy/consent
  checks, dedupe key, attempts and uncertain-send/reconciliation state. Enqueue
  in the same transaction as the accepted milestone. Never send from both engines.

Link creation is idempotent by tenant/order/command UUID and canonical request
hash, with replay returning the original link. A changed payload conflicts. Stable
remote shipment identity is authoritative after resolution; do not rematch solely
on AWB each poll. The present tracker forbids courier/AWB reuse even after revoke;
resolve rebooked/reused AWBs explicitly rather than deleting historical rows.

Poll only active links in the bound business connector, initially every five
minutes with jitter/backoff; this copies the engine's cache and does not force a
carrier lookup. Preserve successful history/check time through auth failures,
timeouts, empty snapshots and revocation. Record `last_sync_at` separately from
the upstream `checked_at`; a successful cache read is not a fresh courier check.

Current `retainHistory` (`worker/providers.js:26`) preserves previous events only
when the incoming list is empty. A nonempty partial response replaces tracker
history. Therefore merge newly observed events into Munimjee's immutable local
history and never clear it when a snapshot is empty or shorter. Upstream dates can
be raw `dd-mm-yy`/`dd/mm/yy` strings; preserve raw values, normalize only when
unambiguous and never use permissive JavaScript date parsing as event authority.

Current display statuses map as follows; store raw display text alongside normalized
tracking state. This mapping does not automatically change order fulfilment:

| Parcel Desk text | Proposed tracking state |
| --- | --- |
| `Awaiting update`, `Awaiting courier update` | `awaiting_update` |
| `In transit` | `in_transit` |
| `Out for delivery` | `out_for_delivery` |
| `Delivered` | `delivered` |
| `Delivery issue` | `delivery_issue` |
| `Returning` | `returning` |
| `Returned` | `returned` |
| Unknown/new string | `unknown`, retain raw text for review |

An empty courier result is `awaiting_update`, not invented shipment failure or
proof of invalid AWB. A fetch error is a separate synchronization/lookup condition,
not a replacement delivery state. Ignore duplicate/older snapshot versions;
contradictory terminal or unorderable evidence enters review rather than regressing
an order automatically. Until versioned machine snapshots exist, do not infer
ordering from HTTP arrival time or overwrite a confirmed milestone with a stale
cache read. Revocation stops sharing and alerts the seller, preserving history.

## Customer access and manual fallback

Render tracking on the existing protected order status page using its scoped order
capability; expose only that order's safe parcel timeline. Remote public tokens are
bearer capabilities: do not log/index them, include them in generic analytics or
return them in cross-order errors. A Parcel Desk deep link can remain an explicit
fallback for an authorized linked parcel. Revoking/unlinking locally stops its
exposure in Munimjee; it does not claim to revoke an already shared remote link.

Parcel Desk's WhatsApp control opens a `wa.me` compose URL; it is not an automated
delivery/outbox (`src/main.jsx:22,26`). Munimjee must own automated updates through
its durable messaging path, current opt-in/opt-out and approved utility-template
checks. Existing `queue_order_update` only supports placed/confirmed/shipped/
delivered and deduplicates by `order:{id}:{event}`. Additional parcel milestones
require explicit template and `link:{id}:milestone:{event_id}` dedupe contracts;
calling the existing shipped event on every poll is incorrect. Unknown send
outcomes require reconciliation rather than blind resend. Tracking enrolment alone
must not send a shipment-dispatched message.

When the connector is unavailable, allow manual courier/AWB entry and an approved
HTTPS tracking URL, clearly labelled **manual / not synchronized**. Preserve it
with actor/time and show the last successful automated update separately. Do not
fetch arbitrary user-supplied URLs from the backend; accept only approved public
carrier/tracker URL patterns. Unknown/unsupported couriers use this explicit path,
without pretending the existing engine supports them. Camera failure always has
manual entry. Seller corrections/replacements preserve old links/events.

## Failure and acceptance checks for the implementation lane

| Case | Required result |
| --- | --- |
| Cross-tenant order, connector, candidate or remote ID | Denied before remote lookup/write; no other customer's identity or token leaks. |
| Same digits on different couriers; multiple visible barcodes; unknown format | Explicit courier/candidate selection; no order assignment from barcode alone. |
| Expired candidate, changed order, revoked seller role | Conflict/denial before linking; require fresh review. |
| Duplicate scan/double-click/concurrent link commands | One active association; same-key replay returns it; changed-body replay conflicts. |
| Same parcel already linked to another order | Conflict and authorized resolution; no silent reassignment or foreign-tenant existence leak. |
| Existing/revoked tracker duplicate; old parcel outside newest 300 | Exact lookup/reconciliation; no list truncation fallback, duplicate enrollment or automatic undelete. |
| Remote enrollment succeeds but response/local commit fails | Durable uncertain command; reconcile/replay same identity; one remote enrollment and one local link. |
| Bad signature/replay/rotated key/disabled connector/foreign host | Fail closed, retain history, surface seller action; no staff-password or public-token workaround. |
| Empty/shorter events, duplicate events, out-of-order/invalid dates | Preserve merged history; no false delivery regression or duplicate milestone notification. |
| Refresh says ok but upstream error remains | Show last check/error accurately; do not claim fresh successful tracking. |
| Revoked/missing link, terminal contradiction, reused AWB | Seller review; preserve past events and stop new public sharing where appropriate. |
| Delivered/returned parcel, cron absent, quota limit/provider timeout | Accurate stale/health state; bounded refresh/backoff; no carrier-engine duplication. |
| Consent withdrawn, template unavailable, replayed poll, uncertain send | No unauthorized/duplicate message; existing durable-send policy applies. |
| Camera denied/hidden tab/cancel/manual correction | Camera stops; manual path works; selected order survives; no accidental link/send. |
| Manual tracking, replacement, cancelled/paid-order transition | Explicit labels/audit; preserve history; existing payment/stock rules remain authoritative. |

Release proof needs actual scoped machine-auth endpoints in an isolated tracker
branch, schema/tenant and retry tests, a migrated Munimjee link implementation,
physical camera acceptance and explicitly authorized test-recipient delivery.
Neither this design nor the source inspection completes those gates.

Source snapshot checksums (SHA256, read-only):

```text
worker/index.js         dc2440e18e07335658541e0b9752d1d706bc45fb6a1aac380483a339406ce3a7
worker/providers.js     dfe691bcf35d7d6c1f0f1ccb1dafddb142f590b985f69ff304ddeda7e5b52220
worker/refresh-queue.js c25baa3322a2b3b2607871b2c24d56c023f7e2bf7dedeb06adf229de15a43149
src/barcode-result.js   70437464d7bcaa6a2d2963753c9a817fb96cc916d58f91fb083fd500c2e29c4e
```
