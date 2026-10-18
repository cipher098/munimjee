# Release-only0056 harness implementation contract

18 October 2026. Base: pushed `875cdf7`, accepted complete backend
`a9880c56b6a8bf7b4e20f54837a362e4432aadda`/actual0056 (reported2441pass,
8known skips,825 stable files). Earlier `d96cba5` preparation is imported with
its pinned historical source/capacity evidence intact. Its35-row retained
proposal remains the specification; new accepted producer wiring is current,
while direct fixture inserts still do not exercise producers. No migration or
release-harness source changed between the proposal base and this base.

## Allowed ownership

Reuse existing clean worktrees and named GPT-6.1 Sol/high workers. No new
checkout copy, service, database, container, tool installation or capacity retry.

| Worker | Branch | Exclusive writes |
| --- | --- | --- |
| `instagram_provider` | `codex/v1-restore-0056-harness` | `scripts/v1_release_rehearsal.py`, `scripts/v1_release_synthetic.py`, new fixed `scripts/v1_release_fixture_0056.json`, `docs/v1-restore-0056-harness.md`, `artifacts/v1/restore-0056-harness/` |
| `instagram_contract_qa` | `codex/v1-restore-0056-harness-qa` | Necessary head/fake-catalog adaptation in existing `tests/release/test_v1_release_rehearsal.py`, new `tests/release/test_v1_release_0056.py`, `docs/v1-restore-0056-harness-qa.md`, `artifacts/v1/restore-0056-harness-qa/` |
| `instagram_security` | `codex/v1-restore-0056-harness-review` | `docs/v1-restore-0056-harness-review.md`, `artifacts/v1/restore-0056-harness-review/`; scripts/tests read-only |
| Root | `codex/v1-restore-0056-harness-coordination` | This task, final handoff, release-only `docs/v1-release-rehearsal.md` update, `artifacts/v1/restore-0056-harness-coordination/`, reviewed composition |

No application, migration, dependency, existing execution-helper, package-switch
script or other runtime ownership. If another seam is necessary, identify it
before editing. No deployment, production/existing target, provider/model call,
credential access, snapshot overwrite, cleanup or deletion of prior evidence.

## Approved design and invariants

Support exactly0056 after a fixed format/version/SHA-256 fixture preflight.
The new JSON is a bounded, fixed repository file, not an arbitrary path or
mutable artifact dependency. Plan mode stays metadata-only with no app config,
database/container/process or private-file effects. The fixture extends exact
source counts to52 rows/32 populated tables and target-only counts to58;
financial/reservation/pending invariants remain explicit.

Preserve legal accepted/pending→sending→terminal action transitions and SQL NULL
for absent legacy JSON proof/claims. Full row/schema hashes remain authoritative.
Add independent semantic counts/relations for retained activity, comment and
operator/enquiry history. The four target-only0054/56 rows and one permitted
policy update follow the incumbent newer paid order/reservation stage.

Replace the all-validated constraint requirement only with a precise reviewed
exception for the expected `public.comment_actions.comment_action_event_tenant`
definition, ordered columns/references, actions, match/deferral and
`convalidated=false`; require every other constraint validated. Preserve exact
source/target metadata and the quote-aware canonicalizer; no quote/case/schema
stripping or arbitrary schema-diff normalization.

On each future owned source/target, use rollback-only positive and cross-tenant
insert probes with distinct unused event/kind pairs. Accept only actual wrapped
SQLSTATE23503 naming this FK. Wrong failures or unexpected success refuse. Both
savepoints and the outer transaction must roll back on every path, including
cancellation, leaving full data/schema/offender fingerprints unchanged.
Historical offenders are reported through counts/digests, never repaired or
silently accepted as arbitrary source data. The fixed synthetic source remains
strict; it is not permission to target a historical/shared database.

Phase order: preflight→hold both existing P01 leases→verify PG16/empty
source+target→migrate/seed→source probe/equality→read-only exported52-row
snapshot/dump→recheck empty target/single-transaction restore→target
probe/equality→full source/target reconciliation→58-row target append/validation
→read-only probe with target/source unchanged→private evidence. Preserve private
archives, no overwrite/create/clean targeting, bounds, timeouts, cancellation
draining, connection disposal and redacted errors. No automatic resource cleanup.

## Finite verification

QA additions are frozen to R1 exact constraint metadata/refusals; R2 probe
diagnostics/rollback/failure/cancellation; R3 fixed locked fixture, transitions,
NULLs/counts/relations/totals; R4 altered fixture/reconciliation refusals; R5
historical offender/snapshot/target mismatch and held-lease failure cleanup.
The initial47 cases are18 metadata,7 probe,8 fixture,7 validation and7 flow cases.
Independent review then reproduced a source defect: duplicated raw constraint
definitions bypassed the existing legitimate PG16 cast-reparse normalizer.
The narrow follow-up retains exact raw known-FK validation before applying the
unchanged canonicalizer to duplicate fields. Two approved whole-schema regression
cases bring the finite new total to49: literal cast-reparse equivalence and
quoted-identifier meaning distinction. No other expansion is included.
Preserve existing quoted identifier/schema-protection/P01/archive tests, adapting
only newly required head/projection fixtures. Independent review audits exact
patches and checks for fake-boundary assertions misrepresented as DB proof.

Run only release source/unit/preflight checks with a sanitized environment and
`REHEARSAL_ACCEPTANCE=0`. The real opt-in acceptance remains unrun/skipped and
blocked by the recorded capability limitation. No DB/container allocation or
capacity retry loop is permitted. Tests can establish refusal/flow behavior over
fake boundaries; they cannot establish PostgreSQL enforcement, restore success,
package compatibility or release readiness. Preserve initial failures and exact
source/harness/fixture/evidence hashes; do not substitute a green actual-restore
claim for source-only verification.
