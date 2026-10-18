# Channel activity installation proposal

Status: isolated implementation draft, not yet actual-PG or mounted accepted.
Central frozen0056 remains unchanged while its complete gate runs.
No sender, consent, claim, retry, customer identity or financial behavior changes.

## Trusted new-row hooks

- Instagram: only a newly inserted signed non-echo durable ingress receipt with
  a nonempty provider MID, before its existing acknowledgement commit. Exact
  duplicate/replay/legacy transfer never backfills. Preserve raw-secret command
  suppression before persistence; suppressed linking/test commands are not
  ordinary enquiries and have no transcript source to classify.
- WhatsApp: only a newly persisted ordinary inbound with a nonempty provider MID
  in the same ingestion transaction. Preserve source/account/window/opt-out
  behavior. Test challenges are redacted and explicitly classified as test by
  their server-owned test association, never a browser flag.
- WhatsApp automated outbound: mark only the actual new queue row from explicitly
  enumerated trusted automation/notification producers. Manual API paths remain
  operator/unknown. Never infer origin from text, payload, idempotency-key prefix
  or an arbitrary caller's supplied boolean. An existing exact row is not a new
  measurement fact.
- Comment automated outbound: mark only each new accepted action row in the
  existing signed producer transaction. Preserve its immutable account/source/
  config claim and the same dispatcher. No ingress-processed-to-send inference.

All hooks use the existing server-only record_source helper and immutable
classification; current policy/retention gates remain required. New source facts
must predate neither the effective owner measurement policy nor the source's
actual creation. Known test environment or an exact server-owned test association
always demotes; historical/unknown/manual sources never become production.

## Reporting proposal requiring bounded review

One scalar statement must combine minimal source ledger rows with exact
tenant-bound canonical source rows. No bodies, customer/provider identifiers,
credentials or arbitrary metadata are projected into analytics. 0054's immutable database guard binds ledger created_at exactly to canonical
source created_at. The draft preserves that authority and names each source-time
cohort explicitly: Instagram durable ingress receipt time, WhatsApp signed inbound
provider timestamp, and local outbound queue/action creation time. These are not
a uniform receipt-time cohort or settlement time. A separate immutable receipt
clock would need a reviewed additive migration after reserved0057; it remains
queued, with no guard weakening or historical timestamp rewrite.

Enquiries mean tagged accepted ordinary inbound messages, not people, buying
intent or cross-channel identities. Automation outcomes mean current local
queued/sending/failed/unknown state plus provider acceptance evidenced by a
nonempty canonical provider association. Provider receipt wins the acceptance
observation; it never means delivery. Unknown without a receipt stays unknown,
and unrecognized states stay unknown. IG sends and resolved-enquiry outcomes
remain null until their own authoritative producers exist.

Initially report tagged observed counts as partial coverage, with explicit
included source kinds and excluded test/unclassified counts. Do not infer full
historical producer coverage from helper existence, first event, an enabled flag
or an empty result. With no proven observed source coverage, counts remain null,
not zero. Test-only data must not become a production zero or positive count.
Production purchase figures and context conversion keep their existing separate
semantics. No channel attribution or joined customer history is introduced.

## Ownership and gates

Integrator owns shared ingress/queue/comment hooks and report/UI wiring after
0056 is frozen. Catalogue's0057 self-service/test code does not install another
producer. Its exact test-message association will be a separately reviewed test
classification input. No migration is reserved by this proposal; any durable
coverage extension requires a separate exact schema review.

Before acceptance: reviewed hook inventory; real migrated new-row/duplicate/
foreign/test/manual/policy/retention cases; current single-writer regression;
source-time/receipt-time boundary; coherent report totals; mounted truthful
empty/partial/test-excluded UI; and a fresh composed gate. Actual provider proof
and deployed measurement/retention readiness remain separate and default-off.

## Draft failure isolation and limits

Each caller flushes domain facts before the observation seam. The seam uses a
nested savepoint, bounded100ms lock/250ms statement timeouts, and restores prior
transaction settings on success. Ledger exceptions roll back only the savepoint
and emit one fixed redacted warning. Actual task cancellation still propagates.
Healthy facts and ledger commit together; measurement failure may leave a valid
unmeasured receipt, and exact replay never backfills it. This makes missing
measurement explicit rather than dropping/retrying a valid ingress or send.

The source report uses the same single-statement snapshot as the activity report.
It joins exact tenant-bound source rows, lists observed production source kinds
and test/unclassified exclusions, and always labels these channel observations
partial. An inbound/outbound family with no production observations remains null,
even when the other family has observations. Unknown, review-required, withheld
or unrecognized no-receipt outcomes remain unknown; a nonempty canonical provider
receipt is acceptance evidence only. Test commands intercepted before ordinary
ingestion have no ordinary source fact.0057 test outbound uses no automation
producer marker and cannot enter production automation totals; exact test-FK
classification is a separately reviewed followup.

Prepared actual SQL-failure/receipt/outbox/dedup/report tests are NOT execution
evidence. Pure boundary checks alone do not prove PostgreSQL savepoint recovery.
