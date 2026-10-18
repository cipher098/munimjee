# V07 WhatsApp self-service proposal

Status: core policy accepted in principle; exact schema/shared hooks pending
integrator approval. Reserved migration `0057_v1_whatsapp_self_service` follows real
`0056` (exact revision dependency still to consume). **No runtime,
schema, provider request or recipient message is implemented/executed by this
packet**. Source inventory is composed `dddd81d`; independent onboarding follow-up
review covered frozen `52fdda8` (now composed separately as `bb261b8`). Existing
manual token configuration is not Embedded Signup or V07 self-onboarding proof.

## Current facts and missing paths

| Existing source | Reusable behavior | Remaining work |
| --- | --- | --- |
| `app/api/v1/channel_operator.py`, `services/channel_connections.py` | Native owner/current-session/CSRF lifecycle, encrypted manual WA setup, exact command receipts, conditional generation and paused activation | Official consent/SDK code exchange and authorized asset selection |
| `models/whatsapp.py` | One WA phone per seller/business; phone unique across tenants; encrypted credential; separate account/automation flags | Short-lived signup attempt, selected-asset grant provenance/expiry and recipient-test authorization |
| `services/whatsapp_provider.py` | Fixed Meta Graph origin, phone-to-account lookup, no automatic POST retry | Strict bounded v4 exchange/discovery/register/subscribe transport and safe step reconciliation |
| `services/whatsapp.py`, `workers/whatsapp.py` | Signed inbound association, contact/window/opt-out, durable exact-key outbox, pre-send policy rechecks, unknown-send hold, monotonic bound status updates | Native test-intent/result projection and one explicitly authorized test while automation remains paused |
| `services/onboarding.py` in `52fdda8` | Current local readiness; authorized message-test unavailable; provider approval never inferred | Derive test evidence only after actual bound signed inbound/outbound status facts exist |

Manual legacy inbox/reply/template routes use legacy dashboard authority; a new
native test flow must not borrow seller tokens or expose those routes as native.
No new broadcast, promotional template, arbitrary recipient/composer or account
transfer is included. A changed phone with an existing inbox remains a separate
account migration; reconnect may only retain the existing phone binding.

## Primary documentation checked on 2026-10-18

The public pages below were read in guest Chrome through Meta's own documentation
search. Direct web fetches returned429/unavailable; Postman results supplied
additional official references. This is documentary evidence, not observed wire
behavior or evidence of this app's permissions, partner status or grants.

| Primary source | Supported fact and compatibility limit |
| --- | --- |
| [Overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/) (updated Jul24,2026) | Facebook Login for Business/JS SDK supplies asset IDs and a code. Cloud API uses `whatsapp_business_management` and `whatsapp_business_messaging`; live advanced access is required. Customers own assets. Existing `waba_id` now names a Messaging account as WAAC/Messaging account responsibilities evolve; IDs remain compatible. Tech Provider billing is customer-owned. Signup sandbox phone numbers cannot send/receive. |
| [Implementation](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/) (Jul24,2026) | HTTPS/allowed domains/strict redirect setup and a Login configuration are required. SDK source is `https://connect.facebook.net/en_US/sdk.js`; `FB.login` requests `response_type=code`, `override_default_response_type=true`, `config_id`, `extras.setup`. `authResponse.code` has30-second TTL. Session messages carry `WA_EMBEDDED_SIGNUP` plus finish/cancel information and asset IDs. Browser data is a hint, not tenant authority. |
| [Version4](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4/) (Sep3,2026) | v2/v3 deprecated Oct15,2026. A new product-configured Facebook Login for Business configuration selects v4; do not invent `extras.version` or reuse deprecated samples. Cloud API products require WAAC/Messaging assets and the two WA permissions. Selecting ads/conversions products would expand scope and is excluded. |
| [Tech Provider onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/) (Aug5,2026) | Server `GET /oauth/access_token` exchanges code using app ID/secret. Server subscribes `/{waba_id}/subscribed_apps` and registers `/{phone_number_id}/register` with a6-digit PIN for standard Cloud API. Its optional test starts with a user's inbound message, then a text reply and status webhooks. The prose exchange response is a token placeholder, not a complete JSON wire schema; parser compatibility still needs canary evidence. |
| [Official Meta Postman phone/account examples](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-950a75b1-6ad7-4950-8b00-c64153c6176f) | Account phone-number collection and app subscription are distinct operations. Collection examples are not proof of our account's authorization or current complete response schemas. |
| [Official Meta Postman statuses](https://www.postman.com/meta/whatsapp-business-platform/folder/fuaee8l/statuses-object) | Statuses identify a message/recipient; the rolling customer-support window differs from older conversation/pricing concepts. We use signed statuses and existing window checks, not price assumptions. |

All required current operator configuration/permission facts remain **unknown**:
business/Tech Provider eligibility, v4 Login configuration/products, app ID/secret,
advanced access, domains, HTTPS, account-update/messages subscription, billing,
number eligibility/registration/PIN, actual token response/grants/expiry and real
recipient delivery. This proposal neither requests nor discovers real credentials.

## Proposed bounded product policy

1. Only the current native business **owner** (`channels.connect`, exact owner
   role) can start consent, attach an account, create a test challenge or request
   the one test reply. Managers/staff/viewers/support operators cannot authorize
   provider access or recipients. A read-only coarse result may follow inbox.read;
   recipient details and choices stay owner-only. This owner-only test policy needs
   integrator approval; no new permission is silently added.
2. Default off independently: `V1_WHATSAPP_ONBOARDING_ENABLED` and
   `V1_CHANNEL_TESTS_ENABLED`. Actual operator-ready configuration/grants must also
   be asserted before a real SDK/transport path is offered. No SDK is loaded merely
   by visiting the native page. Shared config/CSP/package/main/checklist stay
   integrator-owned. Cloud API only; coexistence/migration/multi-WABA/grant-only
   flow variants are rejected with actionable unsupported-flow guidance initially.
3. Start is an explicit reviewed owner action. Explain Meta-hosted identity/terms,
   what account is shared and local disconnect versus Meta revocation. No legal
   consent, OTP, number PIN or payment setup is automated by this task.
4. Selection/credential save stays paused. No automation is enabled implicitly.
   No missing Meta configuration becomes synthetic success. No developer-created
   or signup sandbox account is presented as messaging-capable from local evidence.

Proposed local bounds:5 signup starts/hour per business+actor, one active signup
per native sid/business,3 test challenges/day per business, one active challenge
per generation, one fixed reply per test and60-second test-send cooldown. These
are local safeguards, not claims about Meta quotas. Keys are UUIDs, IDs1–40 decimal
digits, proof/body limits16KiB, provider JSON64KiB, each network wait20seconds.

Distinct operator inputs: blank `WHATSAPP_EMBEDDED_APP_ID`,
`WHATSAPP_EMBEDDED_APP_SECRET`, `WHATSAPP_EMBEDDED_CONFIG_ID` and explicit
`WHATSAPP_EMBEDDED_GRAPH_VERSION=v26.0`. Do not borrow Instagram credentials or
change the legacy WA provider version. Existing signed ingress has a single
`WHATSAPP_APP_SECRET`: the embedded secret must match it, otherwise deny SDK launch
and attachment with `configuration_mismatch`. No multi-app signature expansion.
No new provider-ready boolean or readiness claim follows from config presence.

## Signup attempt, exchange and asset selection

Proposed namespace: `/api/v1/businesses/{business_id}/channels/whatsapp/signup`.
Existing manual `/whatsapp/connect` remains explicitly a manual fallback.

| Operation | Exact local contract |
| --- | --- |
| `POST /signup` | Strict UUID key, reviewed notice boolean (literal true), expected current connection version. Server binds business, native user **and exact sid**, operation hash, generation,10-minute expiry, signed local state and a server-HMAC HttpOnly nonce digest. Response: safe attempt ID/state/config IDs/expiry. No token/secret. |
| `POST /signup/{attempt_id}/exchange` | Current same native sid+CSRF, signed local state+HttpOnly nonce and bounded SDK code. Callback closure binds its original attempt; no code/state in URL, logs or browser storage. Persist consumed/`exchanging` before provider request; then exchange promptly (documented code TTL30s). Identical retry reads existing state and never re-exchanges. Ambiguous exchange stays `exchange_unknown`; restarting requires explicit new consent. |
| `POST /signup/{attempt_id}/assets` | Bounded strict FINISH asset hints, only the active original attempt. Server verifies current app/grants and selected WABA access with the exchanged customer token, enumerates phone membership from fixed Graph routes. Exact-origin SDK session data is untrusted input; it cannot grant account authority. Return at most100 safe phone choices, complete bounded pagination or an error (no truncated auto-selection). |
| `GET /signup/{attempt_id}` | Safe current state/choices/typed blockers; never code, provider token, secret, PIN or raw provider response. No-store/no-referrer/noindex. |
| `POST /signup/{attempt_id}/select` | Explicit choice+strict confirmation+exact key+expected connection version. Selected WABA/phone must be from the server-verified attempt; revalidate membership/current native owner/generation under canonical locks. Never choose first account. Reject a phone owned by another tenant or a phone change retaining an old inbox. |

Local signed state/nonce authenticates our own browser/attempt exchange request;
**do not claim Meta echoes that state**: the documented FB.login callback does not
show an app-supplied round-tripped state field. Exact current native sid/CSRF,
single active callback closure, one-use consumption, backend token/app/asset checks
and final explicit account review are mandatory. SDK source-window validation must
be supported by the actual SDK API; never invent a popup handle returned by
FB.login. Use exact configured Meta HTTPS origins, not suffix matching.

Transport is fixed `graph.facebook.com`, operator-pinned supported Graph version,
strict JSON/field/ID/size/time limits, no redirects, no automatic token exchange or
POST retries. Provider code/secret query strings and exception bodies are redacted
from HTTP logs. A strict `{access_token: string}` response parser is a documented
**unobserved compatibility assumption**, fails closed for other shapes and remains
gated pending real wire proof. Customer token is server-only Fernet ciphertext.
Only allowed grant/expiry/app/asset facts may survive to safe provenance metadata.
Native secret-bearing input uses bounded manual body parsing and a generic422
without raw Pydantic `input`, provider/code/PIN values or exception chaining.
Unknown DTO fields are rejected; `repr=False` alone is not error redaction.

Subscription and standard registration are separately tracked provider effects.
The owner reviews the explicit setup steps before dispatch; PIN is memory-only
until its one provider request and never echoed/stored. Each step has a durable
claim and unknown state before provider work. Reconcile through a documented
read-only provider query only when its semantics are verified; otherwise offer
Meta Manager/support guidance and no blind repeated register/subscribe POST.
Billing and unsupported coexistence remain external blockers, not guessed ready.
Final credential association flushes audit/credential/control rows, then rechecks
same native sid/current owner and generation before commit. Revoke during an
exchange does not undo Meta's token issuance but must save no application access.

Browser recovery stores only user/business/session-bound nonsecret command keys,
attempt IDs/generation/step names and reviewed nonsecret fields. It never stores
an SDK code, signed local state, provider token or PIN; reload cannot silently
restart consent/exchange/setup. Exact-key start replay may restore the same
unconsumed local browser proof using a server-reproducible pseudorandom nonce:
HMAC with a separate purpose over attempt UUID, business, user and native sid.
Only its digest is stored; the raw sid is never returned. Local state has fixed
original creation/expiry claims on replay. A consumed attempt never gets a new exchange. Unknown PIN/setup
outcomes require safe status/reconciliation/manual owner review, not re-entry
followed by an implicit second provider POST. Provider-effect claims/evidence stay
durable even when a final native revoke prevents local account attachment.

## Intended recipient and one explicit connection-test reply

Do not reuse a phone typed into a browser as verified recipient identity. Proposed
flow: owner creates a10-minute, one-use128-bit challenge for the current account
generation, shares its displayed instructions with a specifically authorized
recipient, and that recipient sends the challenge to the business number in
WhatsApp. No application send occurs at this stage. A signed, tenant/account-bound
inbound message records the actual contact/message/time and consumes the challenge
once. The native owner reviews that specific recipient and explicitly confirms
authorization before queueing the fixed, non-promotional test reply.

The reserved whole-text command is `MUNIMJEE-WA-TEST:<challenge>` with a canonical
22-character base64url encoding of16 secret bytes. A case-insensitive namespace
marker **anywhere** in text diverts to redaction, even if malformed, expired,
unrecognized, cancelled or rollout-off; only a canonical complete whole-text
command can prove a challenge. Raw commands/challenges never enter transcript,
LLM/context, audit, logs or artifacts. Canonical inbound storage contains only
`WhatsApp connection-test command (redacted)` plus ordinary signed metadata and
the tenant/contact/provider association. Suppress ordinary automatic replies for
all reserved commands. No provider payload is retained in the test row.

Valid proof additionally requires exact phone/account/generation, nonempty MID,
signed provider timestamp within floored-second `[issued_at, expires_at]`, receive
time at most30seconds after expiry and no more than30seconds before that provider
time. Deduplicate by canonical inbound message; one recipient claims a challenge
once. Receive-late, future, malformed and default-off commands are only redacted,
never promoted to a proof.

The inbound proof is scoped to this test, not marketing/utility opt-in or a durable
identity merge. Never set those contact flags from a checkbox/challenge. Require
no opt-out, a current signed inbound receipt with nonempty provider association,
an open server-observed24-hour window and current generation. First slice is
free-form reply **only inside that window**; closed window denies instead of using
an assumed `hello_world`/utility template. A future template test would require a
current approved template and category-specific consent, outside this slice.

Proposed namespace `/whatsapp/tests` under the same business/channel prefix:

| Operation | Contract |
| --- | --- |
| `POST /tests` | Owner/native/CSRF; key+generation+literal reviewed authorization. Creates challenge only, no message. One active challenge per business/generation, bounded expiry/rate. |
| `GET /tests/{id}` | Safe state, challenge validity, masked intended recipient after matching inbound, applicable window, typed blockers and local message status. No provider body/token or false delivered flag. |
| `POST /tests/{id}/send` | Explicit literal confirmation, exact key, expected generation, selected bound contact/inbound IDs and fixed text version. Queue exactly one existing canonical WhatsAppMessage; no provider call in the HTTP handler. Concurrent/changed intent conflicts; exact replay returns the same message association. |

Shared ingress must recognize the challenge before ordinary automatic reply rules,
save normal signed inbound evidence but suppress automatic replies for that test
message. Shared worker must preserve durable claim/no blind retry and revalidate
stored actor UUID, **exact UserSession UUID and auth-version**, unrevoked/unexpired
session/current owner (no rebind to a new login), generation, current credential, bound
contact/phone, opt-out/window before sending. A narrowly authorized test may run
while general automation is paused; it must **not** flip account/global automation
flags to authorize one message. No bypass exists for ordinary manual/automatic
messages. Current actor/session authority is checked immediately before a provider
send. Revocation during that external request cannot unsend it: always retain its
minimal accepted/failed/unknown observation, withholding future actions rather
than rolling back evidence or repeating a possibly accepted send. These shared
ingress/worker edits require integrator-owned exact hooks.

The one-test exception is authorized **only by the exact canonical message FK to
an immutable test authorization receipt**. A key prefix, JSON payload, contact
flag or client boolean can never authorize it. Inactive/disconnected/expired
credentials always deny. An ordinary disabled-account send retains its current
denial even if its key/payload resembles a test.

Result is derived from the canonical message, not independently marked successful:
`awaiting_recipient`, `recipient_verified`, `queued`, `sending`, `accepted`, `sent`,
`delivered`, `read`, `failed`, `unknown`, `expired`, `stale_connection`. Accepted/sent
are not delivered; read is optional. A signed status must match business, account,
recipient, canonical message/provider association (or existing opaque callback
reconciliation rules); duplicate/out-of-order/foreign status cannot regress or
promote unrelated tests. Unknown never offers a resend button. No status polling
endpoint is invented. Current-connection acceptance requires signed inbound plus
delivered/read proof for the same generation; old evidence stays historical after
reconnect/disconnect and never makes the new connection ready.
`delivery_confirmed` additionally requires exact `signed_provider_webhook`
provenance. A synthetic fixture may illustrate delivered/read status but its
confirmation remains false; it cannot turn the seller checklist ready.

## Approved persistence and ownership decisions

Existing tables do not safely hold short-lived provisional credentials or a one-use
recipient challenge. Reserved additive migration **0057 after actual0056** covers:

- Signup attempt bound through tenant composite keys to user/session/control
  generation, consumed exchange state and step claims, encrypted provisional token,
  safe choices/grant/expiry provenance and timestamps. Code itself is never stored.
- Credential provenance/expiry for the attached current generation; historical
  manual credentials remain unclassified, never inferred as Embedded Signup.
- Test intent/challenge digest+expiry, actor/sid/generation, exact request hash,
  bound tenant contact/inbound/outbound FKs and explicit authorization time. Reuse
  existing message/outbox/provider status; no duplicate delivery engine.

### Approved columns and constraints

All IDs are UUID except provider IDs (ASCII decimal1–40); all times timestamptz.
SHA/HMAC digests are lowercase64hex; versions nonnegative integers. No native JWT,
SDK code, raw command, PIN, customer phone/body or raw provider response is stored.

`whatsapp_signup_attempts`:

- `id`PK; `business_id`FK; `actor_user_id`FK; `actor_session_id`FK;
  `actor_auth_version`; `idempotency_key`; `request_hash`; `connection_version`.
- `created_at`, `expires_at` (created+10minutes), `exchange_consumed_at` nullable;
  `state` in pending/exchanging/exchange_unknown/awaiting_assets/awaiting_selection/
  setting_up/setup_unknown/attached/failed/cancelled/expired/stale.
- `nonce_digest`; `provisional_token_ciphertext` nullable; `token_delete_after`
  (no later than created+15minutes); `token_expiry_kind` unknown/at/permanent;
  `token_expires_at` nullable; `verified_app_id` nullable.
- `selected_choice_id` and `selected_phone_number_id` nullable, bound to the exact immutable choice through a tenant/attempt/phone composite key; `subscription_state`, `registration_state` each
  not_started/requesting/unknown/confirmed/failed; `selected_key`/`selected_hash`
  nullable for one exact selection intent; `updated_at`.
- A global partial UNIQUE(selected_phone_number_id) covers `setting_up`/`setup_unknown`. A selection claims it before provider POST, then fresh-queries incumbent ownership and exact current native owner/session/generation after any unique-index wait. Successful paused Account attachment and transient-claim release share one transaction. Existing Account.phone uniqueness protects attached ownership. Unknown/expired provider-claimed setup retains its claim; cleanup only clears secrets, never silently releases ownership.
- UNIQUE(business,idempotency_key), UNIQUE(id,business); actor/sid linkage validated
  against actual UserSession on insertion; identity/hash/generation/expiry fields
  immutable. Ciphertext may only be cleared or replaced by the one consumed
  exchange result; null after expiry/cancel/stale/attach. No row deletion while
  referenced. The provisional token column is never projected.

`whatsapp_signup_choices`:

- `id`PK; `attempt_id`,`business_id` compositeFK to attempt; `waba_id`,
  `phone_number_id`, `display_name`<=160, `display_phone_number`<=50;
  `verified_at`; `provider_registration_status` unknown/registered/unregistered.
- UNIQUE(attempt,waba,phone); UNIQUE(id,attempt,business). Attempt selection uses
  a compositeFK to its own choice; cannot select another attempt/tenant. Safe
  owner-only fields contain no customer contacts. Complete enumeration at most100;
  service bounds pages4×25, rejects duplicate IDs/cursors and incomplete results.
- Choice identity/attempt/tenant/WABA/phone/verified evidence/fingerprint is
  immutable; only expired unreferenced cleanup may delete it. Selection hash
  binds exact choice UUID+WABA+phone+verified fingerprint, not UUID alone.

`whatsapp_authorization_provenance`:

- PK(business_id,connection_version); FKbusiness; attempt compositeFK;
  `actor_user_id`,`actor_session_id` FKs; `phone_number_id`,`waba_id`,
  `verified_app_id`, `grants` restricted JSON array of the two used WA scopes;
  `token_expiry_kind` at/permanent, `token_expires_at`, `verified_at`.
- Immutable rows; at requires expires_at later than fixed verified_at, permanent
  requires null. CHECK constraints never compare historical immutable facts with
  mutable now(). New
  signup cannot attach unknown-expiry/grant/app identity as verified. Missing old
  provenance remains historical/manual unknown. Current proof requires matching
  current control generation and current account IDs, not merely latest row.

`whatsapp_connection_tests`:

- `id`PK; business/user/session FKs and stored `actor_auth_version`;
  `idempotency_key`,`request_hash`,`connection_version`,`phone_number_id`,`waba_id`;
  `challenge_digest`UNIQUE; `issued_at`,`expires_at` (10minutes);
  `recipient_contact_id`,`inbound_message_id`,`inbound_provider_at`,`received_at`
  nullable; `cancelled_at` nullable.
- UNIQUE(business,key), UNIQUE(id,business). Contact/inbound use composite tenant
  FKs. Actor/sid/generation/challenge/times immutable; recipient/inbound binding
  allowed once only, same canonical inbound on replay. Inbound must be direction
  inbound, exact phone/account, redacted namespace and valid signed times.

`whatsapp_test_authorizations`:

- `test_id`PK and composite test/businessFK; `business_id`; exact actor/user/session
  snapshot+authversion, generation/phone snapshot; contact+inbound compositeFKs;
  `outbound_message_id`UNIQUE compositeFK to canonical WhatsAppMessage;
  `idempotency_key`,`request_hash`,`fixed_text_version`, `authorized_at`, `expires_at`.
- Immutable after insert; all snapshots must match parent test/provenance. Message
  must be outbound text for same contact/business/phone and fixed text version.
  Authorization expires at min(authorized+120seconds, inbound+24hours, token expiry).
  Bounds are checked against fixed authorized/issued/provider times, not now().
  DB guard prevents later replacement/removal or mutation of associated message
  tenant/contact/phone/direction/kind/text/payload/key. Existing worker may update
  provider association/status/error/times; delivery facts never need a Test update.

Add UNIQUE(id,seller_id) on WhatsAppMessage for tenant composite FKs; existing
contact already has its tenant key. A DB insertion guard binds session to user,
checks parent/message snapshots and prevents authorization forgery by mismatched
foreign IDs. No shared UserSession schema change is needed. Add no credential
column to existing account: current ciphertext stays there; expiry/grant facts
live in immutable per-generation provenance. No historical backfill inference.

Use Business→Seller→control→WA→attempt for configuration locks; final native/session/owner
check after all staged writes. Consumed/step-claim commit releases locks before
provider HTTP; reacquire in the same order and recheck generation before attaching.
After revoke, minimal effect receipt update takes only the existing attempt row,
clears token and takes no later Business/Account lock. Cleanup takes transient rows
with SKIP LOCKED, clears ciphertext and never waits for Business.

Test queue reads IDs without row locks, then takes Account→Contact→Test/command,
validates current session/owner/generation through fresh nonlocking scalar reads,
inserts the canonical outbound Message and its immutable authorization atomically,
flushes, final-checks authority, commits. It takes no later Business/control row
lock. Existing sender takes Account→Contact→Message and reads immutable test
authorization without locking/updating a Test row or inserting a Test audit FK.
Ingress reads candidate test IDs without locks, then takes Account→Contact→Test
before binding recipient and inserting redacted canonical inbound. All generated-message/test receipt FKs
are completed in that same transaction; no visible queued message lacks its
authorization. No Account→Business cycle. Required opposite-direction proofs:
signup/legacy config versus queue/worker, queue versus status webhook, duplicate
challenge arrivals versus cancel/send, cleanup versus each setup step, session or
owner revocation at every staged/HTTP boundary. Provisional
token retention max15minutes; expiration/current-access loss cancels future use and
cleanup clears ciphertext even when rollout is off. Operational cleanup scheduling
and retention of minimal immutable audit receipts must be approved separately.

Owned proposal paths: new WA schema/model/service/API/client/tests/docs plus narrow
existing channel-page integration after approval. Integrator owns main/config/CSP,
model registry/migration allocation, native onboarding projection, worker+ingress
hooks and **all channel analytics producers**. Tests/challenges/sends are tagged
server-side test activity; never counted as production enquiries/automation. No
client-supplied test/live promotion or duplicate activity producer is added here.

## Required verification before code acceptance

- Pure strict DTO/SDK event parsing, literal booleans, v4/default-off/config denial,
  exact-origin rejecting suffix lookalikes, unknown provider shapes and redaction.
- Actual migrated PG tenant/sid/state/nonce/key/expiry/generation binding; stale or
  duplicate callback/code cannot issue another exchange; revoke after provider or
  flush saves no credential/check/audit; both legacy/native race directions.
- Multi-phone explicit selection; foreign/missing/mutated accounts, partial pages,
  repeated cursors, malformed IDs and unique-phone conflicts fail closed.
- Each register/subscribe timeout/lost response remains unknown without duplicate
  provider POST. Secret/PIN never in response/log/storage; current GET is not a save
  receipt. Provisional cleanup works with flags off.
- Challenge dedupe/expiry/foreign business/wrong account/old generation, opted-out
  recipient, stale/absent inbound/window, duplicate send and concurrent sends;
  native/current-owner loss before commit/worker dispatch rolls back/withholds.
- Existing outbox unknown/crash/status races, no duplicate sends, no delivery claim
  from local accept, old proof does not approve a reconnected generation.
- Mounted actual-main/native signup→gated flow using explicitly synthetic SDK and
  provider transport; no real keys/calls/sends. Reload/unknown intent, focus/session
  replacement/role loss/stale responses/physical privacy scrub and owner-only UI.

Real acceptance remains a later named owner action: configure verified Meta app/v4
Cloud-only configuration/HTTPS+webhooks/grants/billing; perform actual consent and
phone verification; inspect real token/grant/account membership; then have a
specifically consenting real recipient send the challenge and explicitly authorize
one test reply, inspect signed inbound/delivered status and reconnect/disconnect.
No part of that live canary is authorized or executed in this task.


### Reviewed owner recipient projection and recovery seam

`GET /tests/{id}/recipient` is current OWNER + the original exact native sid only. It reads the intended phone from the existing canonical Contact (no new PII column), with exact contact/inbound IDs, generation, observed inbound and reply-window bounds. A final fresh scalar owner/session/active-tenant/generation check follows all awaited lookups. The private response has no-store/no-referrer/noindex headers. This is an explicit confirmation view; browser-supplied recipient details cannot authorize a test, and its phone never enters journals/audits/result snapshots. `TestChallengeView` has a repr-hidden ephemeral raw command only for an explicit owner start response. Summary TestView remains masked.

Reserved native recovery prefix `munimjee.v1.whatsapp-setup:` contains only exact nonsecret command keys/safe IDs/stage, bound to current user/business/native-session fingerprint. It never contains signed state, code, PIN, provider/native token, recipient phone or raw command. No automatic provider POST or new key follows reload, malformed storage or an unknown result. Shared cleanup dependency1805ea1 is separate from owned runtime.
