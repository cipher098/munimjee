# Native onboarding repair handoff

18 October 2026. All five scoped UI repairs are complete on application base
`8ae97c2d57c0efda5a03a41a469bf9447739ee72`. Independent browser QA passes the
original unchanged 32 cases and eight supplemental checks, with zero failures,
skips, unexpected requests or page errors. Independent source and screenshot
review found no blocking issue. This is ready for local integration review;
mounted-session and release acceptance remain pending.

## Changes and integration

Only `backend/static/v1_app.js` and `backend/static/v1_app.css` change at runtime.
The confirmed two-file ownership contract is preserved. The changes provide:

- Focus into the current workspace after interactive signup/login and into
  sign-in after confirmed logout, guarded by the existing generation and
  business-load counters. Passive refresh retains the user's input focus.
- A pre-await generation capture on logout, preventing a late old callback from
  clearing or focusing a newer sign-in view.
- A native-page-scoped dark-green keyboard focus outline, retaining 3px width
  and offset. The measured component contrast against white is 8.8627:1.
- A keyboard-usable “Reload and try again” action after initial 503 or transport
  failure. Explicit reload uses the existing startup/session checks.
- Reflow for a valid 160-character unbroken business name at 360px, with full
  literal heading text and document width equal to viewport width.

For runtime-only integration, apply the reviewed owner commits in order:
`c85e480cf30d7c3ca55fbdceaca8dd2f9d6d7a20`, then
`8e62ea770729d04bc0982aadf64dadae41973cb9`. They compose here as `4410e56` and
`dbd91a9`. Avoid applying both original and composed versions. The complete
`codex/v1-native-onboarding-repair-coordination` branch also contains the
dedicated tests, preserved historical evidence, reviews and this handoff.

| Runtime file | SHA-256 |
| --- | --- |
| `backend/static/v1_app.js` | `ee4a64b78b1a177e199a22f2cc1e10e146ff66120111bb2147f8bb0920ef9e91` |
| `backend/static/v1_app.css` | `6e9ca1e94315efe982654edab93ecb3e19442f71b1ec6e8a3da62777b25ef52c` |

All 12 protected authority/lifecycle helper bodies and all previous CSS bytes
remain unchanged. Each of the six appended CSS rules requires the native body
marker. Shared parcel/customer HTML and JavaScript, native HTML, `v1_client.js`
and `commerce.css` are byte-identical to base. Shared-page isolation is a static
source finding; no shared-page computed-style browser run is claimed. Local
social retains ownership of storefront/cart changes.

## Verification and exact checkpoints

Existing named GPT-6.1 Sol/high workers were reused: `instagram_provider` for
implementation, `instagram_contract_qa` for independent browser QA, and
`instagram_security` for independent lifecycle, shared-style and visual review.

| Lane | Pushed branch | Exact completed head |
| --- | --- | --- |
| Implementation | `codex/v1-native-onboarding-ui-repair` | `a60ec1ac823fd0742e21bac2d8f801f01a0dbc0e` |
| Independent browser QA | `codex/v1-native-onboarding-repair-qa` | `a0350f779658093325e776acb18ef9d9f7dd8b1f` |
| Independent review | `codex/v1-native-onboarding-repair-review` | `ed35aa77d280b525d7649b3c503db9b92f1bdeb3` |

The prior 27-pass/5-fail comparison at `9642527` is pinned with its exact hash;
it was not overwritten or rerun. All five red IDs now pass:
`keyboard-transition`, `contrast-focus`, `startup-error`, `long-business-name`,
`logout-focus`. The prior five privacy/session repairs also pass. Original
32-case execution/assertion body SHA-256 remains
`9f1a4c19a8d655b8d2ddc5d7aee7331d60a421dc995d4d8b2ca81e766b82a6ee`, and the
ordered case IDs are identical. Earlier baseline artifacts are preserved.

Supplemental checks cover four manual-reload outcomes (503/transport, each with
valid/denied fresh session), held sign-in superseded by logout, held old logout
superseded by a new sign-in, passive refresh retaining focus, and focused long
name at 360px. The held-response checks await source callback busy-state cleanup
before asserting settled focus. The old-logout fixture explicitly models a
superseded synthetic response that cannot overwrite a newer synthetic cookie;
it proves DOM/focus callback fencing only.

Browser QA used actual native source and freshly exported actual formatter DTOs
over fake rows, with all HTTP fulfilled or denied in-process. No listener or
ambient port 4317 was used. Signup and owner captures at 360/390/768/1440 and the
focused long-name 360px capture were independently reviewed. Root additionally
viewed the focused long-name and desktop owner captures and checked every
source, formatter, script and evidence hash after composition. All cherry-pick
patches match their originals. Node syntax and whitespace checks pass. A repeat
browser run was unnecessary because all tested source and runner bytes match
the passing independent run exactly.

See [implementation](v1-native-onboarding-ui-repair.md),
[browser QA](v1-native-onboarding-repair-qa.md),
[independent review](v1-native-onboarding-repair-review.md), and
`artifacts/v1/native-onboarding-repair-coordination/final-verification.json`.
The verification artifact records exact original/composed commit mappings and
all source/evidence hashes. Reproduction commands are in the browser QA report.

## Remaining acceptance boundary

Local source reconciliation and an actual migrated mounted-session check follow
integration. This work does not certify real server logout or Set-Cookie race
ordering, mounted database behavior, physical touch, screen-reader interaction,
complete WCAG compliance, provider behavior or release readiness. Local
`eeb94a1`/0056 is reported context only and was not tested or accepted here.
No backend, schema, provider, authentication policy or production change is part
of this repair.
