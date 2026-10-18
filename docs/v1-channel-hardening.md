# Native channel session and privacy hardening

Repair base: `5141177` isolated reviewed Instagram composition. The independent
QA baseline is `cd636ca` on `codex/v1-onboarding-acceptance`: three actual-main
native-session race failures and actual-script VM privacy proof, preserved as
failures rather than green acceptance. This branch changes only channel API/service,
channel HTML/JS and new tests/docs. The integrator additionally authorized the narrow existing legacy WA account writers and ordered channel tenant locking required for cross-writer generation safety. Shared cleanup dependency161624b is local
`e0c7124`; its exact two shared files were retained when the older IG base lacked
the activity-policy prefix. No other shared-client edit is owned here.

## Authorization and transaction boundary

Versioned channel pages/APIs require a persistent native `v1_user` session, with
current business access. The legacy seller bridge cannot authorize this operating
workspace. Legacy routes retain flag-off compatibility, with the narrow shared-writer
safety boundary described below. Private responses and the
page explicitly use no-store/no-referrer/noindex headers.

Reads recheck the current native session and capability after awaited work. Role-
dependent overview/detail controls use a fresh final capability projection. All
mutation routes flush staged credential/check/operation/audit writes, then recheck
the native session and exact current capability before committing or returning to
the caller-owned commit. Flushing first prevents a later audit/FK wait from moving
the last authority check ahead of staged writes. Review dispatch still happens
only after a protected committed decision and uses the existing durable worker.

The Instagram callback keeps signed state, browser nonce, actor/browser binding,
one-use attempt and connection generation rules. A fresh authorization callback
runs after the consumed-at write is flushed and before its intentional pre-exchange
commit. A second final session/capability check protects staged credential writes
before the final commit. A denied final save does not undo durable attempt
consumption, permit code-exchange replay or claim that the provider exchange was
unattempted. Existing credential helper/generation guards are preserved.

## Conditional WhatsApp setup and exact receipts

The private connection projection adds `connection_version`. Native WA access/eligibility checks and sending-policy changes advance this generation when they supersede earlier conditional setup. Native WA setup
accepts an optional `X-Channel-Version` header; the new UI always supplies the
reviewed value. It is a canonical nonnegative decimal integer bounded at2billion.
The server includes it in the command hash when supplied; absent header preserves
the existing native command hash. Reusing the same key with a changed header is a
conflict. Legacy route payloads and flag-off authorization behavior remain compatible; credential/configuration writers now participate in the same connection generation.

Under existing authorization/tenant locks and a connection-state lock, exact
existing receipts are checked first. A new command compares the expected version
before provider lookup or credential mutation. Only that definite pre-mutation
mismatch emits typed409 `channel_generation_stale`. Accepted saves increment the
connection generation. A late old conditional request cannot overwrite a newer
replacement. Server/provider failures do not become definite pre-mutation errors.

Mutation ACKs carry safe business/key/action binding; accepted WA saves include
the accepted connection version. A valid-shaped ACK with the prior version cannot
confirm a secret-bearing save. A matching receipt proves that command's accepted
result, not that its credentials are still current: a separate fresh read reports
current local status. Account configuration/checks remain distinct from provider
approval or actual message delivery.

WhatsApp credentials/account eligibility and automatic replies are separate facts.
The projection reports automation enabled only when both `enabled` and
`automation_enabled` are true. Native enable/pause updates both flags; an account
with enabled access but automatic replies disabled remains paused and inbound
messages do not queue automated replies. A failed access check clears both flags.

## Legacy WA writers and canonical lock order

The existing PUT/PATCH/DELETE `/whatsapp/account` writers now take Business (only
if present) -> Seller -> channel control -> WA account locks, matching native
setup. No missing Business/User/Membership is created or resurrected by a legacy
request. A legacy-only seller without a Business retains its previous behavior;
there is no native conditional tenant in that case. Credential/phone replacement,
local disconnect and configuration/eligibility changes increment the control
version. PUT preserves encrypted-token reuse and sends stay paused.

When legacy enforcement is enabled, all staged writes are flushed and the actual
current dashboard owner/cutoff is checked again after provider/lock waits and
before commit. Admin impersonation remains denied under that flag. Flag-off
legacy authorization remains unchanged. The native tenant lock helper now takes
Business then Seller explicitly rather than relying on a join planner's lock
order. NO KEY UPDATE remains compatible with ordinary tenant FK checks.

## Browser privacy and uncertain actions

The page uses the shared native client/session/CSRF transport. Native user plus a
hash of the session CSRF binds the page and journal. Every session check participates
in a monotonic sequence so an older response cannot restore prior authority.
Reads/writes recheck identity before and after awaited requests, including an
immediate ended-state check before request dispatch. A synchronous preparation
reservation prevents two submits from passing the first identity/digest awaits
before either has persisted its intent. An ended latch
prevents stale response revival. Focus/visibility refreshes current authority;
role loss clears privileged dialogs/controls and entered credentials.

Ended/replaced access physically erases business/receipt/history/connection/recovery
facts, closes dialogs, resets inputs and removes action handlers. Confirmed401,
logout and identity replacement also clear the current journal. Failed reads scrub
cached private facts and leave an explicit refresh path. Secret fields are erased
on closing/hiding the form and after any save attempt; stored secrets are never
read back into an input.

Journal prefix: `munimjee.v1.channel-command:`. It is per native user/business/session and
contains the session hash, bounded24-hour time and checksum. Nonsecret operations
retain exact body/key/action for explicit same-command retry after reload. No
operation automatically POSTs on recovery. Malformed/expired/foreign or restricted
storage blocks new actions.

WA pending state retains only key, expected version and supplied WABA/phone IDs,
never a token, body containing a token, JWT or credential fingerprint. Unknown save
results erase the password and do not offer blind retry. A seller explicitly checks
current local status, acknowledges that GET cannot prove which secret was saved,
then re-enters credentials for a new conditional replacement using the latest
reviewed version. Typed stale-version rejection allows a fresh review; arbitrary
errors or malformed ACKs retain uncertainty. No token is logged or stored in
browser persistence by the page.

## Verification and bounded review

Final focused P01 run: **126 passed, 0 skipped**, 118.14 seconds. It includes actual
PostgreSQL/native HTTP checks and the existing pure channel contract tests. The
actual migrated chain ended at `0055_v1_comment_binding`: exact committed central
`0054_v1_activity.py` and `0055_v1_comment_binding.py` were local-only migration
dependencies on this isolated `5141177` source base, removed before the owned
commit. No fake migration chain or `create_all` was used. The exclusive lane was
the new disk-backed PG16 at numeric loopback port55443, `payment_w6`, through the
P01 guard/reset lease. No old OOM-affected database was queried.

The actual PostgreSQL tests cover the original three session races, revocation
after staged flush, final-read revocation, conditional receipt/header binding,
late/concurrent replacements, invalid headers, legacy-token rejection, legacy write/cutoff boundaries and both overlapping native/legacy lock orders. The
new flag-mismatch regression proves enabled account access with automation off
stays paused and queues no automated reply; native enable/pause changes both flags.

Final mounted runner: **25 Chromium checks passed**, port8169, actual registered
`app.main` channel router (asserted exactly once, no fixture router include), real
native signup/invitation/session/CSRF and actual head0055. It exercises committed
response loss/reload/exact nonsecret retry, secret uncertainty/manual replacement,
viewer denial, role loss, failed reads, held stale responses, same-user session
replacement and logout. Its only provider work is **4 synthetic account-read
calls**; explicit IG/WA send tripwires stayed0, external browser requests0 and
page errors0. This is browser emulation, not physical-device or real-provider proof.
All13 pre/post mounted application/harness/migration hashes match in the source
manifests. The lane was explicitly released after the run.

**17 actual-script VM checks** pass separately, including delayed-guard concurrent
submit and newer401 before dispatch; **6 shared-client checks** pass. VM checks use
minimal DOM/API doubles, not rendered/native HTTP evidence. Python/JS syntax and
diff checks pass. Raw logs/captures are in `artifacts/v1/channel-hardening/`.

Chronology is retained: `mounted-first.txt` failed because the test unregistered
its held Playwright response before fulfilment (`Route is already handled`). The
harness now awaits delivery/request completion before removing the route. Runtime
source did not change for that harness correction. A25-check run then passed;
the final25 run adds explicit provider-send tripwires and is recorded separately.
Earlier9/10/15 VM checkpoint logs remain historical, with final17 authoritative.

The single mechanical Impeccable pass reports one inherited `cramped-padding`
warning on the table wrapper. Existing commerce table-cell padding supplies the
content inset; no CSS changed in this repair. Independent integrator source/render
review accepted desktop ready, mobile uncertain-save, mobile viewer and mobile
session-ended captures with bounded SHIP verdict. This scan is not provider proof.

Separate acceptance scopes remain explicit: native profile/invite final guards,
native shell privacy and derived checklist completion are integrator-owned, not
completed or re-certified by this packet. Official WhatsApp consent/account
discovery and a safe native authorized-message test path remain separate code/product
work. Current provider access/grants, authorized recipients
and real inbound/outbound delivery remain external gates. This safety repair does
not clear V01/V07 or the disabled Instagram owned-media capability gates.
