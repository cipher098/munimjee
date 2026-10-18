# Channel activity installation proposal

Status: next integrator-owned source work; not installed or accepted by this file.
The existing seller-activity.v1 channel fields remain null/producer_not_installed.
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
credentials or arbitrary metadata are projected into analytics. The report's
cohort time must be stated consistently: proposed source-ledger receipt time,
while verified source time remains only a conservative eligibility check. This
requires an explicit helper/fixture update; do not silently mix IG receipt time
with WhatsApp provider timestamps.

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
