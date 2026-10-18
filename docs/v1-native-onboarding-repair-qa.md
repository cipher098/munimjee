# Native onboarding repair: independent QA

All 32 original cases and all eight bounded supplemental cases pass against the separate implementation owner's repaired native modules. There are zero skips, unexpected network requests or page errors. This is actual native browser source with intercepted synthetic HTTP and actual formatter output over fake rows; it is not mounted-DB or production acceptance.

Production base is `8ae97c2d57c0efda5a03a41a469bf9447739ee72`. Reviewed runtime owner commits `c85e480cf30d7c3ca55fbdceaca8dd2f9d6d7a20` and `8e62ea770729d04bc0982aadf64dadae41973cb9` compose locally as `539d259` and `16bd6ae`. Runtime bytes match the owner exactly and stayed unchanged in both runs. This lane owns QA only; no runtime file is authored here.

The prior independent result remains 27 passing / 5 failing of the same 32 cases. Its preserved source is `8ae97c2`; its evidence commit is `9642527196f2e80b0a0effd69678949be34074af`, under `artifacts/v1/independent-onboarding-experience/comparison-8ae97c2/`. This preparation does not rerun or overwrite it. Remaining IDs were `keyboard-transition`, `contrast-focus`, `startup-error`, `long-business-name`, `logout-focus`.

Reviewed originals `d92406e`, `a3a3d66`, `e0d819d`, `a7282ed` are composed as QA-only commits. The original 32-case runner SHA-256 is `13d503519ef85510f87d7faf29b6505c58fbe00f113d81dcfae66782e8619afd`; exporter SHA-256 is `601b632ca1309826e32acec16901ff5493d00db0df5fe9aa3cd44286e5c4a00f`. The only preparation change to those scripts permits/defaults their output to this lane's owned `artifacts/v1/native-onboarding-repair-qa/` directory. The entire 32-case execution/assertion body is byte-identical to `a7282ed`.

The actual formatter exporter ran with the existing pre-import safety gate, followed by the unchanged 32 cases against actual native modules and intercepted synthetic HTTP. Strict lost-response checks passed: one model commit, two version-3 attempts, stale retry 409, full version-4 fresh read and exact rendered facts, no acknowledgement preceding that fresh read, manual reload preserving all facts. The five prior privacy fixes pass without substitutions or skips. Same ordered 32 IDs and byte-identical execution/assertion body SHA-256 `9f1a4c19a8d655b8d2ddc5d7aee7331d60a421dc995d4d8b2ca81e766b82a6ee` are verified against `a7282ed`.

| Prior red ID | Repaired observation |
| --- | --- |
| `keyboard-transition` | Keyboard submission focuses current workspace `H1#business-heading`. |
| `contrast-focus` | Actual keyboard `:focus-visible`, author-supplied solid 3px green outline; 8.862737535767886:1 against adjacent opaque white panel. This is a narrowly scoped component check. |
| `startup-error` | Initial 503 exposes named “Reload and try again” button. Supplements prove its keyboard action makes fresh session GETs and respects both valid and 401 responses. |
| `long-business-name` | A valid 160-character unbroken business name at 360px yields document scroll width 360px and viewport 360px. |
| `logout-focus` | Completed keyboard logout focuses visible sign-in `H2#access-title`. |

No old failing ID remains and no new failure is classified. The original 27/5 comparison is pinned rather than rerun. Twenty-two earlier baseline artifact files remain byte-identical to `a3a3d66`.

The separate supplemental runner passes a finite eight cases:

- Initial 503 and transport failure, each followed by keyboard manual retry with a valid or denied current session: a new actual frontend session GET is required, no automatic retry or auth mutation, denied session stays outside workspace.
- Held interactive sign-in/business-load superseded by logout: late completion cannot focus obsolete workspace.
- Held old logout superseded by denied recheck and a new interactive sign-in: late callback cannot clear the current workspace or move current focus.
- Same-identity passive focus revalidation retains the current input focus.
- Successful keyboard transition with 160-character business name at 360px: current workspace focus, no horizontal overflow, full-page pass capture.

The old-logout model explicitly isolates DOM/focus callback fencing: its superseded synthetic response does not clear a newer synthetic cookie. Actual server logout, Set-Cookie ordering and real session races remain untested. This model is not evidence that a real old logout response cannot affect a newer cookie.

Independent peer review of preparation `1478a95` found no scope/safety blocker and requested stronger completion observation in the two existing deferred cases. QA-only `b8d7f77` waits for the corresponding source callback to remove `aria-busy` after release, then checks settled focus. All eight supplemental cases were rerun with that refinement and pass. The original 32-case run was not repeated because its harness/assertions and runtime bytes did not change.

Both runners use fresh headless contexts, block service workers/WebSockets, fulfill allowed numeric-loopback requests in process and abort/report everything else. No listener, ambient port 4317, database allocation/connection, credential/provider read, external send, production action or Docker operation is involved. Fixtures verify current formatter/capability/safety hashes before browser launch. Native source hashes are compared before/after.

Full-page signup and owner captures at 360/390/768/1440 and the focused long-name 360px capture were independently viewed. The incumbent muted-green palette, plain controls and uncertainty copy remain intact. The 160-character heading wraps within the document; its visible green keyboard focus outline encloses the current heading. The normal mobile and desktop profile, checklist and invitation sections retain their inherited layout. Thirteen screenshots, fixture/source/script/artifact hashes, source-owner path mapping and counts are recorded in `artifacts/v1/native-onboarding-repair-qa/verification.json`.

Reproduction from this worktree, using only cached runtimes:

```sh
/tmp/munimjee-release-ci-py311/bin/python backend/tests/independent_onboarding_experience_qa.py --output artifacts/v1/native-onboarding-repair-qa
/Users/user/.nvm/versions/node/v24.20.0/bin/node backend/tests/independent_onboarding_experience_qa.mjs > artifacts/v1/native-onboarding-repair-qa/run.txt 2>&1
/Users/user/.nvm/versions/node/v24.20.0/bin/node backend/tests/native_onboarding_repair_qa.mjs > artifacts/v1/native-onboarding-repair-qa/supplement-run.txt 2>&1
```

All three final commands exited 0. JavaScript syntax checks and `git diff --check` also pass. Actual server/Set-Cookie races, mounted migrated DB, physical touch, screen-reader interaction, complete contrast/WCAG audit and provider/production behavior remain separate gates. Local integration `eeb94a1`/0056 is reported only and was not tested here. This is no launch/readiness certification.
