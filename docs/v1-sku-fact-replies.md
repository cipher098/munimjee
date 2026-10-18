# Activated SKU facts in channel replies

Approved bounded contract, frozen with the integrator on 18 October 2026. Base 7a5974f plus the
accepted customer privacy dependency a7e6ce7; separate worktree/branch. No DDL,
import ownership change, new sender or live provider canary is included.

## Authority and permitted behavior

Default-off `V1_SKU_FACT_REPLIES_ENABLED` is an additional rollout gate. Existing
channel connection/automation, conversation window, takeover/pause, manual action,
payment hold, quarantine, contact opt-out/consent and once-only source/outbox rules
remain mandatory. The flag does not authorize a message by itself.

Read only an active tenant's published storefront, activated+active product,
reviewed catalogue mapping and active authoritative SKUs. A product that was
activated never falls back to legacy price/stock. Public facts are product name,
SKU option labels, current public price/currency and recorded stock availability.
Exclude legacy floor/cost/negotiation state, descriptions, credentials, payment
facts, private notes, joined customer histories and consent data from the facts DTO.

The first slice returns deterministic price/options/availability replies for an
explicit focused/replied-to product or one exact linked reel. It does not select a
variant, negotiate, reserve stock, create/update an order, request payment, mutate
transactional conversation-product state or expand an LLM prompt. Unknown/ambiguous
product references, title/vision guesses, transactional/discount/refund requests and excessive option lists require truthful clarification or handoff.
Untracked availability is explicitly unknown, while other approved facts may be stated. Untracked stock never means in stock. Multiple options remain separate
facts; a cheapest/default SKU is not silently chosen.

## Freshness and provenance

At each existing send boundary, use a fresh scalar projection of current tenant,
publication, activation, mapping and SKU facts. Read a coherent snapshot, immediately
render it and describe recorded availability as an observation, not a reservation
or a delivery promise. Stock may change after the read. Do not hold new SKU,
Storefront or broad catalogue locks across provider HTTP. Do not wait for catalogue
locks while WA Account/Contact/Message locks are held. Existing legacy routing
guards retain their own authority contract; a fail-fast shared guard seam is owned
by the integrator if required for activation crossover.

The internal DTO binds business/product/SKU IDs, option facts, mapping revision,
observation time and a public fact hash. Source references are trusted explicit
product context or a freshly revalidated exact reel mapping. Resolve all exact
matching IDs in scalar queries; ambiguity stays a handoff. No broad ORM catalogue
load, first-match inference or stale queued response becomes authority.

Instagram continues through the durable ingress thread/MID ledger and existing
send-and-tag writer. Only the read-only reply path supplies SKU fact provenance;
legacy state/payment branches remain guarded. New text still records once and
unknown send effects retain the current quarantine behavior. Exact reel context
must branch before legacy photo/price/state actions; activated vision/title guesses
remain a handoff.

All explicit product references in one buffered turn must agree before media or
state processing. Conflicting reels, reply-to products or unknown media with SKU
context withhold; neither the first nor the last reference selects a product.
Every frozen exact reel is revalidated in the final observation statement, and
all processing receipt timestamps/account bindings must still be current.
Eligibility freezes once before cycle handling. Activation, rollout or legacy
vision/title identification during later waits cannot admit new fact authority
mid-turn; it withholds through the existing handoff/rollback instead.

The adapter takes no explicit SKU/Storefront/catalogue sweep locks. Incumbent
focus persistence is retained: changing `Conversation.product_id` can hold an
incidental single-Product foreign-key KEY SHARE lock through the send, so a
Product FOR UPDATE writer can wait. This slice does not claim every catalogue
writer is unblocked. SKU and Storefront writer progress during an exact-reel send
is tested; changing sender/history transaction semantics is outside this slice.

WhatsApp continues through `auto:reel:<provider-mid>` and the existing durable
outbox. Its stored payload records the request/reference context. In
`workers.whatsapp.deliver_one`, the current `auto:reel:` regeneration call to
`service.reel_catalogue_reply` obtains and renders current SKU facts for activated
products before the legacy guard branch. These are text messages: after that
helper, synchronous window/contact checks precede the existing provider.send.
Every delivery attempt regenerates; queued old text is never accepted as current.
No template/parcel lifecycle or second outbox writer is introduced.

## Proposed ownership

Worker: new read-fact adapter/DTO/formatter/tests/docs and narrow IG conversation,
explicit-context resolution and WA context regeneration changes under this frozen contract.
Integrator: rollout config, shared registration/guard seams and integrated gates.
No import/catalogue writer, checkout/payment schema or public storefront UI edits.

## Required evidence and limits

The request recognizer deliberately accepts a small English/Hinglish factual
vocabulary. Other phrasing, a selected variant, numbers, transactional requests
and additional unknown URLs use the human-confirmation response. A bare exact
reel may request the same public observation. Stored reel mappings must be full
allowlisted Instagram URLs or exact string media IDs; numeric JSON values and
multiple references are not coerced into an identity. Case-insensitive scheme/
host comparison preserves case-sensitive shortcodes and all matching products.

Final IG emission also requires a current durable processing receipt within the
provider window. This slice does not add proactive SKU nudges/resume. Existing
agreed/payment cycles conservatively withhold rather than restart price discovery.
Feature-wait, remembered variant and negotiation values remain unchanged. Only
the conversation focus/history and existing message/outbox outcome are updated.

Use the exclusively allocated P01 lane and actual current migration chain. Test
foreign/inactive/draft/unpublished/nonactivated/malformed or inactive-SKU states,
unknown stock, multiple prices/options and source ambiguity. Prove no private
legacy facts enter output, no variant/order/reservation/payment mutation, current
projection after queued stock/price/publication changes, and existing pause/hold/
opt-out/window gates. Exercise activation/stock races without catalogue lock waits
or a second send. Provider errors must retain existing unknown-effect behavior.

Mounted native catalogue update plus synthetic signed channel delivery can prove
application composition and output facts. Synthetic provider transport is not live
Meta/customer delivery, consent or permission acceptance. Approved live canary,
production activation/deployment and any broader conversation policy stay pending.

## Existing shared-guard follow-up

The legacy WA guard can hold Account and wait for Product SHARE while checkout
holds Product UPDATE then requests Account for checkout consent/update. This
pre-existing activation-crossover lock inversion is an explicit integrator-owned
NOWAIT/withhold follow-up. The new activated-SKU read path adds no catalogue row
locks and does not claim the unrelated legacy contention case is solved.
