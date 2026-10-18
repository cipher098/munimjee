# Independent onboarding experience QA

Frozen application source: `abab30aaf1ab94052344b0ef21d05b3922f260dc`.
18 October 2026. Exclusive branch `codex/v1-onboarding-experience-qa`; no application
or existing test/safety-harness files changed. The full go-live plan and frozen
independent-experience contract were read before testing. Local owners retain
onboarding/privacy fixes. Findings below are against this snapshot, not their work.

## Evidence boundary and existing coverage

The existing `backend/tests/browser/onboarding.mjs` tests a mounted real application
and allocated database at 8012. It covers signup, saved/resumed profile, conflict,
CSRF, viewer invitation access, delayed invitation response after business switching,
logout/all and 390px mobile overflow. This new lane did not launch it or attach to
its service. No disposable database was allocated; actual mounted/DB behavior is an
explicit unrun gate, not a passing or skipped-by-assertion browser test here.

The new Python exporter reuses unchanged P01 `install_test_safety` before application
imports. It invokes actual `onboarding_view`, `business_view` and role capabilities
with injected fake authorization/counts for two synthetic businesses/four roles.
No secret/dotenv/provider/DB data is loaded. These DTOs are source-backed synthetic
fixtures, not authenticated HTTP or persistence evidence.

The JS harness loads the unchanged native HTML, JS, shared client and CSS into a
fresh isolated cached Chromium. Every browser request is intercepted and either
fulfilled in-process from a strict asset/API allowlist or denied. Its numeric
loopback origin `http://127.0.0.1:47991` has **no listening service**. No route uses
continue/fetch, no ambient 4317 service is touched, service workers are blocked and
websockets are denied. Each case gets a fresh context; all close in finally blocks.
No user's existing profile/tab is used. API state transitions and failures are
synthetic; they test the frontend response to those conditions.

## Result and actionable failures

**32 scenarios: 22 pass, 10 fail; runner exits 1.** Red assertions remain red.
Source hashes before/after match; unexpected request paths/origins and page errors
are zero. Full failures, DOM visibility snapshots and screenshots are in `result.json`.
All identities, names, email addresses, invitation strings and storage entries are
synthetic. No backend authorization bypass or real customer disclosure is claimed.

| Case / priority | Reproduction and observed result | Local fix acceptance |
| --- | --- | --- |
| `session-revoke-401` P1 UI privacy | Create synthetic invitation, return 401 to Revoke. Error appears while the prior profile and invitation bearer link remain visibly rendered. The backend result is denial, not a successful forbidden write. | Route this path through the terminal identity fence; clear private values/links and show sign-in. |
| `cross-identity-error` P1 UI context isolation | Return a valid string-detail 422 containing a synthetic A-context marker, sign out, then sign in as a different user/CSRF with only business B. B heading/profile load, but A's marker remains visible in profile-error. This demonstrates frontend retention of a supplied prior-context error; it does not claim the current backend emits real sensitive text. | Clear private error/status regions on identity transitions and before new business rendering. |
| `session-switch-401` P2 recovery | A→B picker load returns 401. Workspace remains visible with an error and cached controls/values still in the hidden business-content subtree; this is distinguished from visible full-profile disclosure. | Enter sign-in state and clear private DOM consistently. |
| `role-focus`, `session-focus` P2 stale UI | Change synthetic server-side role to viewer or end its session, then return window focus. No session read occurs; old editable controls/private display remain. No prohibited mutation is sent by these tests. | Revalidate on relevant lifecycle boundaries, fence identity/role changes and reject stale asynchronous results. |
| `startup-error` P2 recovery | Initial session returns 503. Loading ends, both access/workspace panels remain hidden and no retry/sign-in control is available. | Provide an explicit accessible recovery action without inventing a successful session. |
| `long-business-name` P2 mobile reflow | Valid 160-character unbroken name at 360px yields document width 3062px. Screenshot independently inspected. | Contain/wrap long headings and business selection without hiding meaningful text or causing page-wide horizontal scroll. |
| `keyboard-transition`, `logout-focus` P2 keyboard context | Keyboard signup and keyboard sign-out both leave activeElement at BODY after the prior context disappears. | Place focus in the new meaningful visible context, with keyboard-visible focus. |
| `contrast-focus` P2 scoped focus contrast | Actual keyboard Tab reaches password; author CSS `:focus-visible` gives a solid 3px rgb(149,174,149) outline adjacent to opaque white panel. Computed contrast is 2.3955:1, below the chosen 3:1 criterion. This is not UA-default focus styling or a full contrast audit. | Use an author focus indicator meeting adjacent-background contrast in each relevant state. |

`access()` clears profile inputs/checklist/invitation data but leaves profile-error,
profile-status/global-error text; `busy()` and the picker/Revoke catch paths have
different session handling. These concrete source boundaries explain the reproduced
findings. The local privacy owner should unify the fence rather than patch only one
assertion. Current backend authority must remain independent of stale UI controls.

The narrow focus criterion is consistent with the coordinator-verified
[W3C non-text contrast understanding](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).
Keyboard focus/reflow references are [Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html)
and [Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html).
No WCAG certification is claimed.

## Passing checks and remaining limits

Passing coverage includes signup and owner profile/checklist/invitation layouts at
360/390/768/1440px; normal label associations and mobile input font sizing; keyboard
skip-link/tab order and invalid-email prevention; primary button text contrast;
announced held initial loading; manager/staff/viewer controls from actual capability
output; unavailable requested business without fallback; zero membership state;
held profile save with disabled duplicate button/aria-busy; lost save response with
explicit reload and optimistic conflict; delayed A profile response discarded after
B selection; profile-save 401 fence; literal HTML-looking names; and native recovery
storage cleanup preserving an unrelated public-checkout namespace.

Normal invitation/bearer strings are included in all owner viewport screenshots;
maximum-length invite-email/token stress is not part of this minimal checkpoint.
Screenshots of owner360, long-name overflow and revoke401 were visually inspected.
Mobile emulation does not test physical touch, browser chrome, virtual keyboards or
real iPhone/Android behavior. DOM labels/roles and focus checks do not establish a
screen-reader journey. Only representative primary/focus contrast was computed;
all other component/state contrast, zoom, full WCAG review, mounted migrated DB,
real session/role concurrency, physical devices and complete V01/V1 acceptance remain
unrun. Backend persistence and actual server-denied mutation behavior need their
existing guarded lanes; the fixture's synthetic denial is not that evidence.

## Reproduction and artifacts

From this worktree root, without DB allocation:

```sh
env -u TEST_DATABASE_URL -u TEST_LANE -u TEST_DB_RESET /tmp/munimjee-release-ci-py311/bin/python backend/tests/independent_onboarding_experience_qa.py
node backend/tests/independent_onboarding_experience_qa.mjs > artifacts/v1/independent-onboarding-experience/run.txt 2>&1
```

The JS defaults point to the verified cached Playwright module in the wave3 QA
checkout and cached Chromium headless shell; positional arguments can select other
installed module/executable paths. No installation is performed. `result.json`
records exact source/runner/fixture hashes, browser version, expected failing exit,
all case outcomes and explicit unrun gates. `fixtures.json` records actual formatter
source hashes and its injected-data boundary. All writes stay in the three owned
test/doc/artifact paths. The harness is submitted for recovery/security peer review;
source-backed UI failures are handoff items, not fixes made by this lane.
