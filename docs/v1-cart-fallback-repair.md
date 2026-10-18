# Missing-photo bag repair

Status: bounded source/render review accepted; final runtime `4eed8af`, executed harness `13685d7353541bd71cef90aab99f05377c0e20e3`. No deployment or live-provider work.

Approved base `eeb94a119736cae816af782f2af5e04cb877e616`. The only runtime change is
`frontend/storefront/src/styles.css` in `4eed8af`. The original independent QA commit
`faec01614c27578afd38bef750b9dc2205ee7c98` and trusted output adaptation
`51f24801a5beb7f39ee57f8739301c633b056272` were cherry-picked alone as `f0f8bab` and
`e8c663c`; their production ancestors were not imported. The six painted-text
intersection assertions and all provider/network denials remain unchanged.

The global `.empty-state` selector spans a grid row. Missing-image `art()` uses it
inside a three-column bag line, so details and price move to later rows and the
name can paint over the amount. The fix scopes that fallback to the image cell,
matching the existing image dimensions (85×114 desktop,65×95 mobile), with compact
padding. The details column can shrink and the title wraps inside it. No renderer,
JavaScript/component, price, payment, activity, publication or API behavior changes.
The pre-repair CSS is byte-identical to the independently reproduced8ae97c2 source
(SHA256 `3b3d44107e53dc66a26154c96060852282db80d565ba4b0b32ce995217829e10`).

The original QA uses actual exported SSR and actual live modules with **synthetic,
intercepted HTTP**; it is not an actual mounted application or database proof. The
optional activity-context requests remain denied as unhandled and make that runner
exit1 independently of the75 UI outcomes. A UI pass must not be called a clean
whole-run exit or activity-contract acceptance.

Prepared mounted proof uses production `app.main`, native owner/session/CSRF,
actual catalogue SKU review/activation, theme save/publication, public SSR/assets,
and the same painted-text predicate at320/390 across editorial/catalogue/video.
It uses only the explicitly allocated P01 lane and8156 after serial release.
No manual router, synthetic product DTO or provider success is substituted there.
External requests and financial POSTs are denied. Ephemeral self-signed loopback
TLS is a test envelope, not public/providerTLS or physical-device acceptance.

## Fresh baseline

On the approved isolated composition, temporarily restoring **only** the exact
pre-repair CSS from `e8c663c` reproduces **69 UI passes /6 painted-text failures**,
all three themes at320/390, with0 page errors and stable source hashes within the
run (`cart-repair-before/result.json`). HEAD remains the test-owner commit13685d7
but the deliberately restored CSS hash identifies the actual baseline; the source
head alone must not be read as repaired-runtime proof. The repaired CSS was
restored immediately afterward. The runner correctly exits1, also preserving
153 denied same-origin activity-context requests. No route was allowed/fetched
for them. This was intercepted synthetic HTTP, not mounted backend/DB evidence.


## Repaired and mounted results

The unchanged original75-scenario runner now reports **75 UI passes /0 failures**,
including all six original Range-based title/price paint assertions. It still
exits1 because the exact same153 optional activity-context POSTs are denied as
unhandled. Zero page errors, no unexpected external origin, and source hashes
remain stable within each run. Do not call this a clean whole-run exit or activity
contract coverage. Cross-run source hashes differ **only in styles.css**; the
runner/exporter are byte-identical to the approved output-option commit.

**6/6 actual mounted checks pass, runner exit0**, using the guarded real0056 P01
migration lane, production `app.main`, Secure native cookies/CSRF, real SKU
create/review/activation, real theme save/publication and public SSR/modules at
both320/390 for each theme. No manual router, provider DTO or product projection
is substituted in that run. It creates0 orders and issues0 financial POSTs,
provider calls or external requests. It reports0 page errors and equal pre/post
hashes for all frontend JS/CSS. The test TLS envelope is ephemeral/self-signed
loopback with ignored browser certificate errors, not provider/publicTLS proof.

Executed commands (owned worktree; exact paths are in the result artifacts):

```sh
PYTHONPATH=backend ../munimjee-v1/.venv/bin/python backend/tests/independent_storefront_experience_qa.py --output artifacts/v1/independent-storefront-experience/cart-repair-after/fixtures
MUNIMJEE_STOREFRONT_QA_OUTPUT="$PWD/artifacts/v1/independent-storefront-experience/cart-repair-after" MUNIMJEE_PLAYWRIGHT_MODULE="/Users/gothi/Documents/Codex/2026-10-10/help-me-understand-x20/work/munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs" PLAYWRIGHT_CHROMIUM_EXECUTABLE="/Users/gothi/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" node backend/tests/independent_storefront_experience_qa.mjs
TEST_DATABASE_URL=<explicit-disposable-parcel_w6-URL> TEST_LANE=parcel_w6 TEST_DB_RESET=1 PYTHONPATH=backend ../munimjee-v1/.venv/bin/python -m tests.run_cart_fallback_browser
```

`cart-repair-before/` preserves the69/6 reproduction and raw output.
`cart-repair-after/` holds fresh SSR, all75 outcomes/paint observations, the denied
optional requests and captures. `cart-repair-mounted/` holds six native/migrated
captures, exact text rectangles, source/harness hashes, raw output and cleanup.
`cart-repair-summary.json` keeps the evidence boundaries explicit. The synthetic
Chromium run used cached145.0.7632.6; no installation or shared profile was used.
The mounted Playwright uses the same local installed runtime without external
assets. No synthetic buyer or order is needed for the mounted bag-only journey.

The catalogue peer independently inspected source4eed8af plus final mounted
editorial320/catalogue390/video320 captures and returned bounded **SHIP**: title
and price remain distinct, fallback stays in the image slot, controls fit, no
clipped price, all theme colors retained. The integrator separately inspected all six final mounted captures and returned
bounded SHIP for the same CSS. Test execution is the author's evidence, independent render/source
review is the peer's. The author also viewed those captures. The Impeccable
mechanical detector reports `[]`.

No owned server/runner or8156 listener remains, and no ephemeral TLS directory is
left (`cart-repair-mounted/cleanup.json`). **parcel_w6 and8156 are released**. The
runtime stayed frozen throughout each repaired run. Physical phones, real media,
screen-reader certification and live provider/payment behavior remain outside
this layout repair. The153 denied optional activity requests are a separate QA
fixture-coverage boundary, not repaired or bypassed here.
