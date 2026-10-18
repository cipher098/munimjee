# A13 early source-only integration checkpoint

Base `6ff11c3d073c5617e18cc439e04809db6dd760ad` is the supplied real0057
composition. New migration is exactly `0058_v1_reel_operator` →
`0057_v1_whatsapp_self_service`. The approved contract including24f746f hashes
`f0e3986b92a2a790b5e70e790c4d6dcc55c0c6a1372b513c12b9af01c9a9c46c`.
This is a coherent early review candidate, **not accepted source/unit/DB proof**.
Finite independent QA and final review are still underway.

Owner source: `34f2125` + `a2d4109` + `9f7a2e8`, composed here as
`1ae794e`, `da90309`, `21cddc4`. Only new API/schema/service/model/0058 files
are authored. UI uses the existing four comment-operator assets. No shared
registry/router install, canonical worker, trusted ingress, package/navigation,
global cleanup, catalogue, credential or financial file was edited.

## Required local installation

1. Register `app.models.whatsapp_reel_operator` beside0057 models and include
   `app.api.v1.whatsapp_reel_operator.router` in the actual main application.
   Install/package the existing changed UI assets through incumbent packaging.
2. Install `await revalidate_resume(db, account, contact, message)`
   **unconditionally** as the final await immediately before the incumbent
   `provider.send`. Do not branch on its None return or a payload/key assertion.
   The helper performs no commits, provider calls or new row locks.
3. Preserve0057 final authority too. For a message with no new immutable reel
   authorization, the helper invokes incumbent `exact_test_authority` as its own
   last internal await and immediately returnsNone, ignoring its auth object.
   A bound reel instead regenerates facts/flushes before its final fresh0058
   scalar and returnsNone or raises409. Do not add another async lookup or guard
   after either successful final path. Ordinary messages retain all incumbent
   checks; no blanket generation cancellation is added to ordinary auto:reel.
4. Register `munimjee.v1.reel-command:` in global native private-journal cleanup
   alongside the existing prefixes. No generic raw error-detail forwarding is
   requested: V1.api's bounded status/code is sufficient. The page captures the
   actual POST route and canonical body locally, and accepts only the exact
   allowlisted pre-mutation409 from that transport request. A session error,
   unrelated200, unclassified409/422 or different request retains uncertainty.
5. Allocate actual0058 migration/native/DB/browser acceptance locally. Remote
   tests may author DB scenarios but must not run them. Synthetic signed ingress
   and synthetic provider belong to that separately allocated actual-main lane.

## Fixed wire shapes

Routes: `/api/v1/businesses/{business_id}/whatsapp/reel-enquiries`, GET collection,
GET `/{inbound_id}`, POST `/{inbound_id}/link`. The POST has exactly seven fields:
idempotency_key/action/product_id/shortcode/expected_fingerprint/
expected_connection_version/confirmed=true. No browser source, text, recipient or
reviewer authority is accepted. Request SHA256 is canonical JSON of
`{business_id,inbound_id,body}`, sorted compact keys, ensure_ascii=true.

Collection is `{items,next_cursor,can_manage}`. Detail binds business/inbound,
message/time/contact/account hints, original source classification+code+URL,
connection version/fingerprint, bounded matches/products and eligibility.
Unknown/multiple references have nullable code/URL and cannot authorize resume;
recent_message remains inferred and only links. Product mapping can inform future
messages; no other historical source is rewritten, closed or resumed.

Receipt fields: business_id/inbound_id/command_id/idempotency_key/action/
product_id/request_hash/result/replayed. Result is exactly mapping=saved,
resume=queued|held|not_requested, reason, outbound_id and mapping_fingerprint.
Queued has exact outbound UUID+null reason; held has null outbound+stable reason;
link-only has null outbound+resume_not_requested. Complete immutable queued
receipts require the exact immutable outbound four-part-FK authorization at commit.

Typed rejection DTO remains server-side bounded fields:
`{code:'reel_operator_pre_mutation_rejection',business_id,inbound_id,
idempotency_key,request_hash,accepted:false,reason}`. The service emits this only
after receipt lookup and before effects. The browser uses the allowlisted code
plus its locally captured exact request, without reading discarded raw detail.

## Evidence and known boundaries

Source compilation/Node syntax and static review are the only completed checks
at this early checkpoint. Independent46-case packet is being authored;20 are
actual-DB source scenarios only. The source-only design is
`artifacts/v1/reel-operator-coordination/design.html`; it has no browser paint
evidence. Actual concurrency/NOWAIT usability, trigger/constraint behavior,
source/queue preservation, shared sender install, native CSRF and mounted browser
privacy/recovery remain unverified. No real Meta, recipient, send or deployment
permission follows from this checkpoint.
