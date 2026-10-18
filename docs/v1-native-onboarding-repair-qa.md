# Native onboarding repair: independent QA

Preparation is pinned to production base `8ae97c2d57c0efda5a03a41a469bf9447739ee72`. This lane owns QA only. Runtime changes are composed solely from the separate implementation owner's reviewed two-file commits. No runtime file is authored here.

The prior independent result remains 27 passing / 5 failing of the same 32 cases. Its preserved source is `8ae97c2`; its evidence commit is `9642527196f2e80b0a0effd69678949be34074af`, under `artifacts/v1/independent-onboarding-experience/comparison-8ae97c2/`. This preparation does not rerun or overwrite it. Remaining IDs were `keyboard-transition`, `contrast-focus`, `startup-error`, `long-business-name`, `logout-focus`.

Reviewed originals `d92406e`, `a3a3d66`, `e0d819d`, `a7282ed` are composed as QA-only commits. The original 32-case runner SHA-256 is `13d503519ef85510f87d7faf29b6505c58fbe00f113d81dcfae66782e8619afd`; exporter SHA-256 is `601b632ca1309826e32acec16901ff5493d00db0df5fe9aa3cd44286e5c4a00f`. The only preparation change to those scripts permits/defaults their output to this lane's owned `artifacts/v1/native-onboarding-repair-qa/` directory. The entire 32-case execution/assertion body is byte-identical to `a7282ed`.

After source composition, run the actual formatter exporter with the existing pre-import safety gate, then the unchanged 32 cases against actual native modules and intercepted synthetic HTTP. Keep strict lost-response checks: one model commit, two version-3 attempts, stale retry 409, full version-4 fresh read and exact rendered facts, no acknowledgement preceding that fresh read, manual reload preserving all facts. Keep the five prior privacy fixes covered without substitutions or skips.

The separate supplemental runner checks a finite eight cases:

- Initial 503 and transport failure, each followed by keyboard manual retry with a valid or denied current session: a new actual frontend session GET is required, no automatic retry or auth mutation, denied session stays outside workspace.
- Held interactive sign-in/business-load superseded by logout: late completion cannot focus obsolete workspace.
- Held old logout superseded by denied recheck and a new interactive sign-in: late callback cannot clear the current workspace or move current focus.
- Same-identity passive focus revalidation retains the current input focus.
- Successful keyboard transition with 160-character business name at 360px: current workspace focus, no horizontal overflow, full-page pass capture.

The old-logout model explicitly isolates DOM/focus callback fencing: its superseded synthetic response does not clear a newer synthetic cookie. Actual server logout, Set-Cookie ordering and real session races remain untested. This model is not evidence that a real old logout response cannot affect a newer cookie.

Both runners use fresh headless contexts, block service workers/WebSockets, fulfill allowed numeric-loopback requests in process and abort/report everything else. No listener, ambient port 4317, database allocation/connection, credential/provider read, external send, production action or Docker operation is involved. Fixtures verify current formatter/capability/safety hashes before browser launch. Native source hashes are compared before/after.

Required repaired-source captures are full-page signup and owner views at 360/390/768/1440, plus current keyboard focus and long-name reflow. The inherited muted-green incumbent style remains the reference. Physical touch, screen-reader interaction, complete contrast/WCAG audit, mounted migrated DB, provider/production behavior and real cookie races remain separate gates. This is no launch/readiness certification.
