# Independent experience QA handoff

Application snapshots are separate: original integration `abab30a`, and fetched
onboarding/activity follow-up `8ae97c2d57c0efda5a03a41a469bf9447739ee72`
(runtime `52fdda8`). The coordinator branch preserves the original application
source and carries independently reviewed tests plus evidence for both snapshots.
No production, schema, migration, dependency or existing safety-harness edits were
made. Local `789db95` /0056 and later 0057 work are reported context, not acceptance
from these runs. All three reused named workers remained GPT-6.1 Sol/high.

## Frontend repair evidence ready

Fresh `8ae97c2` storefront result: **69 passing / 6 failing UI checks**, the same
P2 missing-photo bag defect in editorial, catalogue and video at both **320px and
390px**. The six assertions remain red and the runner exits 1. Title and price text
paint over each other even when page/dialog scroll widths fit the viewport.

Exact worker checkpoints on `codex/v1-storefront-followup-independent-qa`:

- Original QA `faec01614c27578afd38bef750b9dc2205ee7c98` (on newer source cherry-pick
  `52cb713`): actual SSR exporter, actual module browser runner and original evidence.
- `51f24801a5beb7f39ee57f8739301c633b056272`: trusted owned output option only;
  all 75 scenario names and assertions stay unchanged.
- `12c85209883825892e874dab7e68ddf3c2cd3a91`: fresh comparison docs/evidence only.
  This evidence commit is composed centrally as `26976bb` without importing newer
  production source into the baseline coordinator branch.

On an isolated checkout of **8ae97c2**, apply only the original QA and output-option
commits to reproduce. Do not cherry-pick an entire branch's production ancestry
into an unrelated integration state. Use the exact cached-runtime commands in
`docs/v1-independent-storefront-followup-comparison.md`; regenerate SSR first.

Repro: published product with `photo_urls=[]`, name `Independent occasion dress`,
available M variant; open product, select M, add to bag at 320 or 390 CSS pixels.
Inspect `.cart-line h3` versus `.cart-line > strong` in the named `Your bag` dialog.
The test uses DOM Range painted text rectangles and fails when horizontal and
vertical intersections both exceed 0.5px. Representative measured horizontal
overlap is 19.515625px; it is not inferred from container geometry alone.

Cause spans `renderBag` in `frontend/storefront/src/live-app.js`, `art()` in
`components.js` and shared `styles.css`: `art()` returns `.empty-state`, whose global `grid-column:1/-1`
spans the cart row. Details then fall into the mobile cart's 65px first column;
the title intrudes into price text. The cart block, component and relevant CSS
remain unchanged in the newer source, and the fresh run confirms the actual effect.
The repair owner should contain the image fallback within the intended cart cell
and preserve readable text/price layout without weakening the six assertions.
This QA task does not own that runtime repair.

Screenshots and exact assertions are under
`artifacts/v1/independent-storefront-experience/comparison-8ae97c2/`, especially
`catalogue-320-missing-photo-overlap.png` and `video-390-missing-photo-overlap.png`.
See `result.json` for all six text-rectangle observations and
`backend/tests/independent_storefront_experience_qa.mjs` for scenario assertions.
The coordinator and security peer independently viewed representative screenshots.

**Separate boundary:** 153 same-origin POST attempts to the new activity-context
endpoint were denied as unhandled. No request was continued/fetched. This is missing
activity-contract coverage in this shopping harness, not a production analytics failure or successful data
collection. No arbitrary network whitelist or activity-success fixture was added.
Fresh source hashes, zero page errors and denied paths are recorded in that report.

## Onboarding comparison

Historical `abab30a` result remains **22 pass / 10 fail**, with exact synthetic-HTTP
privacy/error/focus/role snapshots in the original onboarding report. Fresh
`8ae97c2` comparison passes the five old lifecycle/privacy cases:
business-switch 401, invitation-revoke 401, focus role refresh, focus session expiry,
and clearing the prior user's profile-error text. The same 32 cases finish with
**27 pass / 5 fail**, zero unexpected traffic and zero page errors. The remaining
failures are all P2 UI findings on this exact source:

| Case ID | Remaining observation | Source owner target |
| --- | --- | --- |
| `keyboard-transition` | Keyboard signup leaves focus at BODY after the access view disappears. | Native workspace transition focus |
| `logout-focus` | Keyboard sign-out leaves focus at BODY rather than the visible sign-in context. | Terminal identity transition focus |
| `contrast-focus` | Author keyboard outline is about 2.3955:1 against the adjacent white panel. | Shared native focus styling; representative scoped check only |
| `startup-error` | Initial session 503 hides both panels with no visible retry/sign-in control. | Initial native load recovery |
| `long-business-name` | Valid unbroken 160-character name expands a 360px page to 3062px. | Native heading/picker reflow |

Use `codex/v1-onboarding-followup-independent-qa` on application source `8ae97c2`.
Apply only QA originals `d92406e` and `a3a3d66`, then harness-only adaptations
`e0d819d18b185bfcf4a2e10466e2c8d6e3aa0c86` and
`a7282ed267d09b4f28b3b22dba24495f59a834b7`. The adaptations issue matching synthetic
CSRF cookies and supply fake rows required by the current six-step readiness
formatter; they do not bypass lifecycle guards or prove backend readiness.
Baseline snapshots remain intact, with new comparison evidence stored separately.
Evidence-only original `9642527196f2e80b0a0effd69678949be34074af` is composed centrally
as `5ccb729`; the baseline exporter remains unchanged here. Exact commands, raw
results, preserved diagnostics and current-source screenshots are in
`docs/v1-independent-onboarding-followup-comparison.md` and
`artifacts/v1/independent-onboarding-experience/comparison-8ae97c2/`.

An intermediate **26/6 diagnostic** is retained as harness calibration. Its extra
lost-response failure required an obsolete conflict-text message. The stronger
reviewed check instead proves the actual frontend receives a fresh complete profile
after one synthetic committed write, rejects the stale retry (both PUTs used version
3; retry returns 409), renders version-4 facts exactly, and produces no extra PUT on
manual reload. A new saved-status acknowledgement occurs after the fresh response.
This is valid self-healing recovery, not an outstanding source defect. Neither
synthetic commit bookkeeping nor an injected 401 is actual database or backend
authorization proof. Privacy findings from the old source remain historical.

## Independent review and integration

All three workers finished and pushed their owned changes. Security review originals
`44790f8`, `a5b4e94` and final `8870079b76a86d16faa07f23833e871e9031d203` are
composed centrally; the final review is `60efee0`. It independently checks exact
Git blobs, runner/exporter/fixture hashes, preserved baseline files, unchanged case
identities and the lost-response state/effect proof. Representative screenshots
were independently inspected. No safety or assertion-fidelity blocker remains
within the stated synthetic scope. Product assertions remain red.

Use `codex/v1-independent-experience-qa` for the aggregate tests/docs/evidence,
`codex/v1-storefront-followup-independent-qa` for the newer-source storefront runner,
and `codex/v1-onboarding-followup-independent-qa` for the newer-source onboarding
runner. The latter two branches start on 8ae97c2; apply only listed QA commits into
the local integration, keeping production ownership and migration ordering local.
Regenerate fixtures and rerun on every later candidate: stored fixture hashes fail
closed when producer source changes. These reports do not certify a moving branch.

`artifacts/v1/independent-experience-coordination/final-verification.json` records
the source-separated counts, fixed/remaining IDs, exact originals and effects.
All 264 baseline application/plan hashes remain unchanged; 20 newer storefront
hashes plus native/formatter hashes match exact 8ae97c2 Git blobs. Review details
are in `artifacts/v1/independent-offline-recovery/peer-review.json`.

## Offline and baseline verification

The fixed lab envelope is 24 synthetic imports across two tenants, four generated
fetch callers, eight active-lease redeliveries, four interruptions and a logical
61-second lease advance, drain batches 20/4/0, plus a 12-caller transport burst with
four admission slots. All three new scenarios pass, including retained admission
after cancellation and successful recovery. Actual service/query/state functions
run over explicitly synthetic persistence and Future transports; no DB/Redis or
real process restart, rollback, throughput or production race proof follows.
Every scenario has a five-second safety bound. Real pilot traffic envelope is
MISSING; timing is informational, not a production SLA.

The original composed backend passes **1,237 tests / 724 skips**, zero failures.
Skips: 721 unallocated DB, two unallocated Redis, one absent LLM cassette. The
baseline Node contracts pass **71/71**. These counts overlap focused checks and
do not certify 8ae97c2, local 0056/0057, or their migrated runtime. The storefront
coordinator rerun independently reproduces 69/6 on the original snapshot.

Physical phones/touch keyboards, screen readers, full contrast/WCAG assessment,
real media/CDN behavior, actual mounted DB/Redis recovery, live providers, soak,
current complete integration and full V1 acceptance remain open. No real credential,
customer send, charge, deployment, DNS/billing action, hosted retry, Docker operation
or ambient 4317 service access occurred.
