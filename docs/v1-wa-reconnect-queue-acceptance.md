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
