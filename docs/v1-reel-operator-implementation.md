# A13 native single-enquiry link and eligible resume

Source-only implementation starts at approved0057 composition
`6ff11c3d073c5617e18cc439e04809db6dd760ad`. Initial contract was composed as
`04a0493`; the approved unconditional-final-guard clarification is pinned at
`24f746f21247fca5a716018d8858241721b3990e` (contract SHA-256
`f0e3986b92a2a790b5e70e790c4d6dcc55c0c6a1372b513c12b9af01c9a9c46c`).
The base is an approved source dependency, not a claim of final0057 acceptance.

Implementation checkpoints: `34f2125`, `a2d4109`, `9f7a2e8`, `aba5c14`,
`86ba2ef`, `00f4e93`. Final source is
`00f4e93935659c8a059adc4812949eaaadf9cbe4`.
Only five new runtime/schema files are authored here: the `whatsapp_reel_operator`
router/schema/service/model modules and `0058_v1_reel_operator.py`, whose real
predecessor is `0057_v1_whatsapp_self_service`. Application registration, package
allowlists, navigation, trusted ingress, client journal/cleanup and canonical sender
installation belong to the integrator. None is silently installed by this lane.

## Public contract

Routes use `/api/v1/businesses/{business_id}/whatsapp/reel-enquiries`:

- GET collection: `items`, `next_cursor`, `can_manage`, with a limit of1–50.
- GET `/{inbound_id}`: exact business/inbound IDs; original message and received
  time; customer name/last-four reference; safe account hint; original source
  classification and nullable shortcode/URL; current connection version/state
  fingerprint; current matches and at most50 product ID/name candidates; explicit
  `eligibility.can_link`, `can_resume`, nullable reason, and `can_manage`.
- POST `/{inbound_id}/link`: strict `LinkCommand` with only idempotency key,
  `link_only|link_and_resume`, selected product, shortcode, expected fingerprint,
  strict nonnegative expected version and literal confirmed:true. It returns bound
  business/inbound/command/key/action/product/request hash, result, and replay flag.

Result contains only mapping=`saved`, resume=`queued|held|not_requested`, nullable
queued reason or required held/not-requested code, nullable outbound UUID and
accepted mapping fingerprint. Queued means an outbox intent, never delivered.
Missing account hint is the safe string `Not connected`.

`request_hash` is SHA256 of JSON `{business_id: string, inbound_id: string,
body: command.model_dump(mode='json')}`, with sorted keys, compact separators,
ensure_ascii=True and allow_nan=False. `receipt_view` returns the exact saved
result on replay under current authority. Changed actor/session/auth-version/body
with the same tenant/key conflicts. A typed pre-effect refusal is emitted only
following receipt lookup and before mapping/outbox writes:

```text
{code: reel_operator_pre_mutation_rejection, business_id, inbound_id,
 idempotency_key, request_hash, accepted: false, reason: stable_code}
```

Unclassified transport/error responses remain uncertain to the client. This lane
does not change the integrator-owned client journal or error-detail forwarding.

## Authority, mapping and persistence

`list_enquiries`, `read_enquiry`, `link_enquiry` and `revalidate_resume` retain the
frozen signatures. Reads require current native `inbox.read`; mutation requires
`automation.manage` plus native session/CSRF. The real request callback returns
`ReviewerBinding(user_id, session_id, auth_version)`, never browser assertions.
Service checks after waits and final staged flushes; the route also uses the
incumbent caller-commit `business_mutation` guard. No service commits or provider
calls occur.

The selected source is resolved tenant-locally and locked Account→Contact→Message.
A short savepoint/NOWAIT lock targets only the chosen active Product. Only exact
55P03 contention becomes a typed busy result; other DB errors propagate. Selected
product must be present with the same name in the bounded reviewed candidate
projection. All exact current reel matches are checked again after acquiring the
Product lock. Conflicting mappings are refused before effects. No broad Product
lock sweep, SKU/Storefront locks, stock reservation or price mutation is added.

Only `Product.reel_urls` is updated. The original inbound payload/classification,
other enquiries and contacts remain untouched. Quoted sources bind their exact
same-tenant/contact/receiving-account message, provider association and private
source fingerprint. Inferred recent-message context can record a mapping and held
receipt; it never becomes explicit or queues an authorization. Unknown/malformed
references fail closed. Source timestamps stay the original provider-derived
inbound time. Equal-time competing inbounds conservatively block stale resume.

The service reads existing approved/current SKU facts; no legacy product-price
fallback is introduced. Missing authority holds without queuing. Unsupported
questions use the existing HANDOFF; untracked availability keeps its existing
confirmation wording. Fresh replies do not reserve inventory or choose a variant.

`WhatsAppReelCommand` is an immutable complete receipt with current native session
insertion guard, validated membership/Product tenant FKs and exact source four-part
FK. Private credential and recipient-phone fingerprints prevent generation or
recipient rebinding without copying a raw token/phone into the receipt/result.
The command insertion guard also requires exact reply-context equality with the
original single-reference context, replacing only matched status and selected
product ID/name; classification and other source fields are preserved.
The state fingerprint includes current candidate IDs/names and source/account/
contact/reply-activity observations. Expected and accepted reel-array fingerprints
are exact, conservative snapshots; later reordering also requires review.

`WhatsAppReelAuthorization` binds an immutable command and exact inbound/outbound
four-part identities, unique per tenant/source and outbound. Its insertion guard
requires explicit classification, canonical key/context, a new unattempted queued
text row in the current transaction and no competing outbound since the source.
The service additionally refuses every prior canonical key before `queue_message`
can return an existing row. A deferred completeness guard requires queued receipts
to have their exact authorization before commit. Link-only/held/inferred receipts
have none. No historical backfill/promotion,0056 enum extension or terminal retry
is added. DELETE/UPDATE guards retain source/review history; empty-only downgrade
refuses retained receipts.

## Last dispatch boundary: integrator installation required

Install `await revalidate_resume(db, account, contact, message)` **unconditionally**
as the last outer await before incumbent `provider.send`, following ordinary
current-source checks. Never use its None result, a JSON flag or key prefix as a
send exception. There must be no later asynchronous work before provider dispatch.

The helper selects immutable outbound authorization. With no native authorization,
it calls existing0057 `exact_test_authority` as its own last await, ignores the
returned object, and immediately returns None. Thus an exact-test message retains
its own final0057 scalar; ordinary work retains incumbent gates. Invalid exact-test
proof propagates409. No family-selection boolean is introduced.

For native-bound resumes the helper regenerates selected-source approved facts or
HANDOFF and flushes current text before a single final fresh scalar. That statement
joins exact immutable command/source/outbound, current native session/auth-version/
active manager-or-owner membership, tenant/seller, account/control flags and
version/credential fingerprint, recipient fingerprint/window, active publication/
reviewed mapping/activation, all exact reel matches, current product name/revision
and complete observed active SKU JSON. The current name must also equal the saved
reviewed label; a post-queue rename holds, while current approved price/stock can
be regenerated. Newer inbound and every other outbound
claim/attempt/unknown/manual reply block it; only the exact immutable authorized
outbound ID is excluded. Quoted proof and original source fingerprint are checked
again. Native auth/factual rollout flags are checked before and synchronously after
the scalar. Success immediately returns None; bound failure raises409.

0057 exact-test and0058 reel authorizations remain separate:0057 requires fixed
text/empty payload with immutable message association;0058 requires reviewed reel
context/canonical key and its own immutable association. This document does not
claim a nonexistent0057 canonical-key constraint.

## Verification and limits

All five files compile in memory without app imports, bytecode output or database
connections. `artifacts/v1/reel-operator-implementation/source-preflight.json`
records exact source/contract hashes, real migration predecessor and unchanged
existing application/schema/test boundaries. Source review identified and corrected
NULL-unsafe quote proof, result/action consistency, current-control/native flag,
post-lock mapping and recipient/label binding issues. Independent QA owns the
frozen tests; its DB cases are authored but unrun until the integrator allocates a
serial lane. Adapter checks cannot establish actual worker/SQL/trigger behavior.

No migration, native session/CSRF journey, DB/browser/server, provider/model,
credential, sender, Docker, installation or tool-capacity operation ran here.
Actual0058 application integration, synthetic signed-ingress/native review/worker
journey, concurrency/revocation cases and mounted UI remain separate gates. No
current Meta policy/permission, real consent/delivery, physical device, image,
restore/rollback, deployment or full V1 acceptance claim follows.
