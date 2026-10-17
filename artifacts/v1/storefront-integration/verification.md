# E20 canonical publication verification

18 October 2026. Author run on `codex/v1-storefront-integration`; source commit is the commit containing this manifest. Dependencies: `38c3da0`, `9402390`, `d606325`, `8a42e54`, `837b7b0`. No deployed runtime, provider/payment/customer messages or external asset requests.

- 84 Python checks passed in 28.17s, covering actual migrated PostgreSQL16 publication/checkout, pure SSR and 7 startup/package guards: `test_storefront_publication.py`, `test_v1_storefront_rendering.py`, `test_v1_wave2_storefront.py`, `test_v1_checkout.py`, `test_v1_checkout_api.py`, `test_v1_storefront_bootstrap.py`. Dedicated P01 `channel_operator_w2` lane, full migrations through0046, exact allocation/reset lease; no other database. Two existing dependency deprecation warnings only.
- 45 Node checks passed; package syntax checks plus explicit canonical-contract.js/order-status.js syntax checks passed.
- 22 incumbent Playwright fixture/injected-HTTP theme checks passed in 22.4s on8151, including all three existing theme contracts;4317/4318 untouched.
- 24 additional Chromium real native/API/database checks passed on8150 through the actual production bootstrap after the final pagination/media/COD-only fix: native signup→store settings→reviewedSKU→activation→publication→policy→SSR→mobileCOD→protectedstatus. Four uncertain POST outcomes (committed-response loss, malformed200,500,untyped409) reload/retry with identical body/key and exactly one resulting order. Definitive typed stock rejection creates no order; corrected intent only follows reviewed bag availability. Order capability travels in Authorization, neverURL; anotherbrowser denied; status works after unpublish. Tests/node_modules/package assets return 404. No-COD browsing cannot place an order. A real DB gateway-only account/provider test and canonical API decoder test verify online payment is not advertised. No external requests/JavaScript errors reported.
- One Impeccable deterministic scan of the five changed/newfrontend modules returned`[]`. This is source evidence, not pixel contrast evidence. Author inspected all seven listed captures at actual390px/1365px viewports, plus incumbent theme browser regressions. Existing theme styling/copy is preserved; optional images are deliberately absent and labelled.

Captures: desktop-public-collection.png, mobile-public-product.png, mobile-cod-checkout.png, mobile-cod-confirmation.png, mobile-private-status.png, desktop-replayed-cod.png, desktop-stock-rejection.png. All names, addresses, accounts and catalogues are synthetic. No shipping or payment success is asserted from an order receipt.

Independent integrator source/render review accepted the bounded COD UI, pending the final online-option correction and actual bootstrap run, now completed. Its pagination finding (same total with duplicate product/SKU across pages) and online option without implemented payment handoff are fixed and regression-tested. Fresh additional agent spawning had previously failed due to the session thread-capacity limit, so no fresh spawned reviewer or documenter is claimed. The active integrator provides independent review; final integration verdict is recorded by the integrator.

Final integrator disposition: **ship this bounded COD slice**. The integrator checked the corrected COD-only provider/decoder and configured gateway-only rejection test, inspected desktop collection/stock rejection and mobile checkout/confirmation captures, and reran all **24 real browser checks** against the actual mounted production bootstrap on the separate `auth_wave2` PostgreSQL 16 lane through 0046. All **7 bootstrap guards** and **21 combined publication/bootstrap/workspace checks** passed locally. The latter also verifies that the seller's optional public-store link uses the configured origin, ignores Host and remains absent when the public feature or publication is off. Refreshed captures come from that integration run. No live payment, provider approval, media retrieval or full V1 completion is certified.

Shared registration/config remains integrator-owned; see docs/v1-storefront-integration.md. Docker frontend-asset packaging, online payment steps, production/provider/physical-device evidence and theme persistence remain gates. Paged SSR capacity is limited to1,000products with explicit503beyond; no truncated completeness claim.

Ordinary-extension documentation pass used the skill's inline documenter fallback after fresh reviewer capacity was unavailable. No design-system files changed. Checked `src/styles.css`, `src/live.css`, `src/theme-config.js`, shared components and the seven rendered captures.

Palette: incumbent paper/ink/panel/accent variables and catalogue green unchanged.
Type: incumbent serif display with 15px/1.5 system body unchanged.
Layout: existing collection grid, 390px single-column fields and bounded scrolling dialog preserved.
Controls: shared 44px-or-larger controls, focus outlines and existing primary/secondary buttons reused.
Rules: confirmed facts come from the server; pending payment remains visibly pending; no new imagery or decorative system introduced.

Pre-existing eyebrows, glyph icons and thick alert stripe remain outside the requested API/contract integration scope; they are not canonized as new design guidance or repaired unasked.
