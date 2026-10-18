# V08 queued WhatsApp reconnect and material acceptance

Owned tests/docs were prepared from `a9880c56b6a8bf7b4e20f54837a362e4432aadda`.
Final execution used CENTRAL `85d93906bc0b61b2ffbd21eb55c4b33266f0035a` with the
remote-owned material repair composed. No runtime/sender/queue/schema edit was
made by this work. **105 focused checks pass (57 actual migrated DB cases and
48 projection/pure cases), plus5 mounted actual-main journeys.** The owned three
signed-ingress cases pass on real0056. Earlier preparation notes below describe
the historical pending boundary; final executed evidence is authoritative.

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


## Final bounded execution and verdict

Final CENTRAL source `85d93906bc0b61b2ffbd21eb55c4b33266f0035a` contains the remote
material vocabulary repair plus owned harness7639453. It is the tested runtime;
this test-only branch does not import/reimplement that production change.

The exact six-module selection passes105/0skip/0fail, runner0 in62.70seconds:
three signed actual-main/PG reconnect/material cases,54 existing actual-PG SKU
cases, and48 remote projection/pure regressions. PostgreSQL16.15 reports actual
`0056_v1_comment_operator`; all512 source/harness pre/post hashes match.

The mandatory reconnect case calls no sender while both account flags are paused
and stays terminal after later enable. The separate explicit-current-owner enable
before first dispatch sends fresh approved price/stock once using replacement
credentials. The unsupported material+price question queues and sends only the
conservative handoff once under duplicate ingress/drain. Incumbent unknown-send
regression attempts its synthetic send once and preserves unknown without retry.
These observations follow the existing contract; no blanket generation-cancellation
policy was added. Native Control metadata remains observedTrue after reconnect;
both effective Account flags areFalse and actual dispatch is withheld.

The unchanged existing mounted SKU runner passes5/5 on the same actual-main/0056
source: reviewed native SKU activation/current price-stock update, mobile untracked
stock and duplicate MID, unpublished withholding, invalid signature withholding,
and buffered conflicting products. No browser errors/external requests occurred.
All1823 tracked file hashes match after the approved wrapper restores the three
historical artifacts byte-for-byte. Both screenshot steps ran; regenerated PNGs
were byte-identical to prior captures, disclosed in capture-attribution.json. The
runner's printed PG0052 label is stale; direct queried0056 is recorded separately,
without rewriting historical output.

Raw first interrupted58pass/2fixture-error output and teardown warnings remain
separate from the final acceptance. `artifacts/v1/wa-reconnect-queue/verification.json`
contains source attribution/counts/hashes and zero raw-JWT scan matches. Fake
verification/send methods are deliberately exercised; this is not a claim of zero
synthetic method attempts. No live provider/customer send, external permission,
real recipient consent or production delivery is proved. No browser camera gate
or0057 flow is included. Parcel_w6/8156 were explicitly released, with no remaining
DB sessions/listener. Bounded V08 acceptance is clear; broader automation readiness
still depends on its separately recorded provider and remaining product gates.
