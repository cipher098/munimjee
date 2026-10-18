# Disposable V1 release rehearsal

This release-only tool implements a guarded synthetic backup/restore acceptance
path at the exact repository migration head, currently `0050_v1_assistance`.
It changes no product models, migrations or P01 policy. Default invocation:

```sh
python scripts/v1_release_rehearsal.py
```

The default and explicit `plan` action read migration source only. They import no
application configuration, read no dotenv file, spawn no subprocess and connect
to no DB/container. Their reviewable output is saved in
`artifacts/v1/release-rehearsal/plan.json`.

## Executable ownership contract

Actual execution is explicitly opt-in. Before running it, the operator allocates
two **different, initially empty** PostgreSQL 16 databases with distinct P01 lane
names. This tool never creates/drops a database, truncates/resets a schema, runs
`pg_restore --create`/`--clean`, downgrades a schema or cleans external resources.
A previously used or partly restored target is refused on the next invocation;
provision a fresh owned pair. The operator is responsible for any later cleanup.

The caller supplies only these two connection environment variables, with simple
synthetic credentials, exact numeric loopback hosts (`127.0.0.1` or `[::1]`), an
explicit port and exact `munimjee_test_<lane>` database names:

- `REHEARSAL_SOURCE_URL`: P01 `postgresql+asyncpg` URL for the allocated source.
- `REHEARSAL_TARGET_URL`: the same URL form for the separate allocated target.

There is no `DATABASE_URL`, admin URL, `.env`, service, passfile or production
fallback. All original P01 validation rules apply, including refusing query
options, DNS names, encoding, unusual loopback spellings and xdist workers. Both
existing P01 session advisory leases are held until reconciliation/evidence
writing finishes, and also across migration/dump/restore failure. A conflicting
lease refuses execution. This is a cooperative exclusion mechanism: the owner
must not attach an application/worker or another non-P01 writer to either DB.

Write an owned regular **0600** JSON attestation outside the repository. Exact
fields are required; use the two allocated lane names and the allocation owner:

```json
{
  "format": "munimjee.release-ownership.v1",
  "source_lane": "release_src",
  "target_lane": "release_dst",
  "synthetic_only": true,
  "allocated": true,
  "owner": "release acceptance job"
}
```

Then invoke this concrete interface with absolute paths:

```sh
python scripts/v1_release_rehearsal.py execute \
  --source-lane release_src --target-lane release_dst \
  --attestation /private/allocated-ownership.json \
  --archive-dir /private/new-release-rehearsal-directory \
  --pg-bin /absolute/postgresql16/bin
```

Do not paste connection strings into arguments or public logs. The private archive
directory must not already exist; its parent must exist and be owned or sticky.
Private paths cannot contain symlinks or parent traversal. The tool creates the
directory 0700 and archive/evidence files 0600 with exclusive no-follow opens.
It never overwrites a backup. Dumps are limited to 64 MiB using the child process
file-size limit, and subprocesses have a 180-second timeout. SQL statement and
lock timeouts are 120 seconds and 5 seconds. No subprocess stderr/row data is
published, even on failure. Child libpq credentials are passed through a minimal
private environment, never argv; inherited provider credentials, PG service and
passfile configuration are excluded. Do not commit the dump or private evidence.

## Actual execution sequence

1. Validate explicit inputs and private ownership without connecting. Verify the
   explicitly selected `pg_dump` and `pg_restore` each report PostgreSQL 16.
2. Acquire both unchanged P01 leases; verify both server majors are 16 and both
   DBs contain no non-system objects. Empty tables are insufficient.
3. Run the existing guarded P01 Alembic migration entry point on the **owned
   empty source** while both leases remain held. Seed only fixed deterministic
   synthetic fixture values from `scripts/v1_release_synthetic.py`. This narrow
   interface deliberately does not accept arbitrary existing source data based
   solely on an operator's assertion that it is sanitized.
4. Verify the exact current head and expected synthetic table counts/totals. Hold
   a read-only repeatable-read source transaction, export its snapshot and pass
   that snapshot to actual `pg_dump`. No source write follows the fixture setup.
5. Recheck target emptiness immediately before actual `pg_restore`, which uses
   one transaction and exits on error, with no owner/privilege restoration.
6. Compare every public table's count and hash of sorted full JSON rows, covering
   every ID/value and duplicate multiplicity. Compare column/constraint schema
   fingerprints and require validated constraints. Reconcile order counts,
   placed/paid/COD-collected totals separately, reservations/quantity, unknown
   payment attempts and open manual actions. Check order arithmetic and tenant
   reservation links. Public output includes only counts/totals/digests, never
   row content. Table/row/data bounds fail closed.
7. Insert a third, newer **target-only** synthetic paid order and reservation.
   Exercise read-only compatibility reader contracts and require the complete
   target snapshot to stay unchanged, including that newer order. Recheck the
   source snapshot unchanged. Write private evidence and release both leases.

Actual success reports `restore: passed` only after the real tools and restored
DB reconciliation complete. A failed or interrupted operation can leave owned
private files, a migrated source or a restored target. There is deliberately no
cleanup command that might mistake an external resource for an owned one.

## Application rollback and forward fix boundary

The compatibility probes are SQL read contracts over a current schema, **not an
actual prior application binary switch**. Both profile names are explicit probe
labels; they do not establish that any earlier application commit is compatible.
Evidence therefore keeps `application_switch` pending even when real restore
and compatibility checks pass. The target-only newer order test demonstrates
that these read probes preserve post-cutover facts; it cannot prove old writers,
background jobs, routing, cache or frontend behavior.

To close that separate gate, the release owner must supply immutable prior/current
application packages, reviewed schema/API/writer compatibility, disabled provider
side effects and an isolated mounted journey that creates a post-cutover order,
switches to the approved compatible package (or forward fix), and reconciles the
new order, reservations, payment evidence, identities and pending actions. Keep
one authoritative writer. If old writers cannot preserve these contracts, stop
and build a forward fix. Do not apply migration downgrade SQL or restore an older
snapshot over newer orders as routine application rollback. Offline SQL planning
must stay target-only and requires separate review before any mutation.

## Validation and remaining gates

Pure/fake-transport tests:

```sh
python -m pytest -q tests/release/test_v1_release_rehearsal.py
```

The optional real acceptance test is the same actual execution path, with no
fake transport and no implicit allocation. It is skipped unless
`REHEARSAL_ACCEPTANCE=1`, then requires the two URL variables plus
`REHEARSAL_SOURCE_LANE`, `REHEARSAL_TARGET_LANE`, `REHEARSAL_ATTESTATION`,
`REHEARSAL_ARCHIVE_DIR` and `REHEARSAL_PG_BIN`:

```sh
REHEARSAL_ACCEPTANCE=1 python -m pytest -q \
  tests/release/test_v1_release_rehearsal.py::test_actual_pg16_backup_restore_and_newer_order_preservation
```

The caller must allocate the empty DB pair before invoking this test. A missing
or unsafe input fails rather than skipping once acceptance is explicitly enabled.
Do not combine this acceptance with backend conftest's single-lane socket guard:
run this dedicated test file as its own process.

Local status on 18 October 2026: **27 pure/fake-transport checks passed, one actual
PG16 acceptance skipped**. No allocated pair or explicit PG16 installation was
provided. The known remote Docker hang was not probed or restarted. Actual
`pg_dump`/`pg_restore`, hosted CI, actual prior/current application rollback and
forward-fix mounted journeys remain pending. Earlier wave-4 local PG16 acceptance
is historical evidence and is not a run of this new rehearsal.
