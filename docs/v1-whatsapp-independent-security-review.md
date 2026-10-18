# Independent0057 foundation security review

Reviewed source: exact immutable Git snapshot `944395c`, not a mutable service draft.
This branch owns review tests/docs only. No runtime/migration or shared hook edits,
DB/browser run, Meta request, message or provider capability validation occurred.

## Additional confirmed finding

`whatsapp_test_authority.intercept_reserved`, source lines91–111, accepts any
nonempty provider MID up to255 characters and stores it unchanged in both canonical
`provider_message_id` and `idempotency_key`. Its broad reserved-packet scan correctly
notices a challenge anywhere in signed metadata, but body redaction alone does not
remove the challenge when it is in that retained MID. This violates the helper's
no-raw-challenge retention contract even when tests are default-off.

The actual helper ran against a fake SQLAlchemy session and actual message models:
`test_reserved_secret_in_provider_mid_never_reaches_any_retained_message_scalar`
**fails at944395c** because reserved metadata was retained. The assertion/log only
shows a boolean failure; no challenge/packet is printed. This is synthetic signed-
packet metadata behavior, not evidence that a real Meta MID has this shape or an
actual database was written. Raw negative: `foundation-mid-negative.txt`.

Catalogue acknowledged the finding and reports an uncommitted fix that rejects
reserved/nonprintable MID before any contact/message insert. That fix is **not yet
independently executed**; recheck the next frozen SHA before calling this resolved.

## Bounded source verdict and coverage

No other substantive foundation blocker was identified in the fixed Graph
origin/path/method/query/body allowlist, pinned public DNS/TLS route, denial of
redirects/proxies/untrusted next URLs, bounded JSON/duplicate-field parsing,
required exact-app/granular-WABA grants, explicit complete phone-choice pages or
secret-free exception/repr surfaces. These are source properties and synthetic
compatibility assumptions, not actual Meta wire/permission proof.

An additional no-network adversarial regression confirms that cancelling four
Graph waiters does not free admission while their underlying jobs remain in flight:
the fifth request is denied, with exactly four bounded fake jobs. It **passes** at
944395c (`foundation-cancellation.txt`). The temporary executor is released in a
finally block. No DNS/socket/provider is used.

Already acknowledged findings were not duplicated: coherent final exact-test
session/role/tenant/account/provenance authority; unbound BEFORE DELETE returning
OLD; and durable pre-provider phone claim/partial uniqueness across setting_up and
setup_unknown. No final runtime/DDL authorization verdict is made while those
fixes and the native signup/service/queue hooks are not a frozen tested whole.

Pending follow-up: portable test recheck on the coherent new SHA, then actual
migrated concurrency/expiry/idempotency/unknown-effect tests only after explicit
serial lane allocation. Preserve canonical signer/outbox behavior and no blind
retry. Provider consent, real recipient delivery and external configuration remain
separate closed acceptance gates.


## Coherent backend6a8d6be follow-up (no actualDB yet)

Dependency6a8d6be was applied as461006e on this test-owned branch; no owned runtime
edit was made. The frozen reserved-MID negative now **passes**, and the Graph
cancellation/admission regression still passes (`coherent-6a8-independent.txt`).
The MID fix rejects the marker and nonprintable bytes before any Contact/Message
insert. No challenge is printed in either historical or repaired logs.

Additional portable negatives at exact6a8d6be:

1. `exact_test_authority` reads the global test rollout flag only before awaited
   projections. Disabling it while the last projection completes still returns an
   allowed authorization. The actual helper test expects withholding and fails.
   Catalogue accepted a final synchronous rollout/current-app/webhook-config gate.
2. `queue_fixed_reply` always stores authorized+120seconds even if verified token
   expiry is only10seconds away. This violates the frozen min(120s,token expiry,
   inbound+24h) receipt bound. The existing sender separately denies expired
   current grants; this finding does **not** claim an expired-token send. Catalogue
   accepted the minimum bound in service plus DB insertion guard.
3. `provider_step` and `exchange_signup` check authority, then await the committed
   claim, then invoke the provider without a new post-commit authority check.
   Revocation during that awaited commit can start a new external operation before
   the later401. Both exact-function controlled commit callbacks reproduce one
   attempted fake operation where zero is expected. This is revocation **before**
   provider invocation, separate from an effect already in flight. Owner response
   and the next frozen repair are pending at packet creation.

`coherent-6a8-extra-negatives.txt` preserves2 failures (flag andTTL).
`coherent-6a8-claim-revocation.txt` preserves2 failures (exchange/subscription).
These tests model only source control-flow boundaries with fake query/commit
callbacks; they neither prove PostgreSQL races nor certify DDL/transaction rollback.
A follow-up actual migrated test must reproduce revocation around real committed
claims and assert zero provider operations, durable safe disposition and exact
replay/no duplicate effects. Native services/shared ingress/outbox UI composition
and current credential-fingerprint provenance remain independently pending.


Portable fixture correction: the TTL source row now includes its immutable real
`inbound_provider_at`, which the contract minimum uses. The final-flag test supplies
valid synthetic matching app/webhook configuration, so a separate configuration
denial cannot mask regression of the rollout check. With both corrections, the
original6a8 source still reproduces the same2 intended failures
(`coherent-6a8-fixture-correction-still-red.txt`); assertions are unchanged. The
author's draft5pass/1missing-fixture-field report is not our frozen-fix acceptance.


## Fix snapshot0254ce5 portable recheck

Runtime dependency0254ce5 is local aliasbadb461, not an owned runtime change.
The independent suite now passes8 source-only cases (the previous6 plus paired
non-revoked positive controls for exchange/subscription). Each revoked commit
requires401 and zero attempted fake operations; each otherwise-identical current
control succeeds with exactly one fake operation and no unknown-effect cleanup.
Fixtures provide valid native binding, current scalar projection and requested/
verified AppID123. This prevents missing fixture data or unrelated failure from
masking the ordering regression. Historical failure logs remain unchanged.

The final flag/TTL/MID fixes are coherent in this snapshot. This does not certify
real PostgreSQL claims, rollback, immutable DDL or mounted native composition.
A separate valid AppID rotation during claim commit remains a confirmed source
gap at0254: the final configuration shape check does not bind the already-built
client/attempt to the currently configured app. Catalogue accepted an immutable
requested-App binding; its next coherent freeze remains pending. No provider,
DB or browser operation was performed by this recheck.


The requested independent valid-App rotation proof now reproduces the gap at
0254 in all three actual service paths: exchange, subscription and registration.
The claim-commit callback changes configured App123 to456 while native authority
stays current; a shape-valid configuration seam isolates App binding from other
configuration failures. Each path attempts one synthetic provider method when
zero is required. Original-app controls dispatch once; SID-revoked controls deny
with401/provider0. The expanded source-only run is10pass/3intendedfail, retained in
`fixed-0254-app-rotation-negative.txt`. No SQL persistence or live transport is
claimed. The new fixture already supplies immutable requested/verified App123;
owner repair and actual migrated App-rotation proof remain pending.


## Requested-App freeze85780f4 source recheck

Dependency85780f4 is localalias982296e. Its final SQL projection now compares the
immutable requested/verified App to current configured App, and preclaim, returned
exchange grants, browser-state and attachment checks preserve that binding.

The first rerun (`fixed-85780-independent.txt`) still had an always-positive fake
scalar that did not evaluate these new predicates. Its three failures are a
fixture gap, not evidence that the commit-time repair failed. The corrected
fixture evaluates actual compiled requested/verified-App bound predicates; if
those predicates are absent, it does not invent a denial. Original commit-time
rotations now withhold and matching-App positive controls still dispatch once.

A remaining tail independently reproduces coordinator's source finding: rotate
the valid configured App while the last scalar completes. That query captured
App123, so its valid result can return after current config becomes456; current
shape validation alone allows the old client's NEW operation. Exchange, subscribe
and registration each attempt one fake method. Expanded run13pass/3intendedfail
(`fixed-85780-app-final-scalar.txt`). Capture queried-App and compare synchronously
after the last await, before client dispatch. Owner notified; no additional policy
or runtime edit was made. No actualSQL/provider/browser execution is claimed.


## Final bounded source verdict at e897ee6

Independent rerun of the exact16 cases on frozen e897ee6 (localdependency230a7f6)
passes16/16. All reported source failures are resolved in the bounded reviewed
backend: reserved-MID suppression, immutable minTTL, final rollout/config gates,
post-claim native/current-generation check, original-App binding across commit
and final scalar, late attachment/route App guards. Matching controls still reach
each fake exchange/subscribe/register once; revoked or changed-App controls reach
none. Source review also retains one-way provider association, ordinary unbound
message deletion, exact ciphertext provenance/ambiguity denial, strict explicit
selection and unknown-effect no-retry semantics. No remaining substantive backend
source blocker was found within this scope.

This is a source/no-network verdict, **not runtime authorization or enablement**.
No PostgreSQL migration/rollback/trigger/concurrent claim was exercised by this
packet, no shared canonical ingress/outbox hook was installed here, and no UI
render/browser/provider consent/test-delivery claim is made. The owner must still
prove actual0056→0057 and native/signed ingress/current outbox composition under
the separately allocated serial lane. Synthetic transport evidence does not
certify live Meta permissions, SDK/provider wire shape or recipient delivery.

The runtime hash manifest compares the reviewed e897ee6 commit with these local
files; dependency aliases are not owned feature changes. Preserve all historical
red logs and the explicitly labelled85780 fake-predicate fixture gap.


## Shared installation source review d541311 against64d9c47

Read-only exact-commit review clears this bounded diff: reserved interception
precedes ordinary identifier/dedupe/transcript/customer-link/activity processing;
the existing worker's paused exception requires exact immutable Message-FK proof,
and fixed text has no subsequent asynchronous template/reel/parcel branch before
the existing provider. A shaped key alone remains denied. No second sender or
authorized-test activity classification is added. Ungated cleanup is bounded and
commits its own session; task registration does not prove deployed execution.
Model/named Message unique and explicit three-asset allowlist match0057; owner
links are contained in incumbent physical session-fenced containers.

This is source-only review, not a new execution claim. Shared installation still
requires actual0057 migration, signed ingress/canonical worker and mounted proof.

## Prepared actual0057 independent race cases

Owner fixture927ccf1 is dependency alias71a7ae1, not owned runtime or test setup.
The new independent DB file imports its actual P01/main-mounted fixture and
preparation helpers without fallback registration. Six cases collect only:
exchange/subscribe/register crossed with SID revoke immediately after real claim
commit or valid App rotation during the real final scalar. The first uses a
separate committed revoker transaction; the second changes configuration after
the actual joined SQL returns. No fake DB scalar/authority/outbox is installed.
Each requires zero NEW targeted provider method, preserved unknown/partial effect
history, no attached credentials and no repeat on exact replay. Earlier confirmed
subscription may remain when registration is withheld. This is not a blanket
revocation of an external effect already invoked.

These6 have NOT run on PostgreSQL. Owner actual fixture/shared mounting fixes and
explicit serial allocation remain prerequisites. Catalogue currently owns the
sole actual0057 lane; no parallel database/browser run was started here.


Prepared fixture refinement before actual execution: catalogue's source review
caught that the late-App registration hook could match the earlier subscription
projection in the same select request. The hook now requires its exact requested
stage column/requesting state (or exchange/exchanging) before rotating. All6
still collect; no actual first-failure or runtime result is claimed.

Read-only b853f4a header-tail review is clear: the custom route preserves private
headers through HTTPException and supplies generic non-echoing validation errors;
normal success remains private. It does not weaken native/session/capability
checks. The email fixture compatibility correction7c501b6 is test-only.
