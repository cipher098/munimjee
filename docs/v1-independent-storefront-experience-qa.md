# Independent public storefront experience QA

Frozen application source: `abab30aaf1ab94052344b0ef21d05b3922f260dc`.
This lane changed only new independent test/export scripts, this document and its
owned evidence directory. No application, dependency, existing harness or migration
was changed. All three themes were tested against fresh actual SSR and the actual
live storefront modules with synthetic, fully intercepted HTTP.

The final sweep contains **69 passing checks and 6 failing checks**. The six failures
represent one reproducible **P2 product defect**, repeated for editorial, catalogue
and video at both 320px and 390px: the missing-photo bag title overlaps the line price.
The runner deliberately exits **1** while that defect exists. This is not a green
product acceptance report.

## Actionable finding

**P2 — Missing-photo bag layout overlaps product title and price on phones.**

Reproduce with any of the three actual public themes, a published product with no
photo, a name such as “Independent occasion dress”, and an available M variant:
open the product, choose M and add to the bag at 320px or 390px. The image fallback
spans the grid row; the text details then occupy the first 65px column. The first
word paints into the line price. The text is visibly superimposed even though the
page and dialog have no horizontal scroll overflow.

The shared source path is `frontend/storefront/src/live-app.js:37` calling `art()`
inside `.cart-line`; `components.js:19` returns `.empty-state` for missing media.
The global `.empty-state { grid-column:1/-1 }` rule in `styles.css` also applies there,
while mobile `.cart-line` uses `65px 1fr auto`. The local implementation owner should
isolate or explicitly lay out that fallback and retain this regression.

Evidence:

- `artifacts/v1/independent-storefront-experience/*-320-missing-photo-overlap.png`
  and `*-390-missing-photo-overlap.png` show every theme.
- `result.json` records both title text-fragment rectangles and the actual price
  text rectangle, plus their intersections. The assertion compares painted text
  boundaries, rather than assuming container widths prove readability.
- `runner-output.txt` preserves the six red assertions and the final summary.

The coordinator independently inspected the 320px catalogue screenshot and
confirmed the overlap. No production fix or assertion suppression is included.

## Coverage inventory and additions

The existing `export_wave4_public_theme_fixtures.py` /
`wave4_public_theme_http_mock_browser.mjs` already cover actual SSR text/privacy,
390px overflow, published defaults, COD/private order status and synthetic online
handoff. Preview specs cover narrow fixture-app layouts; the allocated-DB browser
runner covers native setup and durable purchase recovery when separately available.
This suite reuses the actual-renderer export pattern and adds the missing live
experience checks, without repeating successful payment/order journeys.

For each editorial/catalogue/video theme:

- Home, product, bag and checkout horizontal layout at 320×740, 360×800, 390×844,
  844×390 landscape, 768×1024 and 1440×1000. The lower checkout fields remain
  reachable inside the scrolling modal. Long published business/product names are
  separately checked at 320px.
- Keyboard product opening, radio selection, visible focus, modal/background focus
  separation, Escape dismissal and trigger restoration; semantic main/heading,
  skip link, named dialogs, labelled form fields and named visible buttons.
- Representative enabled primary-button text contrast and author-supplied keyboard
  focus outline contrast on each configured palette. Computed opaque colors and
  ratios are retained in `observations`; these checks do not certify all controls.
- Sold-out/inactive options cannot add stock; untracked availability stays explicit.
- Empty collections have their full-page hero explanation and announced zero count;
  zero search matches are announced and keyboard clearing restores the collection.
  JavaScript-off SSR retains its own empty explanation.
- Deferred availability refresh disables the pending control and then restores it.
  Network abort, HTTP 500, malformed DTO and invalid JSON preserve the catalogue and
  report an announced failure rather than silently fabricating new product data.
- Deferred checkout prevents repeated submission and shows progress. Aborted or
  malformed checkout responses preserve an uncertain attempt with read-only details
  and a retry action; explicit typed stock rejection remains rejected. No invented
  confirmation appears for those failures.
- Missing-photo text/price spatial separation at 320px and 390px, currently red.

There were zero unexpected requests and zero page errors. The browser origin is
`https://storefront-experience.example.test`; every allowed navigation, module/CSS
load and API response is fulfilled from the harness. Unknown paths and unexpected
origins are aborted and fail the report. No request is continued/fetched. There is
no fixture server, ambient service access, actual DB allocation or provider call.

## Reproduce with cached runtimes

From the isolated repository root:

```sh
PYTHONPATH=backend /tmp/munimjee-release-ci-py311/bin/python backend/tests/independent_storefront_experience_qa.py
MUNIMJEE_PLAYWRIGHT_MODULE=/Users/user/Documents/ChatGPT/munimjee-wave3-qa/frontend/storefront/node_modules/@playwright/test/index.mjs PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Users/user/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' node backend/tests/independent_storefront_experience_qa.mjs
```

The exporter imports the existing test safety policy before the pure renderer and
schema, without loading the application main/settings/database. It emits nine
fresh actual SSR files with synthetic products. The runner requires explicit
cached runtime paths and creates a fresh isolated Chromium instance/context; it
has no install, shared browser-profile or ambient-server fallback. Browser version:
`153.0.8010.12`. Syntax/compile checks also pass.

`fixtures/metadata.json` and `result.json` contain application hashes before/after,
fixture hashes, frozen source HEAD and exact exporter/runner SHA256 values. The
application source was unchanged during both export and browser execution. The
final commit changes only owned QA files; its runner hash identifies the scripts
independently of the frozen application HEAD recorded before the QA-only commit.

## Harness calibration, separated from product findings

Earlier exploratory assertions were corrected before this final run:

- Requiring empty copy inside the grid ignored the actual visible hero explanation.
  Requiring a particular no-search-results sentence ignored the announced “0 pieces”
  plus usable search-clear recovery. Neither became a reported product defect.
- Strict exact Playwright label matching on the payment selector included nested
  option text. The final check requires its meaningful labelled combobox instead.
- Native Chromium may move focus from a modal to browser chrome. That produces
  document.activeElement BODY with document.hasFocus() false; it does not focus
  an underlying document control. The final check permits only that case and still
  rejects focused background controls.
- Pointer-directed focus does not activate `:focus-visible`. Contrast measurement
  now explicitly establishes keyboard modality and verifies the author outline.

`harness-calibration.json` preserves the intermediate 63-pass/6-fail diagnostic
report for the latter two harness assumptions. It is marked here as calibration,
not product acceptance. The final result contains only the six actual spatial
failures. These corrections do not weaken or hide the missing-photo regression.

## Limits and remaining acceptance

This is bounded desktop Chromium mobile-layout emulation with synthetic HTTP.
It is not physical iPhone/Android, touch/virtual-keyboard, screen-reader, complete
WCAG, production, persistence or payment/provider acceptance. No actual order,
customer send, credential, charge, deployment, Docker or database operation occurred.

Only representative primary text and author keyboard-focus contrast was computed:
text ratios editorial 6.446, catalogue 9.478, video 7.160; focus against adjacent
paper 4.366, 4.522 and 4.358. Other controls, disabled states, images, all palette
combinations, high-contrast settings, zoom and assistive-technology announcements
need their own coverage. The fixture has no seller photos or footage, so actual
media loading/playback, CDN behavior and visual garment fidelity remain untested.
The existing successful online flow was not duplicated. Actual migrated DB/native
purchase flows remain pending a separate P01 allocation. V02/V05 and full product
acceptance remain open with this P2 defect and those limitations.
