# Prepared V08 queued WhatsApp reconnect acceptance

Frozen approved source `a9880c56b6a8bf7b4e20f54837a362e4432aadda`; tests/docs only.
No runtime/sender/queue/schema edit. **2 tests collect; neither has run against a
DB yet.** The integrator's full producer gate owns the serial DB/browser slot.

Existing activated-SKU tests cover send-time fresh prices/stock and unknown effects,
plus window/opt-out/automation/reel/publication/business/mapping/inferred-context
withholding. They do not exercise actual same-phone credential replacement while
an activated reply is queued. This focused addition uses the existing real P01
SKU fixture, production `app.main`, signed WhatsApp ingress to create the actual
canonical outbox intent, and native-session/CSRF channel connect and enable APIs.
Verification/send adapters are fake; no real provider or network is authorized.

Mandatory case: an authorized same-phone reconnect advances generation and
atomically pauses both account flags. Attempting the old queued action while
paused must call no sender and leave its truthful terminal failure/no provider
receipt. A later current-owner enable must not resurrect that failed action or
create another outbox message.

Separate characterization: if the current owner explicitly enables the current
connection **before first dispatch**, the frozen SKU contract requires current
facts/current account checks, not stale queued text. The second prepared case
observes that boundary, edits authoritative price/stock, and requires once-only
current facts if that explicit enable authorizes the queued action. It is not an
invented hard generation policy or proof that reconnect automatically rebinds an
action. Root confirmed the existing contract: the requirement concerns implicit reconnect
authorization, not a blanket cancellation rule after deliberate current-owner
re-enable. Compliant fresh-fact regeneration is not a defect. The integrator
source-reviewed both prepared cases; neither is actual migrated evidence yet.

No support, legacy impersonation, phone/name matching, consent/window mutation,
order or stock reservation is added by these tests. Synthetic signup-session
fixtures and transports are not actual customer or provider consent evidence.
Actual execution requires an explicit released `parcel_w6` P01 allocation; collected
names are not fake-persistence acceptance or a migrated pass.

One additional prepared actual-PG case closes the remote material vocabulary
repair's wiring gap: signed actual ingress with an exact activated reel plus
“material and price?” must queue the conservative human handoff, retain one action
under duplicate delivery, and regenerate the same handoff at the existing worker
send boundary. A synthetic provider may be attempted once; no price/private facts
may replace the unsupported-material answer. This is not a zero-send case.

The remote owned runtime d3aacd9 (handoff a0d46df) is a required dependency before
execution; it is not implemented or imported into production source by this test
branch. **All3 tests collect only; no actual DB pass is claimed.** The source base
and collection are separate from the future composed runtime under test. Serial
lane permission remains withheld during the full producer gate.


First actual selection at central4b24bbba was stopped after two fixture errors
(and58 completed passes): the prepared fixture required the separate Control
automation flag to be false. Incumbent reconnect pauses both effective Account
flags and advances generation/credential, while leaving the Control flag true.
Coordinator confirmed this is a metadata inconsistency, not current send
authority; sender/effective views require the Account flags. The corrected
fixture keeps both mandatory Account pause assertions and records the Control
value as an observation instead. No runtime or generation policy changed.

The stopped run, KeyboardInterrupt/reset teardown warnings and all512 stable
source hashes are preserved separately; it is not a complete acceptance pass.
The final frozen rerun must prove actual paused dispatch0 and deliberate owner
re-enable/fresh facts independently.
