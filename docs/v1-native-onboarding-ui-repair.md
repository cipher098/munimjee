# Native onboarding UI repair

Application base: `8ae97c2d57c0efda5a03a41a469bf9447739ee72`.
The coordinator explicitly relayed the local integrator's ownership transfer before
runtime edits. Runtime checkpoints are `c85e480cf30d7c3ca55fbdceaca8dd2f9d6d7a20`
and accessible-copy follow-up `8e62ea770729d04bc0982aadf64dadae41973cb9`.
Only `backend/static/v1_app.js` and `backend/static/v1_app.css` changed. No third
runtime file, HTML, shared commerce CSS, client/authentication policy, server,
schema, channel, activity or storefront source was needed.

The five bounded repairs address the independently observed keyboard transition,
logout focus, focus contrast, startup 503 recovery and valid long-name reflow.
The original 32 browser assertions and five previously fixed privacy/session cases
remain unchanged and owned by the independent QA worker. Exact-source browser
verification and shared-page review are pending; syntax/source checks alone do
not certify the repairs as product-verified.

## Behavior and guard preservation

- A class added by this native-only script marks the body `native-onboarding-page`.
  Parcel and customer pages load the shared stylesheet without this script/marker.
- After an interactive signup/login/invitation acceptance finishes opening the
  current workspace, focus moves to the business heading outside ordinary tab order.
  The caller captures the current generation and business-load epoch immediately
  after the workspace load starts. The helper rejects a changed generation/load,
  hidden or unfocused document, hidden view, or an already focused current view.
  This prevents a late completion from stealing focus after the user starts working.
- Confirmed logout captures the generation **before** awaiting the existing API and
  rejects a changed generation before cleanup. This also prevents an old held logout
  response from clearing a newer sign-in, because the existing logout API fast path
  does not perform the ordinary post-response generation check. Current cleanup is
  then followed by guarded focus on the visible sign-in heading.
- The focus helper is called only from those explicit interactive event handlers.
  No automatic focus was added to `endWorkspace`, `access`, `workspace`, business
  loads, current-session checks, focus/pageshow/visibility rechecks or role refresh.
- A native `button[type=button]`, “Reload and try again”, sits beside the existing
  announced global error. It appears only when a non-401 startup error leaves both
  ordinary panels hidden. It calls `location.reload()` on explicit activation, so
  startup again performs the existing real session/CSRF checks. It invents no signed
  state, restores no cached identity and starts no automatic request loop.
- All six new CSS rules require the native body marker. The incumbent green
  `#2e5141` replaces the low-contrast author outline while preserving a solid 3px
  indicator and 3px offset, including the programmatically focusable headings.
- Native heading/picker flex children may shrink and wrap within the available
  width; the business heading wraps unbroken names anywhere. Literal names and
  option values remain intact. Overflow is not hidden and no text is truncated by
  application code.

## Incumbent design guidance

Read `.impeccable/review/packet.md`, `documentation.md` and `finish-review.md`.
The patch retains the existing muted-green Operate interface, system type, white
panels and plain uncertainty/recovery language. It introduces no new design system.
The coordinator found no installed matching Impeccable/accessibility `SKILL.md` in
known roots; no actual skill was discovered in this repository. The notes' craft-
floor path belongs to another host and is unavailable. No installation was attempted.

Source color calculation gives green-to-white contrast **8.8627:1** and green-to-
paper (`#f6f7f3`) **8.2369:1**. These are calculations from opaque source colors,
not yet computed keyboard-modality browser observations or a complete WCAG claim.

## Author verification and independent handoff

`node --check backend/static/v1_app.js` and `git diff --check` pass.
`artifacts/v1/native-onboarding-ui-repair/source-verification.json` records exact
source SHA256 values, the six scoped rules, source color calculations and hashes
showing all 12 existing authority/lifecycle functions remain byte-identical to base:
endWorkspace, applyAuthority, checkedSession, pathAccess, api, clearInvite, access,
busy, loadBusiness, loadTeam, workspace and recheck. The handlers and startup error
presentation are the bounded JavaScript changes. `repair.diff` is the exact applied
review diff, not an unapplied preparation proposal.

Independent QA and the shared-impact reviewer received the exact final source
checkpoint before browser composition. They must retain all 32 cases and separately
verify explicit reload rechecks/denial, stale transitions and passive-focus behavior,
plus native marker isolation on the shared parcel/customer styles. Source-only
verification does not replace their results.

The author did not start a browser/server, allocate a DB, read actual credentials,
call a provider, send a message, charge, deploy, probe Docker or touch production.
Mounted/migrated sessions, actual providers, physical phones and assistive technology
remain separate acceptance gates. Any final product claim must cite the independent
exact-source results, not this implementation note alone.
