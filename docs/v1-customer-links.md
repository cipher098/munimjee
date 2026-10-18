# Customer account control and consent

This default-off slice verifies control of one existing Instagram account and one
existing WhatsApp account within a business, plus explicit consent to link those
records. It does not verify a legal person, create marketing consent, move any
historic message/order, grant payment access, or combine private bot context.
Names, phone numbers and profile labels are never matching evidence.

A current native owner/manager with `automation.manage` selects explicit inbox
record UUIDs and reviews the limited scope. A random UUID challenge derives a
256-bit HMAC secret under the application secret; only its digest is stored.
Creation/exact creator replay can show the secret in a no-store mutation response.
No GET, audit, log, public response or browser recovery journal stores the secret.
The exact whole command is `LINK <43-char URL-safe secret> I CONSENT`.
The customer must independently send it from both selected endpoints within ten
minutes. Signed provider timestamps must be after issuance at second precision,
no more than sixty seconds ahead of receipt, within the challenge expiry, and
received before expiry. Echoes, attachments, wrong sender/account, stale account
configuration, malformed, expired and replayed events cannot establish a proof.

`ingest_instagram_command(db,event)` is an internal hook immediately after IG
message-shape validation, before the echo/transcript or ordinary ingress path.
`ingest_whatsapp_command(db,account,event,provider_at)` runs after trusted provider
account and message identity/time validation, before contact/context/transcript
or rule handling. The existing signed webhooks remain the authority boundary;
these helpers are not browser endpoints. True means reserved token-shaped traffic
was withheld from all ordinary processing, even when the feature is disabled or
the proof is invalid. They never send, log or commit. IG caller commits before
ack; WA outer webhook already commits. The ledger records only provider message,
channel/account/subject identifiers and timestamps. It has tenant/event and
challenge/side uniqueness and immutable evidence triggers.

After two proofs, the native operator explicitly finalizes. Exact command receipts
precede expiry/state checks on retry, bind actor/body/operation/tenant, and are
append-only. Current native session/CSRF and capability are rechecked after waits
and before caller commit. Current connected account fingerprints include credential
and connection-generation facts; disconnect/reconnect invalidates pending proofs
and verified context lookup. Sending may remain paused throughout this flow.
Partial unique indexes allow one active association per provider endpoint and per
source record. Concurrent conflicting proof requests cannot merge two customers.
Unlink is explicit, audited and irreversible for that association; old canonical
records, proofs, orders, messages and consent remain. A new link needs new proofs.

The sole automation seam `verified_customer_id(...)` returns a current opaque UUID
or None. It never returns history, facts, consent, another channel's identifiers or
permissions. No automatic sender, finalizer or historic identity backfill exists.

## Integration ownership

Actual migration `0052_v1_customer_links` follows the real support predecessor
`0051_v1_support_grants` (dependency159c525). It adds five tables and the additive
`conversations(id,seller_id)` tenant key; no data backfill. Main/model/router,
package/static allowlist, config, native navigation and two trusted webhook hooks
are integrator-owned. Config dependencyea1a307 adds
`V1_CUSTOMER_LINKS_ENABLED=False`. New assets are customer_links.html/js/css.
Private journal namespace is `munimjee.v1.customer-link-command:`; it is scoped to
native user/business/CSRF-session fingerprint, contains only frozen command/body
and human summary, persists before POST, and never automatically replays.
Unclassified/transport results retain the exact command. Only server-typed
`customer_link_not_accepted` after receipt lookup and before mutation permits a
new explicit decision. Native identity/401 and lost inbox access clear private DOM.

## Evidence boundary

Final source a7e6ce7 passes47backend checks (14pure,17actualPG service/schema,
16mounted-native HTTP) and14real Chromium journeys on actual app.main/0052.
Backend source65f7a2c is byte-identical at final. The mounted server uses synthetic
configured-account/inbox fixtures plus real signed webhook handlers; no live provider
or customer proof is claimed. Evidence, source hashes, privacy policy, capture scope,
initial refresh-race failure and final independent SHIP verdict are recorded in
`artifacts/v1/customer-links/verification.md` and manifest.json. The real Hide consent
command control clears its value before captures; no raw secret is committed.
Port8156 and the borrowed dependency symlink are released. Central full/runtime
composition and authorized live consent canary remain separate gates. No deployment,
provider send, customer data or production service was used.
