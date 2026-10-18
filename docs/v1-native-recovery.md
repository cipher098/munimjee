# Native import and design recovery hardening

The importer checks its captured fence generation immediately after the native
session wait and before JSON or raw-upload dispatch. A concurrent terminal
identity fence cannot be revived by an earlier successful guard. Upload success
and JSON success also check that generation after their final session wait.

Unclassified 403/404/409/413/415/422, malformed success, transport loss and 5xx
retain the exact saved command. Native 401 identity cleanup remains the shared
privacy policy. Only these typed, receipt-first pre-mutation rejections allow a
new reviewed decision: `theme_version_stale`, `import_revision_stale`, and the
existing `candidate_already_created` for a catalogue-draft request. Their HTTP
status stays 409; structured detail carries `code` and plain `message`. The shared
V1 client already supports that shape. Idempotency collisions and other conflicts
keep their previous string shape and never receive a definitive rejection code.

Theme success must confirm expected version + 1, the exact saved draft, and the
publication revision/configuration. A save also preserves its expected published
snapshot. A following GET must be the same confirmed record or a valid newer
version; an older or contradictory 200 cannot clear recovery. When a later
version exists, the page says so rather than claiming current public design was
unchanged.

New session-storage envelopes use format 2 and hash the exact body plus expected
private/public configuration snapshots. Existing format-1 draft saves still use
their saved config and key. A format-1 publication has no original draft snapshot;
it remains preserved for explicit owner reconciliation rather than inferring
intent from today's design. No migration or shared client/router/package/payment
changes are introduced.

Actual 0049-chain and mounted app.main proof, controlled intermediary/response
loss cases, baseline reproduction scope and remaining limits are recorded under
`artifacts/v1/native-recovery/verification.md`. Tests use only the exclusive P01
parcel_w3 disposable DB and an owned loopback server, with workers and all provider
networking disabled. No production change or live provider operation is claimed.
