# Current0056 restore preparation handoff

18 October 2026. Preparation base: pushed `36535c8`. Accepted full backend remains
`eeb94a1`/actual0056; scoped UI `e4183cf` has separate mounted evidence. Backend
and migration bytes at this preparation base match `eeb94a1`. Local unpushed
producer `a9880c5` is excluded. **No actual restore, image build or rollback
ran in this task.**

## Capability blocker

The arm64 host has16GiB RAM, but its data volume is98% full. Initial `df` showed
4.8GiB free; the final preparation read showed4.81GiB. Timestamped byte values
are retained in the capability artifact. This does not establish ample rehearsal
headroom.

Docker client29.7.2 is installed at `/Users/user/.docker/bin/docker`. Its current
local Unix socket exists, but the server-version probe timed out after8seconds.
A bounded direct read-only `GET /_ping` on that socket returned
`HTTP/1.0 503 Service Unavailable`. No healthy daemon/server version is verified.
No PG16 server, `initdb`, `pg_dump`, `pg_ctl` or `psql` is on PATH or in the
checked Homebrew16/Postgres.app16 installation prefixes/Cellar paths. Spotlight
found only unrelated repository directories named `initdb`; none was executed.
This is not an exhaustive host-wide absence claim.

There is no verified safe existing toolchain/headroom for an isolated instance,
so no launch proposal or instance was created. No install, shared service start,
daemon/billing change, database/container allocation or cleanup occurred. A future
launch first needs accessible existing PG16 tools and ample disk, followed by
local-integrator review of exact owned directories, ports, lanes, memory and
network restrictions. It must use a fresh disposable source/target pair and
private archives, never an existing restore target or production data.

Exact capability observations and the only plan-mode diagnostic are in
`artifacts/v1/restore-0056-preparation/`. The existing plan invocation exits1:
its reviewed `SUPPORTED_HEAD` is0053 while repository source has sole head0056.
It reads migration metadata only; no database/container operation ran.

## Reviewed fixture delta

The named GPT-6.1 Sol/high independent reviewer compared0053→0056 with the fixed
seed/count validation, generic full-row/schema fingerprints, newer-order stage
and old/current package-read harness. The concrete source-only manifest retains:

| New family | Proposed retained records | Added rows |
| --- | --- | ---: |
|0054 activity | Policy/receipt/context, two events, one gap, two order provenance links, one source ledger |9 across7 tables |
|0055 comment safety | Disabled rule; bound pending/unknown/sent events/actions; one legacy-unbound review event/action; eight append-only audits |17 across4 tables |
| WA backing records | One synthetic contact and two exact inbound messages |3 across2 tables |
|0056 operator review | Two no-send command receipts, comment review, open/closed inferred enquiries and one closure |6 across4 tables |

Together with the existing17 rows in15 populated tables, the proposal has52
source rows in32 populated tables. Existing financial/reservation/pending totals
stay unchanged. Attempted comment states must use legal
pending→sending→unknown/sent transitions; direct attempted inserts, claim resets
and replay are forbidden. The source ledger is directly seeded synthetic data,
not evidence that the uninstalled channel producers ran.

After a future restore, the incumbent target-only order/reservation adds2 rows.
A bounded extension adds4 more rows: its order provenance, activity policy
receipt revision2, a new enquiry-close command and closure. The current policy
row makes its permitted revision transition. Proposed target total:58 rows.
All unknown/sent claim tokens, provider receipts and audits stay untouched.
The complete target snapshot must remain unchanged across any later approved
old/current read stage. This is preparation, not an executed package switch.

The incumbent fixed January timestamp is historical retained synthetic data and
may be outside the90-day retention window. It is not a fresh retention-guard
test. Order activity must match the actual order creation timestamp, context
windows and classification; policy history must not retroactively relabel it.
The reviewer manifest supplies concrete templates, dependency/transition order,
count maps, time relationships and reconciliation expectations.

Exact independent review checkpoint: `c0688726d77b99899b72781c8c56eb5c8f6bdd53`
on `codex/v1-restore-0056-review`, composed here as `92786f9`. Root independently
verified all27 immutable source hashes, model AST field names, count arithmetic,
public-fixture claim/event/body hashes, exact source/command/enquiry relations,
time windows and unchanged runtime/schema/tests/harness. These are static proposal
checks, not SQL constraint, trigger or restore tests. The final manifest is
`artifacts/v1/restore-0056-preparation/final-verification.json`.

## Required conservative harness review

Advancing `SUPPORTED_HEAD` alone is insufficient. The old strict populated-table
map rejects the new retained rows. The generic snapshot already fingerprints
every table, but domain totals/count/state invariants must accompany the new
seed data. No existing harness or supported-head constant was changed here.

Migration0055 deliberately creates `comment_action_event_tenant` on
`public.comment_actions (seller_id,event_id)` referencing
`public.comment_events (seller_id,id)` as `NOT VALID`, preserving historical
tenant mismatches while protecting new writes. The current fingerprint routine
requires every constraint to be validated, so it conflicts with this intentional
schema state even on a fresh0056 migration.

The proposed review must keep exact source/target metadata equality: constraint
name, table/columns, referenced table/columns, foreign-key type, actions,
deferrability, definition and expected `convalidated=false`. Every other
constraint must remain validated; any extra/unexpected unvalidated constraint
or changed definition/state is a refusal. Do not remove the validation gate
globally or mutate/validate the historical constraint as a shortcut.

A future actual isolated run must verify valid new inserts succeed and invalid
cross-tenant inserts fail with SQLSTATE23503 naming this exact constraint, using
rollback savepoints on both owned source and target. Probe rows, including a
synthetic second tenant needed to isolate this composite FK, must leave no
lasting row changes. Report any historical offenders through read-only counts
and private identity digests; preserve their exact source/target rows and
metadata. Do not normalize, delete or validate shared legacy data. The fixed
fixture does not claim to populate historical cross-tenant corruption.

## Evidence boundary

See [independent fixture review](v1-restore-0056-fixture-review.md) and its retained
record manifest for exact fields and source references. Root verifies those
templates/counts/hashes against immutable source before composition. No broad
synthetic suite was repeated. No provider, model, real credentials, production
target, previous archive or evidence deletion was involved.

This closes only the finite capability/fixture preparation task. Current-head
restore/backup tools, real SQL triggers/constraint enforcement, current image,
old/current mounted compatibility, rollback/forward fix and release acceptance
remain unexecuted gates. The generic read-only probe is not old-writer or
production rollback proof.
