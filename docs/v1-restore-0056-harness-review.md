# Independent 0056 release harness review

Review base `4d9f940d25e681fd6a80e168f4ea4c0510131fbd` (current accepted producer composition through `875cdf7`, plus prior source-only proposal). Branch `codex/v1-restore-0056-harness-review`; ownership only this document and `artifacts/v1/restore-0056-harness-review/`. Runtime, scripts and tests are read-only in this lane.

Current accepted runtime is `a9880c56b6a8bf7b4e20f54837a362e4432aadda`: execution status records2441 passed/eight documented skips/zero failures on actual0056 with825 stable tracked files. Producer installation/report proof is now accepted within its separately documented limits. The earlier fixture proposal's “unaccepted producer” caveat describes its old36535c8 baseline; it is not the current producer disposition. A directly seeded source-ledger fixture remains data restoration evidence only, even with installed producers.

## Criteria before implementation

The proposed owner scope is release scripts and a new fixed in-repository JSON fixture only: explicit0056 head, exact locked version/SHA and bounded shape;35 new retained rows/52 total source/58 target after finite post-cutover additions. No arbitrary fixture path/input or data sanitization claim can select a source. All financial/full-row/schema reconciliation and original source preservation remain required.

Accept only the exact0055 `comment_action_event_tenant` NOT VALID metadata: public namespace; ordered seller/event keys to public.comment_events seller/id; FK type, exact definition, MATCH SIMPLE, NO ACTION update/delete, nondeferrable/not deferred, false validation state. Every other constraint must be validated. No global bypass, trigger disabling, convenience validation or schema/runtime writer change is accepted. Compare stable identifiers, never OIDs; do not strip quotes, schema distinctions or case globally. Existing `canonical_constraint` literal-array cast normalization and quoted identifier/string/comment fences must remain unchanged.

The future actual FK probe must preserve transaction boundaries: snapshot reads can autobegin, so cleanly end that transaction before opening the rollback-only probe, and finish it before final read-only export. Positive pending-event/public and negative **different** unknown-event/public actions use fresh UUIDs/unused pairs; temporary sellerB satisfies scalar seller/event FKs without a unique collision. Only SQLSTATE23503 with diagnostic `constraint_name=comment_action_event_tenant` counts. Always roll back failed savepoint and outer transaction, including success/failure/cancellation paths; compare full before/after snapshots, not only row counts. Repeat source and target. Historical offender counts/aggregate digests are read-only and must survive restore; no offender repair/deletion is authorized.

Nullable legacy JSON proof/claim fields must bind SQL NULL. Attempted bound comment states must be staged pending→sending→unknown/sent with stable claim/token/time/receipt, not inserted or reset as runnable terminal work. New target activity receipt/order provenance and enquiry command/closure append preserve old records and financial totals; fixed historicalSTAMP is insertion-after-backup, not a newer-created-at claim.

## Original safety boundaries reviewed

`targets`, `ownership`, `archive_location`, `private_file`/`private_read`, `child_env`, `command`, `owned_call`, `pg_tools`, `empty_database`, `pg16` and `v1_release_exec.main` were read directly. The contract retains two distinct initially empty PG16 P01 lanes; strict URL/attestation ownership; archive outside Git with no symlinks, private0600/exclusive opens and no overwrite; target emptiness recheck immediately before restore; exported read-only source snapshot; bounded subprocess/file size; no create/clean/downgrade; lease scope spanning migration/dump/restore/failures and cancellation-draining before release. Failure may leave owned files/data, and must not trigger cleanup/reset/deletion.

Baseline function/file hashes are recorded before candidate edits. Candidate review must compare these guards and the quoted-token normalizer, inspect any changed orchestration, verify source/target/probe ordering, and ensure no secrets or subprocess output is published on failure.

## Finite independent test review

QA proposes exact known-FK metadata positive and bounded mutations, diagnostic/savepoint/outer-rollback flow, locked fixture/NULL/staged-state/count/relationship/totals checks, validator corruption refusal and snapshot/aggregate mismatch tests. Existing P01/private archive/lease/cancellation/schema/quoted-token checks remain, with only necessary head/new catalogue projection adapters. Exact additions await owner row shapes and root freeze; no tests are authored by this review lane.

Expected assertions must be independent literals/mutations, not production expected objects echoed by a fake. Fake repository/transaction rows can establish algorithm/control flow only; they cannot prove PostgreSQL schema/constraint enforcement, actual transaction rollback, pg_dump/pg_restore, retained data, tool/capacity readiness or old/current package compatibility. Actual acceptance remains explicitly unrun/blocked. No redundant green rerun is planned without a concrete review concern.

## Checkpoints

Implementation and QA checkpoints were pending at the initial review; exact final checkpoints are reviewed below. No application, test, harness, DB, container, tool installation, daemon, capacity retry, credential, provider/model or actual restore was executed by this review.

## Candidate source review

Initial candidate `992c8bf88704545117ca17b3dbc12b8f41412f15` changes only the two release scripts plus fixed `scripts/v1_release_fixture_0056.json`. Fixture version1 locks SHA256 `1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3`. Its records, source counts/totals and complete target append are structurally identical to the approved proposal. The loader reads only that fixed no-follow regular file, bounds it to64KiB, checks the literal digest/format/version/table/column layout and UTC top-level timestamp fields before any DB/tool effect. JSON None stays SQL NULL. No caller-selected fixture or application configuration is introduced.

The owner retains legal staged bound actions, source52/target58 exact count/financial/semantic projection checks, append-only native reviews and historical fixed timestamps. Full original table/schema snapshots remain in addition to the selected semantic projection digest. Historical offender rows remain private inputs to a count/digest, never repaired. The accepted producer update does not change the meaning of direct fixture ledger rows.

### R01: duplicate raw constraint definitions defeated PG16 equivalence handling

The initial `schema_fingerprint` hashed raw `pg_get_constraintdef` again in the new `constraint_metadata` inventory, even while the original constraint inventory retained its narrow canonicalization. A valid PG16 literal varchar-array CHECK reparse would therefore still change the overall schema digest. Existing tests of `canonical_constraint` alone would not catch the duplicated path. This was reported promptly to root, owner and QA as a concrete restore compatibility blocker, without executing a database.

Owner correction `bd24f74e541147713f0edf160f0faf5af9df03a2` first validates the known FK's raw exact metadata, then applies the **unchanged** narrow `canonical_constraint` to the duplicated metadata definition before hashing, as it already does to the original inventory. It does not strip quoted identifiers, change case/schema distinctions or accept another NOT VALID. The source correction is appropriate; QA was asked for a whole-schema original/reparsed digest-equality regression plus a protected quoted distinction. That test's fake catalogue boundary must remain explicit.

### Source safety disposition

Independent immutable-byte comparison confirms20 pre-existing rehearsal functions—including P01/ownership/private archive/environment/subprocess/cancellation/PG16/empty-database/normalizer/main guards—and `v1_release_exec.py` are unchanged. Changed `run` validates head/fixture before tools/engines/files, seeds and commits before source FK probing, then enters read-only snapshot export. Target is rechecked empty and committed immediately before restore; its probe runs before restored equality. The post-cutover52→58 stage is validated before the read-only probe, and original source equality is rechecked at the end. No create/clean/downgrade/cleanup or runtime writer appears.

`probe_comment_fk` refuses an existing transaction, snapshots then rolls back its initial read, creates an explicit outer transaction, inserts the valid first event/public action and temporary seller, and tests a distinct second event/public action in a nested savepoint. `fk_error` requires SQLSTATE and constraint name on the same exception in the SQLAlchemy/asyncpg wrapper chain, not message text. Nested and outer rollback run in finally blocks; `rollback_owned` shields/drains cleanup under cancellation. After rollback, the full snapshot must equal the pre-probe snapshot and that read transaction is also rolled back. Source/target probes preserve full data/schema state rather than only count equality. These are source observations, not executed PostgreSQL enforcement or rollback proof.

No other source blocker found at the corrected candidate. Final QA and R01 regression review follow below.

## Final QA/evidence review and disposition

No remaining scoped blocker for source/unit preflight. Exact owner source is `992c8bf88704545117ca17b3dbc12b8f41412f15` plus R01 correction `bd24f74e541147713f0edf160f0faf5af9df03a2`. Owner source-only preflight evidence is `5270afe687d716160ce167a99087957df8326d3a`; its source/guard hashes also match. QA tests are `b57d5ea4999fd4fe3185bd7b524701e56eab7da2`; QA documentation/evidence is `6d78f4467736094f0098652bd6f0a1c60d8c4408`. Coordinator canonical source is `049019b2105a855f88a33149f7a2e4db49d7ceae`. All three owner source/fixture files and the three QA test files match across immutable owner/QA/coordinator Git blobs and the coordinator checkout.

| Exact file | SHA256 |
| --- | --- |
| `scripts/v1_release_rehearsal.py` | `1e7a6a32d8ed483f6e90c355e736431c7c7e6c78f17050681878da93af4adbe2` |
| `scripts/v1_release_synthetic.py` | `551a69e2d7586328e125cec840a06d0113f3815fe98ce4352f303b7a04111577` |
| Locked fixture version1 | `1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3` |
| `tests/release/test_v1_release_0056.py` | `e0b36022bca3023461b17f7245eadd9df05e9c15843a885d9d1aebfe18e20364` |

The root-approved finite49 additions are meaningful within their declared boundaries. R1 uses an independently transcribed15-field FK literal plus missing/altered/extra-NOT-VALID mutations. Its two whole-schema cases exercise both definition inventories, require equivalent cast reparses to hash equally and protected quoted-identifier changes to differ; they close R01's source/unit path. R2 independently pins distinct pending/public and unknown/public event IDs, new action UUIDs and temporary seller binds; transaction markers are restored only when the actual rollback calls occur. Correct, wrong/missing and absent diagnostics, positive-write failure and cancellation exercise success and refusal cleanup. R3 independently specifies count/totals/fixture lock/NULL/staged statements/target append and invokes actual semantic hashing on explicit raw rows. R4 changes a raw enquiry contact link, runs actual `semantic_state`, preserves aggregate counts and still reaches validator digest refusal. R5 injects different snapshot components and verifies orchestration order, held lease markers, archive reuse refusal and no success evidence after failures. None of these fake catalogue/SQL/transaction/engine boundaries is a PostgreSQL implementation or restore oracle.

Independently verified all50 original assertion ASTs unchanged except the approved0053→0056 head literal. The old test-file adaptations add only the probe stub needed to reach its pre-existing lease failure episodes and exact new catalogue rows needed for schema fingerprint assertions. Prior quote/cast, private archive, P01, redaction, lease/cancellation and writer-protection assertions remain. Compatibility test bytes are unchanged. All22 recorded unchanged function/class hashes and the exec helper match the base; owner and QA change no backend runtime/migration/test files.

QA final raw XML records **107 passed, 1 skipped, 0 failures/errors**, including49 new units. The existing53 release case slots include the one actual acceptance skip;52 executed prior release cases +6 compatibility units +49 new units =107 passes. Root's separately sanitized canonical three-file run records the same107/1 in0.38s. Its plan output records exact0056/version1/locked fixture/source52/target58 and no DB/container effects. I verified both XMLs, every QA raw artifact/document hash and canonical invocation/plan/text/XML hashes without executing another unit run. Root's invocation explicitly disables actual acceptance and supplies no target URLs; QA used an empty safe environment without opt-in/URLs. The first QA107/1 output remains diagnostic for its earlier uncommitted assertion version, as disclosed; the final committed-test result is authoritative.

Final verification is under `artifacts/v1/restore-0056-harness-review/final-verification.json`. It records immutable source/test hashes, R01's correction, old-assertion/guard audits, exact result/skip accounting and canonical artifact hashes. No separate failing run of the initial R01 candidate was executed or inferred.

**Actual acceptance remains blocked/unverified:** PostgreSQL catalogue projection and exact FK new-write enforcement, real savepoint/outer rollback, trigger-compatible populated source52 and target58, PG16 tools/two fresh owned lanes, actual dump/restore/schema/row parity, historical offender evaluation, mounted old/current package compatibility and routine rollback/forward preservation. The reported capacity/daemon/tool blockers were not retried. No actual restore, provider/model, credential, install/service/container or production action occurred in this review. Passing source/unit preflight is not0056 restore success or release readiness.
