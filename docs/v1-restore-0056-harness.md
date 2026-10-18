# Fixed 0056 release rehearsal harness

This harness supports only `0056_v1_comment_operator`. Source preparation does not
establish a new backup/restore, application switch, image, or rollback result.
Actual execution remains blocked by the previously recorded capacity/tool/daemon
limits; this lane performs no DB allocation, capability retry, installation,
container, provider, credential, sender or production operation.

Accepted application evidence remains separate: the frozen `a9880c5` composition
passed 2441 tests with eight known skips on actual0056 and 825 stable tracked files
(`docs/v1-wave7-producer-validation.md`). The reviewed proposal predates that
producer acceptance. Its retained direct seed remains **synthetic history**, not
proof that an installed producer created those rows.

## Files and fixed fixture lock

Only `scripts/v1_release_rehearsal.py`, `scripts/v1_release_synthetic.py` and new
`scripts/v1_release_fixture_0056.json` implement this change. No application,
migration, test, P01 safety helper or subprocess execution helper is changed.
The fixture is a fixed sibling file with format `munimjee.release-fixture.0056`,
integer version1 and a literal SHA-256 in the synthetic module:

`1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3`

There is no manifest argument, mutable artifact lookup, environment selector or
application-config import. The loader opens the leaf without following symlinks,
requires a regular file of at most64KiB, verifies the digest before parsing, and
checks exact top-level keys, fixed table/column order, row counts and explicit UTC
timestamp conversion. Null JSON proof/claim fields bind SQL NULL, rather than JSON
null. Nested JSON timestamps stay exact strings. Claim hashes use only the reviewed
public fixture key represented by the fixed template; this is not real webhook or
account authentication. Command fingerprints are synthetic retained lexical values.

The existing0053 fixture remains unchanged. The fixed extension adds35 rows across
17 tables, yielding52 source rows across32 populated tables including Alembic.
All other public tables must remain empty and still participate in fingerprints.
The attempted unknown/sent actions first INSERT accepted/pending with SQL NULL
claim/attempt/receipt/finalization fields, then use permitted pending→sending→final
updates. Legacy proof/claim fields remain NULL. The lossy context uses its allowed
false→true transition. No trigger disabling or worker/provider action occurs.

After restore equality, the target receives the original newer paid order and
reservation, four approved activity/operator history rows, and one legal policy
revision1/test→revision2/off update. Target then has58 rows. The fixed Jan1 order
stamp is preserved; later insertion does not mean a later `created_at`. Historical
context/source retention ends Apr1: these are retained, retention-expired records,
not fresh collection or retention-readiness evidence. No cleanup runs.

## Phase ordering and protections

1. Validate exact migration head and fixed fixture before tools, engines, private
   output or database effects. `plan` reads source metadata and fixture only.
2. Retain both existing distinct allocated P01 leases; verify both empty PG16
   databases, then migrate only the source through the incumbent P01 migrator.
3. Seed and commit the fixed source. At a clean transaction boundary, perform the
   source rollback-only FK probe and verify its full snapshot remains unchanged.
4. Export a validated52-row repeatable-read/read-only source snapshot and create a
   bounded private dump. Recheck the empty target, then restore in one transaction.
5. At the clean target boundary, perform the same rollback-only FK probe. Validate
   the target counts/semantic fields/financial totals and exact equality with source.
6. Append only the finite target history, commit, and validate58 rows and exact
   financial/state expectations. Freeze this full target snapshot.
7. A generic read-only SQL probe must preserve every target digest and newer order;
   the source must still equal its original52-row snapshot. Private evidence retains
   both snapshots and probe results. An actual old/current application journey is
   explicitly pending; no schema downgrade or snapshot overwrite is performed.

Each snapshot preserves bounded full sorted JSON rows, duplicate multiplicity,
all IDs/fields, schema protections, sequences and financial/reservation integrity.
New semantic checks compare the fixed field projection against independently loaded
reviewed templates, including exact tenant, source, claim, audit, command/member,
order/time, enquiry/contact/message and closure associations. Scoped state counts
retain pending1/unknown1/sent1/legacy1, three bound claims/two attempts/one synthetic
receipt/eight audits, disabled rule/opted-out contact and no WA outbound. The target
closes only the second enquiry, preserves original outcomes and adds no sends.

Source financial totals remain orders2/placed2500/paid1250/reservations2/quantity2/
stock8; target becomes orders3/placed3750/paid2500/reservations3/quantity3/stock7.
Unknown payments1/open manual actions1/COD-collected0 remain unchanged.

## Exact NOT VALID exception and rollback-only enforcement

The known `public.comment_actions.comment_action_event_tenant` must be the exact
nondeferrable/not-initially-deferred, unvalidated MATCH SIMPLE/NO ACTION FK from
ordered `(seller_id,event_id)` to `public.comment_events(seller_id,id)`.
`validate_constraint_metadata` checks15 stable catalog fields, including the exact
rendered definition under controlled `pg_catalog, public` search path. Missing,
duplicate, validated or altered known-FK metadata, and any other NOT VALID
constraint, refuse. No quote, case or schema stripping occurs. Exact raw FK
validation precedes use of the unchanged narrow `canonical_constraint` on ordinary
duplicated definition fields. A review caught and corrected the initial duplicated
raw-definition fingerprint mismatch in `bd24f74`.

`probe_comment_fk` first snapshots and rolls back the read's implicit transaction.
Its explicit outer transaction inserts a valid same-tenant public action and a
temporary second Seller. A nested savepoint attempts a distinct public action on
the unknown event across tenants; both scalar FKs resolve and event/kind identities
avoid a uniqueness collision. Only SQLSTATE23503 **and** diagnostic constraint name
`comment_action_event_tenant` on the same wrapped exception leaf count as success.
The savepoint and outer transaction always roll back, including wrong errors,
unexpected success, positive-probe failures and cancellation. Rollback tasks are
shielded and drained before returning. A final full snapshot must equal the first;
no probe row or temporary Seller is committed.

`historical_offenders` independently reads the composite tenant/event LEFT JOIN
and retains count plus digest of sorted complete offending rows, without exposing
raw IDs/rows publicly. Restore/read snapshots must preserve it. The fixed fixture
requires zero offenders; arbitrary nonzero historical datasets are unsupported,
never relinked, deleted, validated away or silently accepted by this fixture.

## Verification and remaining gates

Initial source `992c8bf88704545117ca17b3dbc12b8f41412f15` plus correction
`bd24f74e541147713f0edf160f0faf5af9df03a2` pass source-only plan and in-memory Python
compilation. `artifacts/v1/restore-0056-harness/` records exact source hashes,
protected-function preservation, fixed counts and raw plan output. QA owns all unit
assertions and necessary old-head/fake-catalog updates; its independent results are
recorded separately when available. No synthetic row hash is presented as an actual
PostgreSQL restore digest.

The original quote-aware normalizer, P01 ownership/allocation/empty-lane guards,
private archive/no-overwrite/size limits, sanitized child environment, one-writer
lease lifetime and cancellation-drained subprocess logic remain unchanged. Actual
PG16 trigger/driver/schema behavior, dump/restore, packaged old/current read journey,
production rollback/cutover and complete release acceptance remain unrun here.
