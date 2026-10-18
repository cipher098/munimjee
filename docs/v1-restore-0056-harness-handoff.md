# 0056 release harness source/unit handoff

18 October 2026. The release-only implementation is complete against accepted
integration `875cdf7`; **actual0056 PostgreSQL restore remains BLOCKED / NOT RUN**.
No application, migration, service, database, container, installation, provider,
credential, deployment or capacity retry operation accompanies this packet.

## Composition and behavior

Branch: `codex/v1-restore-0056-harness-coordination`.

| Original checkpoint | Coordinator composition | Purpose |
| --- | --- | --- |
| `992c8bf` | `6ea5189` | Fixed0056 fixture, exact constraint policy, rollback-only probes, reconciliation |
| `bd24f74` | `a3e2a50` | Correct duplicate ordinary constraint definition normalization |
| `5270afe` | `0504d1f` | Implementation source/preflight evidence and limits |
| `b57d5ea` | `049019b` | Independent49-case unit addition and necessary legacy fake/head adaptations |
| `6d78f44` | `b9d69c2` | Independent QA results, hashes and boundary disclosures |
| `7f84a7b` | `5baa1d6` | Independent source review and normalization finding |
| `2df095d` | `fda0676` | Final independent test/evidence review; no source/unit blocker |

The reviewed `d96cba5` preparation and fixture proposal are retained, pinned to
their historical source and capability snapshot. The current accepted producer
composition `a9880c56b6a8bf7b4e20f54837a362e4432aadda` (reported2441pass/8known
skips,825 stable tracked files) is separate evidence. These direct synthetic
inserts do not execute that producer path.

The fixed sibling JSON is format `munimjee.release-fixture.0056`, integer version1,
SHA-256 `1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3`.
It adds35 reviewed retained rows to yield52 source rows across32 populated tables.
The original newer target-only paid order/reservation plus four history records
yield58 target rows; one permitted policy update adds no row. Financial totals,
pending/unknown/sent/legacy claims, no-send consent and exact retained associations
are checked explicitly alongside full-row/schema fingerprints. Historic Jan1
records and expired retention timestamps do not imply fresh collection readiness.

The single intentional NOT VALID tenant FK requires all15 stable catalog fields
exactly; every other unvalidated constraint is refused. Raw known-FK validation
precedes the unchanged narrow PG16 literal-cast normalizer. Future source/target
probes require a positive same-tenant write and the exact cross-tenant
SQLSTATE23503/constraint diagnostic, then rollback savepoint and outer transaction
even on failure/cancellation. Historical offenders contribute full-row sorted
count/digest evidence and are never repaired or deleted; this fixed fixture
requires zero. Existing P01 leases, empty-target checks, private archive controls,
restore targeting, subprocess cancellation draining and no-overwrite guards remain.

## Verification

The canonical composed run at `049019b2105a855f88a33149f7a2e4db49d7ceae` passed
**107 tests, zero failures, one explicit actual-PG16 acceptance skip** in0.38s.
Independent QA passed the identical final source/test bytes107/1 in0.34s. These
are overlapping executions of108 cases, not214 unique passing tests. Source-only
plan and in-memory compilation also pass. No harness/test source changed after
the canonical run.

Independent review verified the corrected source, fixture/preflight, both exact
test/result packets, retained guard/assertion hashes and documented fake boundaries.
It found no remaining scoped source/unit blocker and ran no redundant test suite.

The frozen49 additions cover20 exact metadata/normalization cases,7 diagnostic
and rollback cases,8 fixture cases,7 reconciliation cases and7 historical-offender/
orchestration cases. Existing50 assertion ASTs remain unchanged except the reviewed
head literal. Original quote/lease/archive/P01/schema guard assertions remain.
Catalog/SQL/transaction/engine responses are declared fakes: these checks establish
construction, refusal and cleanup control flow, not actual PostgreSQL enforcement,
trigger-compatible insertion or dump/restore parity.

The original release baseline57pass/1old-head failure/1actual skip is preserved.
Independent review found the initial duplicated raw definition fingerprint defect;
the correction and two whole-schema regression cases are retained. There is no
claim of an executed red test run against that initial source candidate.

Evidence and review:

- [Implementation and preflight](v1-restore-0056-harness.md)
- [Independent QA](v1-restore-0056-harness-qa.md)
- [Independent review](v1-restore-0056-harness-review.md)
- `artifacts/v1/restore-0056-harness-coordination/`: raw baseline/canonical results,
  exact invocation/source/test hashes, plan, protected-source audit and final manifest.
- `artifacts/v1/restore-0056-harness-qa/`: independent raw first/final results,
  fixture/assertion audit and hash manifest.
- `artifacts/v1/restore-0056-harness-review/`: independent source, test and evidence audit.

## Remaining actual acceptance boundary

Suitable isolated PG16 tools and an explicitly allocated empty P01 source/target
pair with enough host headroom are still required. The earlier host/tool/disk/daemon
blocker is time-stamped historical evidence; it was not retried here. Real seeding,
new-write FK enforcement and rollback, catalog SQL, historical-offender SQL,
pg_dump/pg_restore and source52/target58 database digests are unverified.

Actual old/current package compatibility, mounted application switch, rollback/
forward preservation, image/deployment and full release acceptance remain separate
unrun gates. Historical0053 actual restore evidence remains historical. Do not
restore an older snapshot over newer financial/target-only facts or relabel this
source/unit handoff as an actual restore success.
