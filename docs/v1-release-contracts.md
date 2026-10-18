# Bounded V1 release engineering and acceptance audit

Base `3082f1a`, application `dd36b0d`, 18 October 2026. Preserve the locally
verified recovery fixes and all earlier checkpoints. Every worker is explicitly
configured GPT-6.1 Sol/high. This batch does not authorize deployment, live DB
writes, secret access, provider calls, service restarts or infrastructure deletion.

## Ownership

| Lane | Branch / worktree | Owned files |
| --- | --- | --- |
| CI and reproducible package | `codex/v1-release-ci` / `munimjee-wave5-ci` | `.github/workflows/`, `scripts/v1_runtime_package.py`, `scripts/smoke_v1_runtime.py`, `deploy/v1/`, dedicated package/release tests and `docs/v1-release-ci.md`, `artifacts/v1/release-ci/` |
| Disposable rehearsal | `codex/v1-release-rehearsal` / `munimjee-wave5-rehearsal` | New `scripts/v1_release_rehearsal.py` and supporting release-only modules, dedicated tests, `docs/v1-release-rehearsal.md`, `artifacts/v1/release-rehearsal/` |
| Independent acceptance audit | `codex/v1-release-audit` / `munimjee-wave5-audit` | New audit docs/matrix/artifacts and independent release safety tests only; read peer implementation without editing it |
| Coordinator | `codex/v1-release-coordination` | This ownership contract, integration/review and aggregate release evidence/report |

No lane modifies product code, models, migrations, recovery UI, backend requirements,
support/sales access, analytics, customer identity links or the shared go-live plan.
Any required shared interface change is reviewed by the coordinator first.

## CI and package boundary

Preserve explicit source/static allowlists, secrets/tests/uploads exclusions,
nonroot runtime, default-off flags, incomplete-package refusal and CID-bound smoke
cleanup. Add immutable dependency/base/action references and validation where
feasible; package reproducibility and image reproducibility are distinct claims.
Keep the existing Python3.11 runtime unless a separate compatibility decision is
needed. Runtime-only lock/constraints belong under `deploy/v1/`; do not change
shared backend dependency pins in this batch. New CI uses ephemeral hosted runners,
least permissions, synthetic disposable PostgreSQL16 fixtures and P01 guards;
never production credentials, self-hosted runners or deployment actions.

Unexecuted workflows and multiarch manifests remain pending. Current reference
versions must be verified against primary sources; never invent immutable hashes.
Coordinate rehearsal CI composition only after its executable interface is frozen.

## Disposable rehearsal boundary

Default mode is a reviewable plan with zero DB/container effects. Execution, if
implemented, requires explicit disposable source and distinct empty restore target,
numeric-loopback URLs, matching exact `munimjee_test_<lane>` names and held P01
leases for the whole operation. No production fallback or implicit dotenv reads.
Do not create/drop databases, use `pg_restore --create/--clean`, overwrite backups,
or run cleanup against unowned resources. Backup/restore output and command
evidence must not expose URLs/passwords/data; private archives stay0600 and are
never committed as public artifacts.

Application rollback and destructive schema downgrade are different. A routine
rollback must preserve post-cutover orders, reservations, identities and pending
actions; never restore an old snapshot over newer transactions. Prefer a fail-closed
schema compatibility/forward-fix rehearsal and target-only offline SQL planning to
unsafe automatic downgrades. Any actual mutation stays within explicitly allocated
synthetic resources, and actual execution is pending if no lane is provisioned.
Reuse existing P01 guards/leases without weakening their policy.

## Independent audit and evidence

Audit all V01–V13 outcomes, actual-product matrix rows, G0–G6 gates and migration/
rollback criteria against the exact integrated source and saved evidence. Separate
source implementation, actual migrated/native evidence, simulated providers,
physical-device/live-provider gates and local-team work in progress. Do not flatten
these into a green release score or change scope to make the release appear done.
Competitor research is historical and does not need live provider access here.

Independently review CI permissions/dependency integrity, runtime determinism and
rehearsal fail-closed behavior. Send actionable findings to owners; report exact
source SHA, commands, passes/skips and remaining gates. Preserve historical evidence
without claiming that local PG16/container results were rerun remotely.
