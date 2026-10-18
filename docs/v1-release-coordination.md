# Bounded release engineering handoff

18 October 2026. This batch starts at `3082f1a` and preserves application
`dd36b0d` and its latest recovery fixes. Product code, migrations, direct backend
dependency pins and the shared go-live plan are unchanged. Local support grants,
customer identity links and analytics remain separately owned work.

The release branch combines immutable CI/runtime inputs, deterministic source
archives, a guarded synthetic restore tool and an independent acceptance audit.
It is not a deployment or a release-ready declaration.

## Independent coordinator checks

- Python 3.11.16 with the hashed test closure: final backend regression at `000d0fd`
  **896 passed, 562 skipped**, zero failures/errors. Database/provider-dependent
  cases remain skipped; this is not a migrated database run.
- Focused CI/package/P01 selection: **119 passed, two actual DB cases skipped**;
  actionlint 1.7.12 exited zero on the composed workflow. This selection overlaps
  the full backend run and is not an additional acceptance total.
- Reviewed restore tooling through `0e2996f`: **38 passed, one actual PostgreSQL
  acceptance skipped**. Checks cover refusal paths, private files, schema writer
  protections, child timeout/cancellation ownership and synthetic reconciliation.
- JavaScript contracts: **77 passed**, zero skipped/failed.
- Clean runtime context: **288 files**. Two uncompressed archives matched after
  differing umasks and context timestamps. Source/content/archive hashes are in
  `artifacts/v1/release-coordination/archive-check.json`. This proves source
  archive determinism for the recorded commit, not reproducible OCI images.
- All three workers and the coordinator were verified as GPT-6.1 Sol/high;
  recorded turn metadata is in the coordination artifact directory.

Raw backend and rehearsal JUnit records are retained under
`artifacts/v1/release-coordination/`. Counts describe distinct checks and should
not be summed into a product acceptance score.

Separate pushed worker branches are `codex/v1-release-ci` at `5b4cc41`,
`codex/v1-release-rehearsal` at `0e2996f` and `codex/v1-release-audit` at `9a417c9`.
The coordinator cherry-picked their reviewed commits into
`codex/v1-release-coordination`; the final verification JSON records full worker
SHAs and the tested composed source. Every source digest in the peer review
matches the composed files. A preliminary 887-pass backend record is retained
with its earlier source SHA; it is superseded by the final 896-pass record.

## Execution boundaries and blockers

The initial hosted run `39105746311` failed workflow validation before jobs.
The corrected workflow created four jobs in run `39105879610`, but GitHub blocked
every job before its first step: **“The job was not started because your account
is locked due to a billing issue.”** No hosted test, image build or database job
executed. No account/billing settings were changed and no manual rerun was
requested. Source pushes can trigger workflows automatically; further execution
remains subject to that external billing condition.

The release worker's single six-second Docker availability probe timed out.
There were no further probes, service restarts or workaround deployments. Hashed
Linux cp311 runtime wheel downloads succeeded for amd64 and arm64; neither a
wheel download nor a registry manifest establishes image startup on that arch.

The restore tool defaults to a plan without DB/container effects. Actual execution
requires two explicitly allocated, initially empty PG16 lanes, both P01 leases,
private ownership attestation, explicit PG16 tools and a new private archive
directory outside Git. It never creates/drops databases, resets arbitrary
schemas, overwrites backups or restores an old snapshot over newer orders.
Its SQL read probe is not an earlier application binary compatibility test.

To close the remaining release engineering gates, the local integrator must run
the mandatory migrated P01 test and full backend suite, mounted native journey,
native amd64/arm64 image build/offline smoke, and the opt-in two-lane real restore
acceptance. An actual approved old/current application switch or forward-fix
journey preserving post-cutover facts is a separate open gate. See
`docs/v1-release-ci.md` and `docs/v1-release-rehearsal.md` for exact commands.

## Acceptance and evidence provenance

The independent 58-row audit retains V01–V13, all 23 acceptance rows, G0–G6,
migration/rollback and cross-cutting criteria. Implementation gaps include the
owned Instagram media adapter, CSV fallback, current-SKU automated responses and
sitemap/legacy redirects. Provider/device approvals, operational readiness and
local-team product work remain additional gates. Conditional Dharaa migration
requires its international criteria or retention of the existing route.

Historical local **1,417 passed / eight skipped** PG16 results remain historical;
they were not rerun here. The saved import harness digest belongs to
`47b1b83`, whose change improves screenshot capture, while application source is
`dd36b0d`. This is separate application/harness attribution, not a demonstrated
product defect. The minimal refresh for that attribution alone is the 47-check
native import journey on the final candidate with pre/post application and
harness hashes plus a capture manifest. Historical artifacts are preserved.

No production access, provider calls, live routing/DNS changes, secret reads,
shared service restarts, destructive infrastructure operations or deployment
were performed by this batch.
