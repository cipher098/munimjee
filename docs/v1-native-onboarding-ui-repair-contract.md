# Native onboarding UI repair: proposed ownership and patch contract

18 October 2026. Exact application base
`8ae97c2d57c0efda5a03a41a469bf9447739ee72` (runtime `52fdda8`). Independent
comparison from `3f50197` records 27/32 passing browser cases and five P2 UI
failures. Preserve all 32 cases, the five repaired privacy/session cases and the
existing identity, business-load, CSRF, current-capability and async fences.

**Transfer pending: no production/runtime writes are authorized yet.** This is the
minimal proposed patch for the local integrator to reserve. Source-only design,+test preparation, static review and an unapplied patch artifact are allowed.

## Exact proposed runtime ownership

| File | Proposed change | Limits |
| --- | --- | --- |
| `backend/static/v1_app.js` | Add one native-page marker for CSS scope; focus the current visible workspace after confirmed interactive signup/login and sign-in controls after completed logout; expose a keyboard-accessible startup recovery button on initial transport/503 failure. | Preserve IDs, `[hidden]`, textContent rendering, existing controls, checkedSession/api/pathAccess/endWorkspace authority and generation checks. No automatic retries or successful-session invention. |
| `backend/static/v1_app.css` | Add native-page-scoped author focus color using the existing dark green; constrain/wrap long heading and picker flex items so valid160-character names fit at360px. | Scope every new rule to the native-page marker. This stylesheet is also loaded by parcel/customer pages; they must keep their existing appearance. Preserve3px focus outline and spacing. |

No need to edit `v1_app.html`, global `commerce.css`, `v1_client.js`, any other
static/frontend file, server route/service/config, schema/migration, channel,
activity, authentication/cookie policy or authoritative data. If implementation
finds a third runtime file necessary, stop that change and report the exact reason
for a separate contract. Local social owns all storefront/cart repairs.

## Proposed behavior

- `keyboard-transition`: after the existing confirmed interactive access transition
  finishes and the current view is visible, move focus to its meaningful heading
  or first enabled control. Do not steal focus on passive session refresh, role
  changes or every business load; any deferred focus must check the current view
  and existing generation. Keep heading focus out of ordinary tab order.
- `logout-focus`: after the existing confirmed logout/terminal cleanup, focus the
  current visible sign-in context. Preserve cleanup and current-session rejection.
- `startup-error`: show a named native button next to the existing announced error
  when initial failure leaves both normal panels unavailable. Preferred minimal
  recovery is an explicit page reload, which reuses existing startup/session
  checks and cannot manufacture an authenticated state. No automatic request loop,
  cached identity restoration, cookie changes or new sign-in bypass. The retry
  button must remain keyboard usable and must not mask the error.
- `contrast-focus`: use the incumbent dark green for author focus indicators on
  the native page only, against actual adjacent white/paper backgrounds; retain
  width/offset. Verify keyboard modality and computed contrast, not pointer focus.
- `long-business-name`: retain all literal text; permit heading and picker flex
  items to shrink/wrap within the container. Do not hide overflow as a substitute
  for legible content or truncate the business name into a misleading identity.

## Workers and write boundaries

Existing named workers are reused with their GPT-6.1 Sol/high settings; no new
agents or other-chat messages. All worktrees start from exact8ae97c2.

| Worker | Worktree / branch | Exclusive writes during preparation |
| --- | --- | --- |
| instagram_provider: implementation | munimjee-wave9-onboarding-repair / codex/v1-native-onboarding-ui-repair | docs/v1-native-onboarding-ui-repair.md, artifacts/v1/native-onboarding-ui-repair/; only the two runtime files above after explicit transfer relay |
| instagram_contract_qa: independent browser QA | munimjee-wave9-onboarding-repair-qa / codex/v1-native-onboarding-repair-qa | New existing-owned independent_onboarding_experience_qa scripts from reviewed QA commits, optional new native_onboarding_repair_qa scripts, docs/v1-native-onboarding-repair-qa.md, artifacts/v1/native-onboarding-repair-qa/ |
| instagram_security: independent shared-impact/review | munimjee-wave9-onboarding-repair-review / codex/v1-native-onboarding-repair-review | docs/v1-native-onboarding-repair-review.md, artifacts/v1/native-onboarding-repair-review/; runtime/test source read-only |
| root: coordination | munimjee / codex/v1-native-onboarding-repair-coordination | This contract, docs/v1-native-onboarding-repair-handoff.md, artifacts/v1/native-onboarding-repair-coordination/ and reviewed composition |

## Guidance and verification

No matching installed Impeccable/accessibility SKILL.md was found in the supplied
skill roots or common local skill directories. The repository's
`.impeccable/review/packet.md`, `documentation.md`, `finish-review.md` were read;
they preserve incumbent muted-green Operate styling and plain uncertainty/recovery
copy. Their craft-floor path points to another host and is unavailable here. No
new design system or unrelated global cleanup is proposed. Applicable primary
references remain W3C Focus Visible, Non-text Contrast and Reflow, as recorded in
the previous independent QA evidence.

Independent QA must run all32 reviewed cases against actual repaired modules with
fresh current-source formatter fixtures and intercepted synthetic HTTP; no weakening
or skipping prior privacy/recovery assertions. Add only bounded recovery/focus checks
needed to show retry performs a fresh session check, stays unauthenticated on denial,
and does not focus an obsolete view. Inspect screenshots at360/390/768/1440, long-name
reflow and keyboard focus. Check unchanged shared-page style scope statically and
with a bounded source-backed fixture if justified. All screenshots and source/harness
hashes must be exact; labels/DOM checks are not screen-reader or full WCAG proof.

No live provider, actual credentials, customer sends, charges, server/DB allocation,
ambient4317 service, Docker, production, DNS/billing or hosted-CI operation. Actual
mounted/migrated sessions, physical phones and assistive technology remain separate
acceptance. Local eeb94a1/0056 testing is reported context and does not certify this
isolated repair. Push reviewable separate checkpoints and relay the exact file
transfer before runtime edits.
