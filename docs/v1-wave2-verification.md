# Wave 2 independent verification

Owner: QA/F20, `codex/v1-wave2-qa`, base `7de7cd68ce700e089bcf31e357aeebb08ea08299`.
Frozen decisions: `docs/v1-wave2-contracts.md`. This document records bounded
verification and pending gates; it is not release approval or provider evidence.

## Acceptance and failure matrix

| ID | Boundary | Positive observation | Required adversarial observation | Current gate |
| --- | --- | --- | --- | --- |
| QI01 | Website source authorization | Authorized HTTPS source is retrieved by a pinned public IP | Userinfo/query secrets, private/mixed DNS, transition IPs, peer mismatch, cross-origin/private redirect and rebinding fail before unsafe transport | Independent fake-transport/resolver checks pass; actual retrieval remains pending |
| QI02 | Bounded source parsing | Literal JSON-LD Product fields become drafts with provenance | Compressed/oversized/slow bodies, malformed/duplicate JSON keys, duplicate normalized source IDs and conflicting offers never produce an authoritative fact | Independent malformed-source and global-budget checks pass after reviewed fixes |
| QI03 | Import actor and tenant | Current authorized actor creates/reviews only owned jobs | Revoked membership/session, foreign source/job/candidate and spoofed actor/business in input fail before fetch/write | Independent write-schema/revoked-action fake-service checks pass; native sessions/actual DDL pending |
| QI04 | Import recovery | Retry/cancel/reload has a durable visible outcome | Competing claims, stale leases, cancellation before persistence and retries cannot duplicate candidates or publish | Persistence implementation and actual DB pending |
| QI05 | Reimport and catalogue write | Seller corrections survive an approved canonical draft write | Stale/concurrent revision conflicts; changed source facts invalidate review; unknown stock is not untracked stock; no implicit activation/publication | Pure domain verified; persisted bridge pending |
| QS01 | Public catalogue | Published approved public facts render on canonical routes | Unpublished/foreign IDs and unknown slugs return 404; private prices/tokens/notes stay absent in JSON, HTML and metadata | Independent SSR fake-provider checks pass; canonical publication provider remains unconfigured |
| QS02 | Browser product/cart | All three themes use real DTOs, explicit SKU choice and current stock | Unknown/stale/inactive/review SKU, malformed DTOs, malicious strings/URLs and changed basket state fail closed | Three independent preview browser checks pass on 4319; real DTO journeys pending |
| QS03 | Checkout attempt | One canonical server-priced order per idempotency key | Double click, refresh, network ambiguity and same-body retry reuse the attempt/key; changed basket cannot silently resubmit; 403/404/409 recover truthfully | Sixteen independent pure JS and three explicit mock-HTTP journeys pass; canonical checkout/provider gate pending |
| QS04 | Browser publication/privacy | Canonical product route carries escaped product metadata | HTML/script breakout, URL schemes, malicious IDs and private DTO fields cannot enter executable markup or third-party requests | Script/URL/identity/nested-private-object projection checks pass after reviewed fixes |
| QX01 | Cross-module ownership | Native member reads own catalogue and preserves seller-reviewed facts | Revocation after a valid read prevents the next authorized action; cross-tenant SKU constraints reject direct inserts; draft review creates no order | Five new parameterized cases use P01 migrated_engine; actual DB unavailable on this host |
| QX02 | External effects | Fakes/replay and local HTTP only | No real provider send, payment, courier booking, customer message or production mutation | Enforced by P01 for backend; browser routing/local request assertions required |

## Environment and evidence

This Mac mini uses its own Python 3.12 virtual environment. P01 disables dotenv
and inherited provider settings, blocks outbound sockets except an explicitly
guarded test DB, and requires an actual Alembic head with a held reset lease.
No test uses `Base.metadata.create_all` as migration proof. Docker remains
unavailable here; no restart or remote database exposure is attempted.

Storefront verification uses port **4319**, separate from the preserved 4317
preview and the storefront worker's 4318 server. Browser sessions/tests are
serialized. Fixture or mocked-HTTP browser tests remain simulated until the
coordinator registers APIs/migrations and runs the actual product journey.

Initial independent baseline command, before adding wave 2 tests:

```sh
.venv/bin/python -m pytest backend/tests/test_v1_import_drafts.py backend/tests/test_v1_identity.py backend/tests/test_v1_catalogue.py -q
```

Result: **186 passed**, no skips, on frozen-doc source `f9f1678` (application tree
still base `7de7cd6`). Existing deprecation warnings remain. This covers the
foundation pure domain only; none of the pending persisted/live rows is counted
as passed from this result.

## Independently reproduced defects and disposition

- Import checkpoint `b1b4b40`: duplicate JSON-LD keys silently selected a price;
  whitespace-distinct source keys collapsed after candidate normalization;
  common credential-query aliases were accepted; shielded late failures emitted
  unobserved task errors. Tests reproduced all findings with synthetic inputs.
  Reviewed fixes `cac1adc` and `e8d8a26` resolve these, including double encoding,
  bounded query-field errors and a process-wide four-work admission cap. No real
  DNS resolution, transport thread or external HTTP was used in these tests.
- Storefront checkpoint `8bdbee3`: an already-open uncertain attempt could retry
  after 24 hours without rechecking expiry. `9f775dd` resolves this and preserves
  an expired locked tombstone while erasing PII. The independent test now passes.
- Malformed public provider data could alias one SKU across products.
  `160312f` rejects repeated product/SKU/category IDs and inconsistent parent IDs;
  the independent regression now passes. This was a defensive malformed-provider
  finding, not proof of a cross-tenant database exploit.
- Nontext policy/category presentation fields could serialize a nested private
  object into public HTML/JSON. Independent regressions reproduced all three
  cases; `86e2455` now rejects malformed text before projection.
- Three separate actual-DB regression cases retain cached User/Membership
  objects while another transaction revokes the user, disables the user, or
  downgrades the role, then require current authorization to fail. These model
  authority changes during an import business-lock wait. They are **unexecuted
  here** and must be checked on the coordinator's DB before any defect/pass
  claim. Static inspection suggests an identity-map freshness risk because
  active-row queries may return a cached role without refreshing attributes.
  Shared identity code belongs to the local auth owner; QA did not modify it.
  P01 remains the only schema/reset path.

The approved dependencies were cherry-picked explicitly; QA changed no
application implementation, registration or migration files. Source dependency
SHAs and the final tested QA source are recorded in the evidence JSON.

## Bounded checkpoint results

- Independent backend cases: **73 passed, 5 actual-DB cases skipped**.
- Full backend regression suite without DB credentials: **747 passed, 218
  skipped**. No failures. Skips remain DB/Redis/historical-cassette gates; they
  do not establish migrated-schema or provider completion.
- Independent checkout/storage/API rules: **16 JavaScript tests passed**.
- Independent Chromium tests: **6 passed**, serialized on 4319: three preview
  authority/cart/text checks and three explicitly mocked HTTP failure/retry
  journeys. The mock codec is internal test data and does not implement or claim
  the pending canonical catalogue.v2 contract.

Reproduce the owned checks from the repository root:

```sh
.venv/bin/python -m pytest backend/tests/test_v1_wave2_*.py -q -ra
node --test frontend/storefront/tests/wave2-checkout.test.mjs
frontend/storefront/node_modules/.bin/playwright test --config=artifacts/v1/F20/local-review/playwright-qa.config.mjs
```

The browser command uses the installed Playwright browser, or the explicitly
configured `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. Its config never reuses another
server. No physical-device, registered native-session/CSRF, real publication,
canonical SKU checkout, payment-provider or integrated import DDL acceptance is
claimed. Those remain coordinator/product gates in the matrix above.

Per-checkpoint source SHAs, exact commands, counts, failures and limitations are
stored under `artifacts/v1/F20/`. Missing dependencies and DB/provider access
remain explicit skips/pending gates; a test that has not run is not a pass.
