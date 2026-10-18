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

Cause spans `frontend/storefront/src/live-app.js:37`, `components.js:19` and shared
`styles.css`: `art()` returns `.empty-state`, whose global `grid-column:1/-1`
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
activity-contract coverage, not a production analytics failure or successful data
collection. No arbitrary network whitelist or activity-success fixture was added.
Fresh source hashes, zero page errors and denied paths are recorded in that report.

## Onboarding comparison in progress

Historical `abab30a` result remains **22 pass / 10 fail**, with exact synthetic-HTTP
privacy/error/focus/role snapshots in the original onboarding report. Those failures
are not automatically called outstanding against newer local fixes. Current
`8ae97c2` comparison has already passed the five old lifecycle/privacy cases:
business-switch 401, invitation-revoke 401, focus role refresh, focus session expiry,
and clearing the prior user's profile-error text. Final same-case comparison and
independent review are being recorded separately before final handoff.

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
