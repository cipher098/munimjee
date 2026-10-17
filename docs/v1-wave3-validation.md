# Wave3 validation and acceptance boundary

Application source through `af6c3e4`, followed by the mounted import transaction guard (payment domain followup `626d62f` integrated as
`9729441`). All resets use the held P01 lease, explicit `wave3_integration`
loopback URL, disposable PostgreSQL16 and actual Alembic head 0048. No production
DB, `.env`, existing service or original ParcelDesk source is a test target.

| Failure or transition | Required result | Local proof |
| --- | --- | --- |
| Import unknown price/stock/options, malformed or incomplete allocation | No inferred facts and no partial approval/Product/SKU creation | `test_import_catalogue.py`, strict schema checks |
| Approval failure, same-key concurrency, reimport or changed key/body | One atomic private product/provenance receipt, or complete rollback; never publish/activate | Actual 0047/0048 bridge tests |
| Manual product creation versus bridge/store settings | Both complete without FK lock inversion | Actual opposite-path regressions; independent original repros rerun successfully |
| Native role/session revoked during store/product/order row wait | Current authority before commit;403/401 and complete rollback | `test_v1_mutation_boundary.py`, bridge after-wait tests |
| Payment flag/account/Business/Seller disabled | Zero first provider order POST through new session and both older SKU aliases | `test_checkout_sessions_api.py`; legacy Product behavior preserved |
| Lost provider order creation response or concurrent initialization | Existing durable unknown state; no second provider POST, exact-ID reconciliation only | Actual PG16 tests and native/public browser recovery |
| SDK missing before a new order | Zero customer order/provider POST, editable unsent form | Actual production-bootstrap guest browser |
| Invalid callback/signature/amount/currency or SDK success alone | No paid state; captured server authority remains required | API/webhook and module tests |
| Existing provider order after flag/account rotation, unpublish or inactive tenant | Status/settlement use the validated saved order snapshot; no new provider order | API and older-alias ready-snapshot tests |
| Older pending status arrives after verified paid | Paid remains in UI and stored confirmation | Independent controlled repro rerun; actual bootstrap browser |
| Seller association/capture check | Exact ID and explicit confirmation; no charge creation or browser-paid shortcut | Safe native payment-review DTO/API, actual seller→same-buyer browser journey |
| Reconciliation list response after another order selected | Current selection remains | Actual browser held-list regression |
| Session replacement/401 while private guard pending | Clear private DOM/intent and latch; old guard issues no new private request | Actual native login replacement plus held session response/browser; independent source/UI review |
| Parcel scan without selected order/courier confirmation | No implicit link; manual selection/camera-denied fallback | Real ZXing synthetic-camera plus actual native browser |
| Parcel enrollment committed but response lost / worker wakeup lost | Durable exact command recovery creates one enrollment/link | Real Worker.fetch/HMAC/SQLite plus actual PG16 tests/browser |
| Foreign/changed connector, order, session or role | Fail closed before effects, or review-required after a remote commit | Row-wait/HTTP rechecks, DDL tenant actor FKs, registry-change tests |
| Duplicate/out-of-order tracking events or terminal regression | Append-only history, stable dedupe and explicit review; no order payment/dispatch mutation | Two-service tests and browser order invariants |
| Tracking with absent consent or changed template/connector before send | Tracking proceeds; customer notification withheld and no second sender | Actual existing outbox hook with synthetic provider and post-template-wait changes |
| Camera/session ends or courier selection changes during preview | Camera stops/private facts clear; returned signed courier identity controls confirmation | Final native browser and independent capture/source review |
| Runtime missing assets, test/key path or disabled storefront | Startup fails closed where enabled; private/test files excluded |258-file allowlist/hash proof, 10 pure checks, 3 offline image modes |

Final current-source browser evidence: **38 online/seller-recovery**, **66 native
catalogue**, **25 COD**, **18 parcel** actual application checks. The **22 theme
checks** use injected HTTP and do not certify persisted theme settings. Provider,
SDK, refresh and customer-send transport outcomes are synthetic; real DB/session/
CSRF/stock/receipts/router bootstrap behavior is local application behavior.
Counts overlap and are not a unique end-to-end coverage total.

The full checkpoint through `1ac880a` passed 1223 tests with 8 documented skips in
363.48s. The final-source combined regression is recorded separately as
`artifacts/v1/integration/2026-10-18-wave3-final.{xml,txt}` when complete.

Open product/release gates: remote native import review/allocation bridge UI,
persistent theme 0049 and all-theme public rendering, native payment credential
entry UI (the protected local configuration API exists), review-required parcel
resolution/replacement, private ParcelDesk provisioning/D1/TLS, physical phone,
real approved Meta/template and Razorpay/CSP canaries, migration/restore/CI and
multi-architecture release rehearsal. Sales console, analytics, explicit expiring
support grants, verified customer identity links and the remaining complete
onboarding matrix remain V1 scope. No production deployment, live provider
mutation, real paid transaction or customer message is authorized or claimed.

A final mounted-route audit reproduced revoked native import job creation during
a Business-row wait (HTTP 202 after session revocation). The main application now
mounts all import mutations with the same transaction-final catalogue-write
guard. Five real wait/revoke regressions cover create/upload/review/cancel/retry;
all roll back with 401. The combined mutation/import/bridge/startup rerun passed
**64 checks** in 50.87s. The earlier final-suite attempt was deliberately
interrupted to land this fix (331 passed/1 skip at interruption), and is preserved
as `wave3-interrupted`; it is not a completed gate. The final-source suite/image
are rerun after this guard change.
