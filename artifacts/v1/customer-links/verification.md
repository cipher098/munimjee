# Customer account-link verification

Final runtime source: `a7e6ce73f46099846caf11ff3ebc403951cc2f6d`.
Backend47 ran at `65f7a2c9159d7d024eebcef76528a5b120f8d78e`; every owned
backend/model/schema/API/test file and both shared ingress hooks are byte-identical
at the final runtime. The later change only scrubs residual count/checkbox state
on the existing native identity fence. Browser14 reran at the final runtime.

## Actual tests

`backend.txt` / `backend.xml`: **47 passed, no skips** in32.51s. This is14pure
command/strict-boolean checks,17real-PG service/schema/concurrency checks and16
real mounted-native HTTP/signature checks. P01 leased only `parcel_w3`, actual
`munimjee_test_parcel_w3`, PostgreSQL16 with the full real Alembic chain through
`0052_v1_customer_links`. Real0051 dependency159c525 and shared configea1a307
were consumed, never replaced by a fake predecessor or create_all. One existing
Pydantic class Config deprecation warning remains.

Evidence covers wrong account/sender/time/signature, expired/nonexact/attachment
proofs, per-provider-message replay, same-name records remaining separate before
proof, exact receipt replay, no browser verified assertion, native CSRF, inaccessible
tenants, source-pagination boundaries and current role after aggregate reads.
Concurrent finalization of two challenges for the same endpoints creates only one
customer/pair. Proof/audit are DB-immutable with tenant composite FKs. Canonical
lookup rejects unlink/reconnect/source/flag changes during its last binding await;
scalar binding reads preserve unrelated unflushed Seller/WA facts. Current native
session revocation while waiting for a challenge lock and after real staged audit
flush rolls back creation/finalization/cancellation/unlink respectively. Unlink
preserves old conversation/history and does not grant messaging consent.

`browser.txt` / `browser-results.json`: **14 mounted Chromium journeys passed**
at finalruntime. The harness imports actual app.main after test flags, with the
integrator-owned router/model/signature-hook composition; no manual product router
mount. A disclosed test-only owner-guarded fixture seeds synthetic inbox records
and synthetic configured accounts, not a real connection. HMAC requests then run
through the real signed IG/WA webhook handlers. No provider or customer is contacted.

The journeys exercise two independent proof arrivals, wrong sender, repeat event,
zero canonical customers before explicit finalize, explicit audited unlink,390px
layout, dropped/unclassified409/422/wrong-key200 after real committed creation,
exact body/key reload recovery with one request, dropped finalize recovery with one
customer, typed nonaccepted stale context, denied storage zeroPOST, native expiry,
same-user login replacement, role downgrade, double-submit journal serialization
and older successful guard released after a known real session change (zeroPOST).
External browser requests and page errors are empty. No new sender/outbox path exists.

The first browser run caught a real mobile refresh/confirmation race: a pending
refresh could reset a newly checked review checkbox. Product controls now wait
through the complete refresh; the failing log is preserved as
`browser-initial-failure.txt`. It contains no secret. Subsequent full runs passed.

Commands, with the exact P01 lane allocation and shared read-only Python3.11:

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_customer_links.py backend/tests/test_customer_links_db.py backend/tests/test_customer_links_http.py -q
PYTHONPATH=backend python -m tests.run_customer_links_browser
```

## Captures and privacy

- `desktop-one-proof.png`:1365px fullpage, only one consent proof, explicitly unverified.
- `mobile-verified-link.png`:390x844 selected-pair/detail viewport after explicit finalization.
- `mobile-unlinked.png`:390x844 retained proof/audit history viewport after unlink.
- `mobile-session-ended.png`:390x844 after real native session revocation; private DOM cleared.

Before proof screenshots, tests use the real **Hide consent command** control,
which empties `#consent-command` and hides `#command-panel`. No test-only token
mask or product-code redaction is used. The session-ended test checks empty secret,
customer pair/history/count DOM and cleared review checkbox. Text artifacts were
scanned for raw43-character consent commands; none occur. Images were visually
inspected: no raw command, no layout clipping, restrained incumbent green/type/native
form system. Source hashes, asset byte sizes, capture policy and evidence hashes are
in manifest.json. No new visual identity or accessibility certification is claimed.

## Independent review

Integrator source review found and resolved current-association lookup after binding,
retained ORM overwrites, stale can_manage projection and explicit private headers.
Final bounded source/render verdict: **SHIP** at a7e6ce7 /65f7 backend. The integrator
inspected desktop one-proof, mobile verified/unlinked and secret-free captures;
control/consent scope and current Unlinked state are clear. Final fence scrub was
also accepted. This is an independent integrator review, not author certification.

This worker separately read-only reviewed explicit support schema/contract/router/
services. A final-allowlist board metadata race and its cursor tail were identified
and fixed by the integrator; the final source recheck has no remaining bounded
member/impersonation/write-escape blocker. Support35/integrated97 execution belongs
to the integrator and was not rerun or claimed as this worker's result.

## Boundaries and handoff

The feature remains default-off. Proof verifies control/consent for two seller-scoped
channel endpoints, not legal-person identity, marketing permission, payment access
or historic ownership. No message/order is moved, no combined history is passed to
automation, and no challenge is automatically sent or finalized. Signed synthetic
requests prove application wiring only: approved live provider/customer-consent
canary, deployment/cutover and any expanded context/authority policy remain pending.
Existing private connector/D1/TLS, camera and provider-template gates are unchanged.

Shared registration/hooks/static/nav/cleanup are integrator-owned and consumed as
dependencies. Central full suite/runtime image and independently mounted final
composition remain integrator release gates. Port8156 was released after the run;
8155 was not bound in this slice. The borrowed node_modules symlink is removed,
leaving the shared dependency directory untouched.
