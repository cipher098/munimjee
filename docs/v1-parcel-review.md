# Native parcel review and replacement

This extends the existing order-first parcel page. It requires the current native
session, active business membership and `orders.write` for every action;
`orders.read` permits the scoped tracking and review history. Cookie mutations
use the shared Origin/CSRF dependency. The existing parcel feature flag and
trusted business/instance connector configuration remain authoritative.

## Explicit actions

- **Review and resume tracking:** read the saved remote parcel, or resolve the
  exact saved courier/AWB if an earlier enrollment remains unknown. Only one
  confirmed owned record with the exact tenant, instance, courier, AWB and known
  remote identity can resume. Unknown, unowned, multiple, missing, revoked,
  errored, older or unrecognized-status records remain manual review. Resume
  performs no ensure/enrollment request. A seller can explicitly accept a newer
  contradictory carrier status; all previous observations remain append-only.
- **Close this association:** close the local row, invalidate its lease and retain
  history. This does not revoke remote tracking or cancel a booking or order.
  Closing remains available when connector configuration is unavailable.
- **Replace with another parcel:** start from the same authorized order and an
  existing link, scan or manually enter a different label, preview its exact
  courier/AWB, choose a reason and confirm both acknowledgements. One transaction
  retires the old local row and commits its successor plus review audit. The
  existing `process_link` remains the sole enrollment writer. The same parcel
  must be resumed, not replaced. An earlier parcel from another association is
  never silently transferred, even when that association is closed.

A request or customer message already beyond the local fence may have reached its
provider. No local action can recall it. The page states this and requires an
explicit acknowledgement. Tracking review changes no fulfillment, payment,
reservation, stock or courier-booking state.

## HTTP contract

All routes start at
`/api/v1/businesses/{business_id}/orders/{order_id}/parcels/{link_id}`:

| Method/path | Purpose |
| --- | --- |
| POST `/review-preview` | Read-only exact saved-parcel review |
| POST `/replacement-preview` | Read-only preview of a different explicit label |
| POST `/review` | `resume_tracking` or `close_link` |
| POST `/replace` | Commit explicit replacement and wake the existing worker |
| GET `/reviews?page=1&page_size=25` | Tenant/order/link-scoped immutable audit projection |

Preview requires the expected order and full link fingerprints plus a scan ID.
Replacement preview additionally requires a supported courier and label AWB.
A short-lived signed candidate binds actor, business, order, source link, complete
link snapshot (including lease token/deadline), connector configuration, normalized
label and the exact read snapshot. Preview and command both recheck the current
native session and capability after remote reads; commands recheck after order
and link row waits. No remote I/O occurs while holding those rows.

Commands require a UUID idempotency key, exact expected fingerprints, documented
reason, `confirmed: true`, and `remote_effects_acknowledged: true`. Resume and
replacement require their signed preview. A successful response identifies
`command_id`, `action`, `source_link_id`, the resulting `link`, and `replayed`.
Business-scoped immutable audit receipts check the original actor, exact body,
source and order before candidate expiry. Replaying an accepted command returns
its current result; it cannot create another review or enrollment command.
Concurrent replacements serialize on the order/source link; only one succeeds.

Only `parcel_review_preview_expired_or_invalid` and
`parcel_review_context_changed` are definitive pre-acceptance typed conflicts.
The native client saves the exact path/body/key in session storage before POST,
checks persistence, validates response correlation and retains that intent after
unknown HTTP/transport/malformed-response results. Reload offers explicit retry
of that same action. It never silently creates a new command. Storage is under
`munimjee.v1.parcel-link:` and bound to native user, business, order and session
CSRF fingerprint; the shared identity cleanup already covers this prefix.

Native identity replacement/expiry clears private order, label, candidate,
review/history DOM, camera and saved intent. A held successful old session read
cannot restore the page or dispatch a later private request. Capability loss
withholds writes. Restoring access requires reviewing current facts.

## Worker and notification fences

Close/replacement clear the old lease token. An in-flight worker response must
match its original token, so it cannot revive a retired association after HTTP.
The old enrollment may nevertheless exist remotely; that is disclosed rather
than represented as cancelled.

Resume reconciles its reviewed snapshot without notification decisions. The first
confirmed replacement snapshot establishes a skipped baseline, including after
unknown enrollment recovery. Old queued updates do not become eligible merely
because a link is resumed. Review audit records the pre-existing outbox IDs and
wall-clock acceptance time; the existing sender's final scalar revalidation
rejects earlier messages without acquiring new order/link locks. Outbox unknown
results are not retried. Later newly observed milestones still require the
existing consent, approved UTILITY template, live connector/business and matching
current order/contact checks, and remain deduplicated per link/milestone.

No DDL, new background sender, main registration or package asset change is
introduced. Immutable audit/observation triggers and existing tenant membership
foreign keys remain the actual migrated schema. Overview retains its incumbent
50-link bound; carrier and review APIs are paginated, while the page shows the
latest 25 observations/reviews per displayed association.

## Local verification boundary

See `artifacts/v1/parcel-review/verification.md` for the exact tested source,
commands, raw reports and independent review disposition. The test-only Node
loopback transport targets exactly `127.0.0.1:8155/integration/v1`; it exercises
real Worker.fetch/HMAC/SQLite and actual app.main on the exclusive P01 parcel_w3
PostgreSQL 16 lane. Production HTTP transport is blocked by the safety harness.
This proves local two-service composition, not a cross-host deployment.

Private connector deployment/provisioning, D1 migration, TLS, physical phone
camera behavior, actual carrier lookup, provider template acceptance and live
customer messaging remain unverified external gates. No original Parcel Desk
files, production services or real sends are changed or exercised.
