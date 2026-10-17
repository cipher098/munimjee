# Durable Instagram ingress: bounded C10 slice

New actionable customer DMs commit a minimal normalized receipt before HTTP/SQS
acknowledgment. Provider account ID is resolved through the active Seller mapping;
event-supplied seller IDs have no authority. Processing rechecks and locks that
mapping. `account_id + event_key` uniquely identifies a receipt; the provider mid
is authoritative when present, independent of rotating media URLs. Without a mid,
normalized content, participants and provider timestamp form a fallback hash.
Identical messages without both mid and timestamp cannot be distinguished.

Redis/Celery wakes are optional hints for DB-native traffic. Register the worker
module and periodic `recover_instagram_ingress` task as described below. Pending
and explicitly reviewed retry receipts survive broker outages and worker restarts.

## Completion and uncertain effects

Receipt payloads remain immutable. `processed_indices` records exactly which
normalized components the existing conversation processor handled or withheld by
policy. A payment screenshot can return before later text/media; only handled
components advance. Unhandled components stay pending for the next recovery pass.
A receipt becomes completed only when all its components are consumed.

The existing bot can send externally before committing its database transaction.
A failure or interrupted processing therefore becomes a retained unknown-effect
error rather than an automatic replay. Processing receipts and unresolved
unknown-effect errors quarantine the seller/customer thread. The shared writer,
new receipt claims, takeover-resume and nudge paths check this gate; the owning
receipt worker excludes only its own processing IDs. This also fences the gap
between a failed transaction and its separately committed error update.

Internal seller-scoped service seams require the caller to authorize access:

- `replay_receipt(..., side_effects_reviewed=True)` queues a reviewed retry and
  rechecks the active provider-account binding.
- `resolve_receipt_without_replay(..., side_effects_reviewed=True)` marks an error
  resolved without sending again. Original payload/progress remain available.

These are service seams, not a shipped operator UI or a public authorization API.
All blocking receipts must be reviewed before the thread can resume. These guards
do not turn legacy external sends into an exactly-once provider transaction.

## Legacy Redis cutover

The legacy `process_message_batch` task is now a transfer adapter. It never calls
the sending phase. It persists buffered events into the same receipt ledger and
commits before trimming the exact Redis prefix. Comparing the prefix prevents a
stale task from trimming newly arrived work. Transfer failures retain keys without
expiry and retry; the periodic recovery task also scans a bounded set of legacy
buffer keys. Redis failure during this optional scan does not discard DB receipts.

Legacy buffered events are held with `legacy_cutover_review_required`; missing
provider IDs use `legacy_identity_unverifiable`. Legacy buffers lack a reliable
record of whether an older worker already sent before losing its commit. A
collision with a pending durable receipt is therefore held for review as well.
Completed/resolved ledger entries are not replayed by subsequent legacy transfers.
Reviewed replay sends through the same durable worker once; reviewed resolution
can release the hold without repeating an already handled operation.

Before any deployment, stop older worker binaries that still contain the direct
Redis sending implementation and reconcile their outstanding work. New code
cannot prevent an older binary from executing its old policy. Work whose old
120-second Redis TTL has already expired cannot be reconstructed by this slice.
No production cutover or backlog reconciliation was performed during development.

## Registration and migration

The integrator owns these shared registrations:

- Import/export `InstagramIngress` in `app.models`.
- Include `app.workers.instagram_ingress` in Celery startup.
- Run `app.workers.instagram_ingress.recover_instagram_ingress` every 30–60 seconds.

Unreleased migration `0042_instagram_ingress` follows `0041_v1_catalogue` and
includes `processed_indices`. Rebuild disposable schemas created from an earlier
version of this unreleased migration before validating the updated source. The
coordinator verifies the complete migration chain; worker-owned tests apply the
actual 0042 migration over an isolated baseline schema.

## Verification boundaries

Synthetic PostgreSQL tests cover duplicate and concurrent delivery, failed broker
wakes, recovery, interrupted work, reviewed replay/resolution, provider account
reassignment, exact payment-tail/multi-attachment consumption, cross-source media
deduplication, and quarantine across new ingress/resume/nudge/legacy paths. Signed
HTTP tests reject malformed nested shapes before acknowledgment. A disposable
Redis check covers stale-prefix trimming. Provider/media/LLM/send boundaries are
stubbed; no customer messages or live sends are used. Comments, connection UX,
operator review UI and a durable outbound outbox remain outside this slice.
