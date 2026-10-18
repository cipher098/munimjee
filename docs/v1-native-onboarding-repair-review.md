# Independent native onboarding UI repair review

Application base: `8ae97c2d57c0efda5a03a41a469bf9447739ee72` (runtime delta
`52fdda8`). Review date: 18 October 2026. Runtime ownership transfer is pending.
This lane writes only this review and `artifacts/v1/native-onboarding-repair-review/`.
Application and test source remain read-only. No patch has been applied by this
reviewer, and no server, DB, provider, credential, user browser or production
operation has been used.

## Initial disposition and file contract

The proposed `v1_app.js` / `v1_app.css` boundary is sufficient; no third runtime
file is needed for the five bounded repairs. This is a source-only design review,
not approval of an unseen patch or a passing product acceptance report. The
implementation owner must receive explicit transfer before runtime edits.

Preserve existing IDs, `[hidden]`, textContent rendering, ordinary tab order,
current tenant/role authorization, `checkedSession`, `pathAccess`, CSRF matching,
`fenceGeneration`, `businessLoad`, sequence/latestSession protection and terminal
identity cleanup. No HTML/client/global commerce CSS change, auth-policy change,
new identity route, channel/activity change or storefront/cart repair is included.

## Incumbent guidance and primary accessibility scope

Read `.impeccable/review/packet.md`, `documentation.md`, `finish-review.md`.
Their incumbent Operate guidance preserves muted green, system type, plain recovery
copy and honest uncertainty. The historical channel-operator verdict is not this
repair's acceptance. The referenced craft-floor belongs to another host and is
unavailable. A fresh search of supplied/local skill roots found no applicable
Impeccable/accessibility `SKILL.md`; no missing skill was claimed as executed.

Primary W3C Understanding references were read on this date:

- [Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html):
  keyboard focus needs a visible indication. Keyboard modality and actual computed
  styles are relevant evidence; pointer focus alone is insufficient for the proposed
  author `:focus-visible` repair.
- [Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html):
  evaluate the author-supplied focus-state cue against its actual adjacent color.
  The scoped criterion is at least 3:1 without rounding up. The user-agent-only
  appearance exception does not describe the incumbent author solid 3px outline.
  A representative passing input is not proof for every component/state/palette.
- [Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html): retain information
  and functionality when content adapts to a narrow viewport. Wrapping literal
  business text is appropriate; hiding page overflow or silently truncating identity
  text is not a substitute. Existing 360px checks remain; no complete zoom/reflow
  certification is inferred from those few fixtures.
- [Focus Order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html):
  focus order should support meaningful operation. Moving focus after an explicit
  context transition is the selected repair design, not a claim that W3C mandates
  this particular heading or control. A programmatically focused heading can use
  `tabindex=-1` without becoming another ordinary tab stop.

These are informative explanations used to scope the review. No screen-reader,
physical-device, full accessibility or WCAG conformance certification is made.

## Lifecycle review criteria

**Interactive entry:** focus only after a confirmed explicit signup/login/invitation
transition has finished and its current workspace is visible. Any deferred focus
must confirm the same generation and current view. Do not attach unconditional
focus to `workspace`, `loadBusiness`, `access` or `endWorkspace`: passive role/session
checks and expired-authority cleanup invoke those paths too. Avoid focusing a hidden,
disabled, disconnected or obsolete node; preserve current user's passive focus.

**Explicit logout:** keep the existing API confirmation and terminal cleanup. Only
then focus the current visible sign-in context. A denied or stale logout must not
pretend success. Involuntary 401/passive identity checks need their existing privacy
fences without adding focus theft as a side effect of a generic helper.

**Startup retry:** append a named native keyboard-operable button alongside the
existing announced startup error only when normal panels are unavailable. Explicit
page reload is sufficient: it reruns existing startup/current-session/cookie checks.
It must not restore cached identity, set cookies, invent success, automatically
loop requests, hide the original error or continue displaying private workspace
on denial. Existing successful/invitation/session paths should not acquire a
spurious retry control.

## Shared stylesheet impact criteria

Only three HTML files load `v1_app.css`: native `v1_app.html`,
`parcel_tracking.html`, and `customer_links.html`. The latter two do not load
`v1_app.js`. A class/attribute marker set by the native JS can therefore scope the
new rules without HTML edits or changing sibling page styles.

Every added CSS rule must be under that marker, including media-query descendants.
Keep shared `commerce.css` and all pre-existing rules unchanged. Override only the
native author outline color using incumbent dark green; retain 3px width and 3px
offset. Validate against white and paper adjacent surfaces, not just a nominal
palette token. Long heading/picker flex items need `min-width:0`/bounded widths and
wrapping or equivalent legible containment. Keep the full 160-character literal
name and all picker options available; do not conceal overflow to make a metric green.

## Pending independent verification

Await the exact unapplied patch, then review its two-file content, scope and
lifecycle guards. Record proposed-content hashes without modifying runtime files.
After root's explicit transfer and committed implementation, compare actual runtime
hashes, review all 32 existing assertions plus bounded retry/focus additions,
independently inspect exact screenshots and verify shared-page style isolation.
Actual mounted/migrated sessions, physical phones, assistive technology and full V1
acceptance remain separate gates. Local eeb94a1/0056 is context, not this source.

## Committed runtime source review after transfer

Root explicitly confirmed the two-file ownership transfer before runtime writes.
Implementation original `c85e480` plus one-line label followup
`8e62ea770729d04bc0982aadf64dadae41973cb9` were reviewed via read-only Git
objects. This reviewer did not apply a patch or modify product/test source. No
third file was needed and no static blocker was found in the committed scope.

Only `v1_app.js` and `v1_app.css` differ from `8ae97c2`. All twelve protected
helper bodies (including endWorkspace, applyAuthority, checkedSession, pathAccess,
api, access, busy, loadBusiness, workspace and recheck) remain byte-identical.
Existing CSS bytes are unchanged; all six appended rules require
`body.native-onboarding-page`. Native JS alone adds that marker. Shared parcel/
customer HTML and JS, global commerce CSS, native HTML and shared client are
byte-identical to base. Exact hashes are in `committed-source-review.json`.

A concrete pre-commit review finding was resolved: `api()` returns a confirmed
logout response before its usual post-response generation check. The explicit
logout handler now captures generation before awaiting, rejects changed generation
before terminal cleanup, then invokes focus only for the current resulting sign-in
view. This is a narrow UI cleanup/focus fence, not an auth-policy change or proof
about real Set-Cookie races. Independent QA should keep the mock-callback limit.

New focus calls occur only after explicit access-form completion and confirmed
logout. The helper checks current generation/businessLoad, current visible view,
visible/focused document and whether focus already lies in that view. Programmatic
headings receive tabindex=-1; passive helpers acquire no new focus calls. The
manual reload button preserves the announced error and uses only location.reload.
Its final label, “Reload and try again”, also preserves the original recovery
assertion without editing that assertion. CSS preserves 3px outline/offset, scopes
dark green to the native page, wraps literal business headings and permits flex/
picker shrinking without an overflow-hiding substitute.

Exact-source browser and visual acceptance remains pending independent QA. Static
review alone does not establish all 32 cases, contrast, focus timing or shared-page
computed-style behavior.
