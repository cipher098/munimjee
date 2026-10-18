# Native explicit reel link and eligible resume (A13)

Integrator-frozen boundaries,18October2026. Baseline `1c4b3b451832bc94fceafa145c720bf74ac1433c` (actual0056). Existing requirement: go-live-plan§3 rule9 and acceptanceA13. This is the missing native workflow, not a new messaging engine or general V08 expansion. No provider action or enablement is authorized.

## Exact native journey

A current native actor with `inbox.read` opens the existing comment/enquiry workspace, selects **one inbound enquiry UUID**, sees its account/contact hint, original explicit reel reference and current match/eligibility reason, and chooses an explicit active product. Mutation requires `automation.manage`, native session/CSRF and an explicit confirmation. Support grants never grant access.

The two actions are **Link only** and **Link and request one eligible reply**. No freeform reply, bulk group/contact selection, inferred recipient, variant/order/payment/stock change or automatic send from a GET. A preview/read never changes the mapping or queues a message. The response distinguishes mapping saved, queued for current checks, held without a send, and uncertain command response. Queued/accepted is not delivered.

Scope is the selected source only. Legacy `link_and_resume` mutates a whole shortcode group across contacts and therefore cannot be called unmodified as the native command. A shared product→reel mapping may become visible to other future enquiries; that does not authorize queueing, closing or rewriting any other contact's historical message.

## Source and authority

Server resolves business, Account, Contact, exact inbound Message and provider/source timestamp from trusted persisted records. Bind inbound UUID+tenant+contact+phone/account+provider MID+original context fingerprint. Browser supplies only reviewed IDs, exact shortcode, expected state fingerprint, expected connection version, action, explicit confirmation and idempotency key; no source/verified/recipient assertion, credentials or customer text.

Original context classification stays unchanged. `message_link`, `referral_link` and `quoted_message` must still resolve to the same exact supported reference before any eligible resume. `recent_message` remains inferred: linking/review may record a mapping, but cannot silently promote it to explicit or auto-resume it. Unknown/ambiguous/foreign/missing/changed products or multiple conflicting references stay held. No name/phone/title/vision inference chooses a product.

Read only approved current facts from active tenant/seller, published storefront, activated/reviewed mapping and active authoritative SKUs. Ambiguity, unsupported facts, unknown availability and unsupported legacy authority follow the existing fact/handoff contract. No floor/cost/private description, automatic variant choice, reservation or financial operation is introduced.

Current native sid/auth-version/capability must be rechecked after waits and after all staged audit/receipt flushes, before caller commit. Receipt replay still requires current authority. Queue authorization and shared sender guard must bind/recheck the reviewed actor, selected source, account/version, current product/mapping and current policy; the current native actor sid/auth-version and active automation.manage membership at dispatch. They are never supplied as authority by a browser.

## One command, durable receipt, one writer

Use a dedicated immutable tenant/actor/body/key receipt and safe result, with exact inbound four-part tenant/contact/phone FK and tenant Product FK. Do not silently add operations to0056's five-operation CHECK or reinterpret comment closure receipts. Integrator reserves **0058_v1_reel_operator → real0057_v1_whatsapp_self_service**. Remote authors exact DDL/models only against the integrator-supplied approved0057 source base; no invented predecessor. No fake predecessor or legacy backfill.

Receipt-first exact replay returns the same accepted outcome under current authority; changed actor/body/key conflicts. Persist accepted mapping/queue intent and audit atomically, then commit before any provider I/O. A lost HTTP result retains the exact frozen command in the current user/business/session-bound journal; only explicit retry with its original body/key. A well-shaped unrelated/stale200 or unclassified409/422 never clears the uncertain intent. Typed pre-mutation rejections are allowed only after receipt lookup and before effects.

Reuse the existing exact Instagram-reference parser, product mapping/fact resolver, `queue_message`, canonical outbox key (`auto:reel:<provider MID>`) and **existing** `deliver_one`. No new sender/LLM/collector, no bulk legacy service duplication, no second action key after uncertainty. An existing source reply claim/attempt/unknown/manual reply blocks a new automatic action; no terminal result is resurrected. Newer inbound/STOP/opt-out or manual contact activity blocks stale resume.

## Locks and final delivery boundary

Keep canonical Account→Contact→Message order. Mapping Product write must not wait under those locks: a short savepoint/NOWAIT target Product lock with a safe pre-mutation busy disposition is frozen. Resolve **all** exact current reel matches and deny conflicts; never first-hit selection. No broad Product sweep, SKU/Storefront row locks or provider HTTP inside the native transaction. Preserve transaction usability after contention.

The current worker rechecks mapping/window/account, but the reviewed native source additionally requires **newer inbound/manual reply/review-binding revalidation immediately before provider dispatch**. Integrator owns/reviews this narrow shared sender seam. Fresh scalar reads under existing canonical locks; do not add reverse lock acquisition. Pending text is never fact authority: regenerate from current approved SKU/source references at the actual existing send boundary.

Use current effective account/automation/reel flags, recipient opt-out, original source age and current reply window, tenant/seller/publication/mapping/SKU authority, current review/actor binding and already-attempted/unknown state. Connection replacement or changed accepted review context requires withholding/review, not implicit rebinding. This new reviewed-resume guard does **not** impose a blanket generation-cancellation policy on ordinary existing auto:reel work; the separately tested explicit-current-owner re-enable/fresh-facts contract stays unchanged.

Unknown provider effects stay unknown and cannot auto-retry. Closing/reviewing a source never marks delivered or recalls already invoked effects. If the source is now ineligible, show a specific stable reason and queue nothing; recording a mapping is separate from permission to send.

## Ownership and acceptance freeze

Frozen remote ownership: new `whatsapp_reel_operator` schema/service/router plus dedicated receipt/authorization model declarations, allocated0058DDL/tests, and the narrow existing comment operator UI/contract extension. Integrator owns model registry/main/package/navigation/cleanup/shared sender+trusted-ingress install; existing catalogue/import/credential/financial files stay with their owners. Social independently reviews source and runs separately allocated acceptance. No DB/browser/process activity until serial slot grant.

Required local evidence: actual migrations/native session+CSRF, exact one-source link and eligible once-only queue; duplicate/lost response/same-key replay/body conflict; two simultaneous operators; stale mapping/source/newer inbound/manual reply/STOP; role/sid/account-generation/config change while waiting and after claim; published/current SKU facts; inferred remains inferred/no send; unknown prior effect cannot resume; foreign tenant/contact/account denial; no mutation to other contacts; stale UI/401/session replacement physically scrubbed; paused vs queued vs accepted/unknown truth. Final mounted actual-main journey must use signed synthetic ingress, approved native product review/link, canonical worker and synthetic provider only. Transport/device/provider/live permissions stay separately pending.

No claim of actual official Meta policy/window/permissions, real recipient consent/delivery, hosted deployment, new image/backup/restore or physical phone acceptance follows from this slice.


## Frozen persistence/API/helper shape

Names may follow repository naming conventions, but these bindings/constraints are mandatory:

- `WhatsAppReelCommand` / `whatsapp_reel_commands`: UUIDid; business; native actorUser/session/authVersion; UUIDidempotencyKey; action=`link_only|link_and_resume`; canonical requestHash; exact inboundMessage/contact/phone/account receiving identity; original providerMID/context classification/source fingerprint; shortcode; explicit productId; accepted connectionVersion/credential fingerprint; expected+accepted mapping fingerprints; safe outcome/reason; createdAt. UNIQUE(business,key), UNIQUE(business,id), validated Membership(business,actor), current native session binding insertion guard, exact inbound four-part FK using existing `wa_message_review_source`, tenant Product FK. Result JSON is bounded safe IDs/fingerprints/reason codes only, no token/challenge/full customer text. Complete result is INSERTed atomically and immutable (UPDATE/DELETE denied).
- `WhatsAppReelAuthorization` / `whatsapp_reel_authorizations`: immutable commandId/business, exact source four-part identity and optional queued outbound four-part identity (outbound is mandatory in this row), plus source/product/mapping/account-generation/reviewer snapshot or exact immutable Command join. Validated Command tenant FK; exact inbound/outbound `(business,id,contact,phone)` FKs reusing0056 unique; UNIQUE(business,outbound), UNIQUE(business,source) for a resume. Trigger requires an explicit original classification, link_and_resume command, exact one canonical queued text message and correct actor/source/product snapshot. No authorization row for link-only/inferred/held results.

The authoritative binding is this immutable outbound FK, never an `auto:*` key or editable JSON flag. Existing0057 exact-test binding remains separate. No extension of0056 operation enum. Historical messages/reviews/receipts are never backfilled into current native authorization. Inbound payload/source classification is preserved; new context references live in the command/queue intent, not a rewritten historical fact.

Native routes (all under `/api/v1/businesses/{business_id}/whatsapp/reel-enquiries`): paginated GET collection; GET `/{inbound_id}` current review/eligibility/product candidates; POST `/{inbound_id}/link` exact frozen command. Body contains `idempotency_key, action, product_id, shortcode, expected_fingerprint, expected_connection_version, confirmed:true`. Recipient, source, reviewer/session and reply text remain server-derived. Responses bind business/inbound/command/key/action/product/result; unknown responses retain original journal. New private namespace `munimjee.v1.reel-command:` requires integrator cleanup registration and current user/business/session scoping.

Remote service signatures:

```python
async def list_enquiries(db, actor, business_id, *, cursor=None, limit=20): ...
async def read_enquiry(db, actor, business_id, inbound_id): ...
async def link_enquiry(db, actor, business_id, inbound_id, command, *, request_authority): ...
async def revalidate_resume(db, account, contact, message) -> None: ...
```

`request_authority` is the real native mutation/session/CSRF callback run before effects and after staged flushes/waits; `link_enquiry` does not commit or call provider HTTP. `revalidate_resume` returnsNone for an ordinary message with no immutable Authorization, returnsNone after successful exact authorized checks, and raisesHTTPException409 for a bound now-ineligible resume. **No bool branch can turn a missing/invalid authorization into permission.** The integrator installs this helper immediately before existing provider.send for bound native resumes, after ordinary current-source/fact generation, with no later asynchronous authority gap; ordinary unrelated messages retain their incumbent checks. Unknown-effect history and source replay checks remain in the same canonical writer. Final helper uses a single fresh scalar across immutable authorization/command/source/outbound/current native session+capability/Account+control/product/current mapping/newer-inbound/manual-attempt/window; no reverse row locks or HTTP. Any fact-regeneration await precedes this final guard.

Base/source dependency remains explicit: remote source-only implementation starts only from the integrator's approved exact0057 composition SHA. Real migration/DB/browser execution waits serial allocation. This contract freezes no broader native inbox, activated comment action mode, load/alert framework, generic CRM merge or international policy.
