# Independent 0056 release-harness QA

The focused release packet passes **107 tests, 1 explicit actual-PG16 skip, 0 failures/errors** in 0.34s, exit 0. It comprises the existing release 53 and compatibility 6 cases plus the frozen **49** new unit cases. No database, container, restore, tool installation, capacity retry, service, provider/model or credential operation ran. This verifies source/unit/control-flow contracts only; **actual0056 restore and old/current application acceptance remain blocked and unrun**.

Base is `875cdf7` plus reviewed proposal `c0688726d77b99899b72781c8c56eb5c8f6bdd53`, composed as `4d9f940`. The coordinator approved owner source `992c8bf88704545117ca17b3dbc12b8f41412f15` plus `bd24f74e541147713f0edf160f0faf5af9df03a2`, composed here as `c655759` and `93438ab`. Their three release harness/fixed-fixture files match owner bytes exactly. No app or migration was authored/changed here. QA-only preparation is `b57d5ea`.

## Frozen matrix and observed scope

The coordinator approved R1–R5 with 47 cases before test writes, then approved two finding-driven full-fingerprint cases (49 total). No other scenario was added.

| Group | Cases | Independent checks and observed result |
| --- | ---: | --- |
| R1 | 20 | Independently literal 15-field known FK plus ordinary validated constraint accepted; missing known, every one-field mutation and unrelated NOT VALID refused. Mutations cover schema/table quoting, case, ordered keys, FK actions/match/deferral/validation and exact raw definition. Full source/reparsed CHECK fingerprints agree through both inventories; a quoted-identifier meaning change produces a different digest. Controlled `search_path` is issued before catalog inspection. |
| R2 | 7 | Actual rollback-only probe function constructs positive pending/public action on the independently known pending event, then a different UUID/event on the unknown event with the temporary Seller. Wrapped same-leaf SQLSTATE23503 and exact constraint name accepted. Wrong SQLSTATE, wrong/missing constraint and negative success refused. Positive insert failure and cancellation unwind owned outer/savepoint markers without commit. |
| R3 | 8 | Fixed file version/literal SHA, independent source52/target58 counts/totals and approved record relations match. Actual semantic projection over scripted raw rows matches independent proposal-derived digest/counts. JSON SQL NULL remains `None`, not JSON `null`; actual seed SQL constructs pending→sending→final attempted actions. Target append constructs six inserts and only stock/policy updates. Fixed hash, format, symlink and size tampering refuse before tools/engines/archive. |
| R4 | 7 | Independent source/target snapshot inputs accepted. Altered count, unexpected populated table, financial total, semantic count and retained link digest refused. The link case changes a scripted raw enquiry/contact association, runs actual `semantic_state`, preserves aggregate counts and is rejected by the real fixture validator. |
| R5 | 7 | Historical-offender digest includes full rows, duplicate multiplicity and order-independent sorting, while exposing aggregate fields only. Actual orchestration function orders source probe→dump→restore→target probe→target58 append, compares source/target inputs, preserves source baseline and refuses archive reuse. Source/target probe failure, restored row-hash mismatch, target reconciliation mismatch and source drift retain both mocked leases through cleanup and write no success evidence. |

The initial candidate duplicated raw `pg_get_constraintdef` in its new metadata inventory, bypassing the prior narrow PG16 cast normalizer. Independent source review found this before QA composition. Owner `bd24f74` validates exact raw known-FK metadata **before** applying the unchanged canonicalizer to ordinary duplicated definitions. The two R1 fingerprint cases cover this concrete finding; direct helper tests alone would miss it. The known FK's quoted/case/schema variants still refuse. This packet does not claim a separately executed red run of the initial candidate.

The proposal's source financial contract remains orders2/placed2500/paid1250/COD0/reservations2/quantity2/unknown-payments1/open-actions1/stock8. Target58 preserves all pending/unknown/sent/legacy states while adding the newer paid order/reservation and four0054/56 facts: orders3/placed3750/paid2500/COD0/reservations3/quantity3/unknown-payments1/open-actions1/stock7. These are independently specified fixture/bind and reconciliation inputs, not observed PostgreSQL totals.

## Existing guards and exact permitted adaptations

The existing release test file changes only:

1. The literal plan-head expectation0053→0056.
2. A no-op source-probe boundary in its existing lease/failure fake, so that old failure episodes continue to reach their intended migration/restore points. New R2 independently exercises the actual probe's control flow.
3. Known-FK four-column and 15-column fake catalog rows in its existing schema-protection fingerprint fake.

No other old assertion was changed. Existing P01/no-fallback/distinct-target, private ownership/path/archive/no-overwrite, tool bounds, private environment/redaction, lease failure cleanup, subprocess cancellation, writer-protection digest and quoted-token/cast guards remain meaningful. Compatibility test bytes are unchanged. The original actual acceptance test remains opt-in and skipped. The new module also denies socket connect/connect_ex and DNS through pytest fixtures.

Source hashes verify that `canonical_constraint` and the existing safety/exec functions remain byte-identical to base. The retained proposal is source-only; it and the existing historical actual0053/0056 evidence are not relabelled as this run. The earlier coordinator baseline reportedly had57 pass/1 known old-head refusal/1 actual skip; it is not counted as a run by this lane.

## Boundary disclosures

R1 scripts raw catalog results; it cannot prove PostgreSQL's catalog projection/filter behavior. R2 replaces snapshot/insert/connection responses with recorded transaction markers and injected SQLAlchemy-wrapped driver errors; it proves diagnostic recognition, statement construction and cleanup calls, not actual FK enforcement or engine rollback. R3 records actual SQL/binds without executing inserts, triggers or transitions. Its semantic projection returns explicit approved raw JSON rows. R4 supplies independent synthetic snapshot inputs. R5 replaces engines, leases, tools, snapshots, seed/append and probe boundaries to test orchestration; its placeholder row hashes and synthetic archive are deliberately **not** database/dump digests. Only bounded private temporary filesystem operations and the existing private Python exec-helper unit ran outside process-local fakes.

All other NOT VALID constraints are refused; historical offending rows are hashed/read, never repaired or deleted. The fixed fixture's expected offender count is zero. No known FK is validated for convenience, no trigger is disabled, and no prior archive/target is overwritten. Source52/target58 equality and target-only preservation are source/control-flow assertions until an allocated actual PG16 pair executes the complete harness.

## Reproduction and evidence

The final run uses an empty environment with only safe runtime variables. `REHEARSAL_ACCEPTANCE`, target URLs, app/provider configuration and dotenv inputs are absent:

```sh
env -i PATH=/usr/bin:/bin TMPDIR=/tmp LANG=C /tmp/munimjee-release-ci-py311/bin/python -B -m pytest tests/release/test_v1_release_rehearsal.py tests/release/test_v1_application_compatibility.py tests/release/test_v1_release_0056.py -q -p no:cacheprovider -o junit_family=xunit1 --junitxml=artifacts/v1/restore-0056-harness-qa/results.xml > artifacts/v1/restore-0056-harness-qa/run.txt 2>&1
```

An initial107/1 pass preceded two stronger assertions within the same cases: pinning negative-probe binds to the actual temporary Seller/distinct reviewed events, and exercising actual raw-link semantic hashing rather than supplying an arbitrary wrong digest. Its raw output is preserved in `first-pass/` as diagnostic evidence; the final run at committed QA `b57d5ea` is authoritative. No assertion was weakened, skip added or scenario expanded. Final text/xunit1 XML, exact source/test/fixture/artifact hashes, preserved-old-assertion audit and case accounting are under `artifacts/v1/restore-0056-harness-qa/verification.json`.

Actual two-lane PG16 allocate/migrate/probe/dump/restore/reconcile, real FK new-write enforcement, historical offender evaluation, populated trigger-compatible insertion, old/current package and mounted compatibility, rollback/forward preservation, capacity/tool availability and deployment remain pending. No retry of the reported host capacity/daemon blocker was attempted. This is not restore/release readiness.
