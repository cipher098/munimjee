# Native comment review and inferred-enquiry visibility

Status: bounded contract and concrete `0056` tables, including the exact four-column inbound receiving-account FK, accepted by the integrator. Source base `3820d14`; no database or browser evidence exists for this new slice. The repaired `0055` writer remains the only comment sender. This document does not certify provider permissions, a live window, customer delivery, or broader V08 completion.

## Operator task

An owner or manager can inspect why a comment reply did not run, maintain an explicitly scoped static rule, and record a review without another send. A person handling the inbox can see an activated-product WhatsApp follow-up that automation withheld because its reference was inferred. The existing native commerce interface is the visual authority: Operate mode, readable tables, focused dialogs, plain explanations, and controls that work at 390px. No redesign of channels, catalogue, or inbox is included.

The three sections are **Comment activity**, **Comment rules**, and **WhatsApp enquiries**. Each has a bounded, tenant-scoped cursor list and a detail view. A comment row shows the message excerpt, received time, independent public/private outcomes and the plain withholding reason. A review dialog shows the original comment and saved copy, current eligibility, and previous decisions. A rule save or preview is labelled as sending nothing. An inferred WhatsApp suggestion is labelled “Possible context”; it is never displayed as a confirmed product selection.

## Authority and private state

- Native session/current user, active Business/Seller, current membership and `inbox.read` authorize every list/detail. Rule mutations, preview and review closure require `automation.manage`, native CSRF/Origin protection and fresh authority after every row/HTTP wait and after flushing staged receipts, before commit. Support grants do not participate in this resolver.
- Read results recompute visible capabilities from the final authority check. Browser requests and responses are generation-fenced. A revoked/replaced session, lost tenant access or failed identity check clears private rows, message/customer text, selected dialogs, command bodies and recovery state, and latches the page against revival by an older successful request. Focus/pageshow/visibility recheck the same user and native-session fingerprint. A role downgrade removes controls without granting a new identity.
- Private responses own `no-store`, `no-referrer` and `noindex` headers. Source binding JSON, HMACs, access tokens, accepted claim JSON, internal claim tokens and raw provider payloads are never public DTO fields. User/provider text uses `textContent`, including previews and recovery summaries.

## Delivery versus review

`delivery_state`, current `eligibility` and `review` are separate projections. An unattempted action can say “No send attempted” only when its durable attempt/claim/receipt history proves that. A committed claim or an unknown effect says “Send result not confirmed”; a provider receipt says “Provider accepted”, never “Delivered”. Public and private actions remain independent.

The only review operation is **Close after review — no new send**. It requires an explicit strict boolean confirmation, a bounded human reason, and the expected fingerprint of the event and all actions. The server locks the exact tenant event, validates a fresh scalar projection of its actions, and refuses closure while any action is pending or sending. It never waits on action locks while holding the event: the existing sender locks Action before Event. Terminal transitions cannot return to pending/sending, so closure needs no opposing action-lock order. It appends an immutable review and command receipt. It never updates the accepted event, action body, claim, unknown result or provider receipt. Closed reviews do not remove the original outcome from detail/history. There is no retry, resend, rebind, mark-delivered or bulk-resume endpoint.

## Rules and previews

Native rules require one explicit media ID and one current tenant-owned product, bounded keywords and bounded public/private static copy. Activated products cannot enable static-copy rules. A disabled rule may be edited without claiming that it is eligible. Enabling also requires current channel control/account-access evidence and all current comment policy gates that can be evaluated without an actual event. Account-access verification is not provider permission approval.

Every update/disable supplies the expected canonical fingerprint of the complete current rule. Under the tenant rule lock, a mismatch is a typed pre-mutation rejection. A change applies only to later incoming work; immutable old actions are never rewritten. Existing pending actions continue through the sole writer's current configuration/generation checks. Preview matches a saved rule and explains current withholding with `sends:false`; it is neither an authorization snapshot nor a current-SKU fact renderer.

## Exact command recovery

A command UUID is unique within the business. The durable receipt binds operation, actor and a canonical body hash and retains the accepted result identity/fingerprint. A same-body same-actor replay returns the original result before stale-context checks; a different operation/body/actor is rejected. The current native session and capability are still required on replay.

The proposed private journal prefix is `munimjee.v1.comment-command:`; it must be registered in shared identity cleanup before use. A journal envelope is scoped to user, business and a SHA256 native-CSRF session fingerprint, contains the exact bounded body/key, is written and read back before POST, and is never automatically replayed. Unknown transport, malformed/stale acknowledgements and unclassified HTTP errors preserve the exact intent. Only a server-typed rejection proven before mutation can release it for editing. The UI shows frozen human facts, not raw request JSON or wire UUIDs. A rule acknowledgement must match the command, result rule and accepted fingerprint; review acknowledgement must match the exact event/enquiry and immutable review receipt.

## Inferred WhatsApp enquiry

`reel_catalogue_reply` needs an explicit typed decision for the exact case: an activated product is matched, rollout permits current facts, but `reel_context.source == 'recent_message'` makes it ineligible for automatic facts. An arbitrary `None` result is not enough to create this reason. The original signed inbound message/contact/account remain authoritative; no new URL fetch or product inference is introduced.

The inbound insertion and one enquiry record commit in the same ingestion transaction, uniquely keyed by tenant and inbound message. The record stores the exact inbound ID/contact and receiving phone-number ID, a bounded stable reason, and creation time. Message text and suggested references are read from the original tenant-owned inbound message, without copying a whole transcript. Repeated provider delivery cannot create another enquiry. There is no automatic historical backfill or silent replay of an old inbound event.

An enquiry can be closed once with explicit confirmation/reason and a separate immutable closure/command receipt. Closing sends nothing and changes no contact opt-in, provider window, product/variant, outbox message, order or payment. The UI directs the person to the original conversation; this slice adds no second manual sender. Open/closed derives from the closure ledger, preserving the original message and reason.

## Source inventory and integration seams

- Existing legacy comment management: `backend/app/api/routes/comment_automation.py`; native users are correctly denied legacy dashboard credentials. New native router/service/schema/page are additive.
- Existing accepted comments/actions and immutable `0055` audits: `backend/app/models/comment_automation.py`; no alteration of their accepted/send fields.
- Existing sole comment dispatcher: `backend/app/workers/comment_automation.py`; no sender, startup, rate or buffering replacement.
- WhatsApp typed-decision seam: `backend/app/services/whatsapp_context.py`; persist the new exact inbound-linked enquiry in `backend/app/services/whatsapp.py` after trusted ingestion and before its transaction commits. Existing `auto:reel` writer and delivery regeneration remain unchanged.
- Proposed migration `0056_v1_comment_operator` follows actual `0055_v1_comment_binding`. New tables: immutable operator command receipts, comment review ledger, exact inbound enquiry rows and enquiry closure ledger. All new tenant/actor/source FKs are validated. Rule concurrency uses a canonical fingerprint rather than a new rule version column.
- Shared main/model/navigation/package/journal-cleanup registration remains integrator-owned. No DDL or shared source edits occur until the concrete proposal is confirmed. No DB/browser before a newly released lane allocation.

## Required proof

Actual migrated mounted tests must cover owner/manager/viewer/foreign tenant, revoked sid and downgraded role during row/flush/read waits, final capabilities and private DOM clearing; cursor tamper and concurrent inserts; public/private split outcomes; close-versus-claim and two-close races; exact replay after a lost response; stale rule fingerprints and uncertain rule acknowledgement; activated/unbound media held; and the original five sender safety negatives remaining zero-provider. Signed WhatsApp duplicate delivery must create one visible enquiry and zero outbox rows for the typed inferred case, while explicit same-contact quotes still use fresh facts and foreign-contact references remain denied. Mobile/desktop render review, keyboard dialogs and no horizontal overflow are required. Provider transports stay synthetic; live permissions/window canary and broader automation quality remain separate.
