# Native single-enquiry UI source checkpoint

Exact0057base `6ff11c3d073c5617e18cc439e04809db6dd760ad`; frozen contract
`f800846`. The source-only design was committed first at `ee8060c` and reviewed
independently before implementation. Review corrected its illustrative prechecked
confirmation; both the design and runtime now start unchecked. No browser/render
execution is allocated, so the HTML design is not a screenshot or paint proof.

The fourth Unlinked reels tab reviews exactly one trusted inbound UUID. Original
classification/reference, contact/account hints and server eligibility stay
visible. Product selection never defaults; changing product resets confirmation.
Link only and one eligible reply remain distinct. Inferred0056 follow-up closures
retain their no-send API and command semantics. Current facts, queue permission,
provider acceptance and delivery are not conflated.

`munimjee.v1.reel-command:` stores the exact command/body/key/request hash under
current user/business/CSRF-session digest. It is separate from the old comment
journal, while either pending action blocks preparing another. Recovery verifies
format, bounded size/age, complete envelope/session binding and both hashes.
Unrelated200 or unclassified409/422 keeps the frozen action. Exact immutable safe
receipt fields bind business/inbound/key/action/product/request hash before the
journal is cleared. No automatic retry runs on load. Current session/role checks
surround transport and physically fence private DOM/forms and owned journal on
identity/review permission loss. Selection/list epochs discard stale responses.

## Integrator-owned seams

- Register router/models/0058 and install final helper before canonical provider
  dispatch; source-only UI is not connected-main acceptance.
- Register the new journal prefix in global cleanup. An old page clears only its
  owned key; it must not delete a replacement session's key.
- The incumbent V1 client currently exposes error code/status but drops structured
  error detail. Preserve only the bounded typed pre-mutation rejection fields as
  `error.detail` for this new endpoint/code, or retain uncertainty conservatively.
  Root validation requires exact business/inbound/key/hash plus accepted=false;
  code/status alone cannot release the frozen link intent. Do not expose arbitrary
  validation bodies or credentials while adding this integration seam.
- Local actual-main/browser allocation must verify mobile wrapping, focus, native
  CSRF, identity replacement, reload recovery and receipt/dispatch outcomes.

Node syntax checks pass. Independent finite Node/source/pure checks and final
source review remain pending. No DB/browser/provider/model/server/install or live
send operation ran in this UI lane.
