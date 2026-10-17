# V1 existing-parcel tracking: local implementation

This implements an existing order → scan/manual tracking number → explicit
courier/recipient confirmation → durable association → cached tracking journey.
It does not book a courier, purchase a label, prove carrier handover, or change
payment, dispatch, order status or stock. The original Parcel Desk and running
services remain unchanged. No deployment or real carrier/customer request was
performed.

## Runtime boundaries

`V1_PARCEL_ENABLED` defaults false. One explicitly provisioned `ParcelConnector`
binds a Business to one trusted tracker instance, an exact origin and a private
credential reference. `V1_PARCEL_CONNECTORS_JSON` resolves that reference to
business_id, instance_id, origin, key_id, secret and enabled. The business/instance
must match the database record; origin must be in `V1_PARCEL_ALLOWED_ORIGINS`.
Production permits HTTPS with no credentials, path, query, fragment or arbitrary
port. Only APP_ENV=test permits the reserved loopback fixture on 8155. Browser
input cannot supply an origin, credential or business claim. Keys never appear in
native responses or browser storage.

The independently committed source-only tracker copy is
`work/parcel-desk-v1-connector`, branch `codex/v1-machine-connector`, commit
`2f85e53a74aa4737e9f86b5fa0c41211f87ef32c`; its CONNECTOR.md defines the exact
HMAC API and required isolated D1 migration. Its baseline has 32 source/package
files matching the read-only original (plus a newly authored .gitignore); no env,
Wrangler state/config, dependencies, customer fixtures or private keys were copied.
No legacy shipment is adopted: an unowned duplicate courier/AWB requires manual
review. No public tracking capability is disclosed or used as ownership proof.

## Native API and UI

The page is `/v1/businesses/{business_id}/orders/{order_id}/parcel`, reached from
native catalogue View order → Link or view parcel. Read access needs current
`orders.read`; preview/link/refresh needs current `orders.write`. All mutations
use persistent native sessions, Origin/CSRF checks and fresh authority after lock
waits or remote reads. Current tenant membership and active Business/Seller are
required; there is no support impersonation or seller-token fallback.

Base API: `/api/v1/businesses/{business_id}/orders/{order_id}/parcels`.

| Method/path | Meaning |
| --- | --- |
| GET base | Selected order context/fingerprint, capabilities, configured boolean, couriers and bounded saved links/notification decisions. No connector URL/key. |
| POST base/preview | Exact scan_id/courier_id/awb; normalize and scoped-resolve only. Returns a five-minute signed actor/order/connector/label/fingerprint candidate; no enrollment. |
| POST base | Exact idempotency_key/candidate_token/expected_order_fingerprint/confirmed:true. Commit link intent and audit before remote work. Same key/body returns the receipt before checking candidate expiry. |
| GET base/{link}/history | Tenant/order-scoped page/page_size; append-only observations and total. Raw ambiguous dates stay raw. |
| POST base/{link}/refresh | Exact idempotency_key; audited cache synchronization or same-command enrollment recovery. Does not force a carrier lookup. |

Link responses include id, business_id, order_id, idempotency_key, courier_id, awb,
state, revision, tracking_state, raw_status, check/attempt/sync timestamps and a
bounded error code. The native client validates selected order and command identity
before clearing its saved intent. Session storage uses prefix
`munimjee.v1.parcel-link:` scoped to user/business/order/native-session fingerprint;
only the exact confirmed command is persisted before POST. Reload and uncertain
responses offer explicit same-command recovery. Shared identity-transition/401
cleanup removes private intents. The page rechecks native identity/session and
current capabilities around requests and on focus/visible/pageshow. A401, changed
sign-in or lost business read access stops the camera and clears private DOM and
in-memory label/intent/history. Role changes withhold mutation controls.

Only typed HTTP409 `parcel_preview_expired_or_invalid` proves rejection before
any receipt/mutation and permits a fresh scan. Any other conflict, transport loss
or malformed/wrong-command acknowledgement retains the original command. Camera
starts on eligible intake, requires two consistent local ZXing detections and
stops tracks on completion/cancel/hidden/page exit. Ambiguous numeric barcodes do
not choose a courier. Denied/unavailable camera has the same manual confirmation
path. Scanner JS/WASM is served locally, with retained license attribution.

## Durable processing and status truth

Actual migration0048 follows0047. Tenant composite FKs bind orders, connectors and
actor memberships. Partial unique indexes permit one active link per order and
per connector parcel identity. Database triggers make observations/audits
append-only. There is no backfill or silent legacy ownership transfer.

A committed pending_enrollment command is claimed with a 60-second lease before
HTTP; the database lock is released during transport. Unknown enrollment keeps the
same remote command UUID. `poll_due` recovers expired claims and due
pending_enrollment/enrollment_unknown/linked rows (20 per pass, maximum100).
The central default-off Celery task scans every30 seconds; cache polls are due
five minutes apart. The existing Parcel Desk queue remains the carrier writer.
The local UI's refresh reads that cache, so last tracking sync is distinct from
last successful courier check. There is no new webhook in this slice.

Reconciliation deduplicates independent observed events without deleting shorter
or older history. Older snapshots/check times and status regressions cannot
regress current status. Remote revocation, changed authorization/order context or
contradictory terminal status requires review. A successful enrollment is only a
tracking association, including when courier status is Awaiting update. It is
never proof of shipment or delivery.

## Notifications

Tracking does not depend on consent. Each new eligible milestone gets a unique
local decision and new WhatsApp outbox key `parcel:<link_uuid>:<milestone>`;
it does not reuse shipped-order keys. Missing consent/account/approved utility
template records a skipped decision rather than blocking history. A previously
skipped milestone is not automatically sent later when consent is added.

The sole existing outbox sender refreshes approval, requires UTILITY, then checks
current connector/configuration/Business, current linked milestone, order opt-in
and contact consent immediately before sending. This helper uses fresh scalar
reads without new Order/Link/Business locks to preserve sender lock order.
Templates can be eligible outside the24-hour free-text window; that does not
permit unconsented messages. Queued/accepted is not delivered. An uncertain
provider submit becomes unknown and is never automatically retried.

## Remaining release gates

Explicit private provisioning/key rotation and isolated D1 migration are required.
Cross-host TLS/provider transport, Cloudflare deployment, real scheduler/carrier
behavior, approved-template delivery and a physical phone camera/printed label
have not been exercised. Manual resolution/replacement of review_required links
is not implemented in this bounded slice; preserve the record and use an operator
review process rather than fabricating completion or retrying enrollment with a
new identity. Current pages expose only the latest25 observations, with total;
API pagination supports older history. No production customer data was used.
