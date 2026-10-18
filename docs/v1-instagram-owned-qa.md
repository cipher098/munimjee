# Owned Instagram durable-pipeline QA

18 October 2026. Independent QA base `3f01ae1b8f0296df8c761d9ce52b534aa6b74b9a`.
This lane owns new pipeline tests, this document and its bounded evidence folder.
Provider source and shared runtime are read-only. No live Meta request, token read,
DB allocation, Docker action or release action occurred. Fake provider evidence is
simulated workflow evidence. Full V03/V04 and V1 acceptance remain open.

## Read and scope checkpoint

Read the coordinator's `docs/v1-instagram-owned-contracts.md` at `0523488`, the
entire `go-live-plan.md`, current import service, runner, worker, schema, domain,
asset models and unchanged P01 harness. Separately inspected CSV contract and
shared service at `32a2d11fb51293402dd814eb3c4216327e5eec5a` on
`origin/codex/v1-csv-import`; none of that branch was merged.

The frozen provider keeps `fetch_owned_media(*, business_id, account_id, media_id)`.
The new `OwnedMediaResult` adds original asset bytes/hash/MIME beside the existing
matching account/media and products. Default `OwnedMediaCapabilities` leaves
Instagram Login media and carousel disabled. Synthetic tests explicitly enable
their tested capability. An Instagram media placeholder is not a discovered
product count: `(("media-product", DraftFacts()),)` preserves all unknown facts.

## Current verified boundary

The existing shared service derives account ID from trusted access at job creation,
not from a caller-supplied credential/account field. It rechecks creator access and
account ID before fetch and at final persistence. Tenant locks, lease fencing and
deterministic source identities survive retries. Network I/O is outside short
claim/check/finish transactions. Results enter private review-required drafts.

The shared service does **not** persist added `OwnedMediaResult.assets`. Successful
provider byte retrieval alone therefore does not establish durable original-media
retention. `test_original_media_result_is_not_falsely_persisted_by_existing_seam`
demonstrates the boundary: only a draft/audit is added, with no ImportAsset or
job asset association. Signed CDN URLs must never become provenance or identities.

Current `_fresh_access` returns only role and `Seller.instagram_page_id`. Thus the
existing final guard independently fences membership revocation/account-ID changes,
but does not prove rejection after same-account reconnect/generation change, token
expiry, or token removal with the account ID retained. Provider rechecks close
retrieval gaps; they do not atomically authorize later DB writes. These remain
explicit shared integration gates below.

## Reviewable shared patch proposal — not applied

Apply only through the local shared owner after reviewing the final adapter DTOs.
No code in this lane modifies these targets.

| Target and current anchor | Required change and invariant |
| --- | --- |
| `backend/app/services/imports_v1.py:AccessSnapshot`, `_fresh_access` (current lines 58–86), `JobClaim`, `claim_job` | Obtain an Instagram-specific trusted connection proof from fresh scalar projections under the existing business lock. Bind business, current Seller account ID, `ChannelConnectionState.provider_account_id` and version, token presence and expiry. Validate active Business/Seller and current creator User/Membership/capability. Snapshot generation into the claim; never accept it from HTTP input. Do not weaken the common access snapshot for website/upload/CSV paths. Explicitly reject missing/ambiguous connection state until a coordinated compatible bootstrap policy is reviewed. |
| New trusted runtime credential-loader callback, owned by local integration; provider calls it with business/account only | Open its own short session and read fresh committed scalar columns with `autoflush=False`, rather than retained Seller/identity-map objects. Require active Business/Seller, matching Seller account and connection-state account/version, nonempty token and future expiry. Validate current creator/job through a job-bound checkpoint closure. Load/decrypt only through the application's actual authorized credential handling; current model stores a string, so do not invent a decryption format or new credential table. Return `OwnedCredentialSnapshot` with redacted token. `granted_scopes=None` remains unknown unless verified storage supplies it; do not fabricate grants. No dotenv/environment or alternate-DB fallback. |
| `check_claim` (379), `finish_claim` (398) | While holding the existing tenant/job locks, compare fresh current connection proof against claim generation/account and require current token presence/unexpired access. A same-account reconnect, cleared token or expiry after fetch must discard all candidate and asset results atomically. Keep current state/token/lease/time fence first, then creator access. Provider final callback alone cannot replace this guard. |
| `collect_claim` (342), `run_job` (451) | Preserve keyword fetch seam, ownership comparison and bounded stable product keys. Carry verified original assets in a typed collection envelope to final persistence instead of silently dropping them. Normalize Instagram typed errors to a reviewed fixed allowlist; never persist arbitrary `.code`, raw provider text, caption or CDN URL. Retain `provider_capability_pending` before credentials/network while official route acceptance is disabled. Keep the existing outer timeout and recovery semantics. |
| `finish_claim` after final live guard and stale-capture check, in the draft/audit transaction | Validate bounded exact original bytes, SHA256/MIME and media association again. Adopt the provider owner's reviewed existing-table proposal: `ImportAsset` rows use claim tenant/creator and `uuid5(job.id, 'instagram-original:' + asset.media_id + ':' + asset.sha256)`; replay verifies exact metadata/content. Flush the candidate first, then add immutable `ImportAudit(action='instagram_assets_retained')` entries with tenant candidate/job FKs and `uuid5(job.id, 'instagram-manifest:' + str(candidate.id) + ':' + asset.media_id + ':' + asset.sha256)`. Canonical details contain only parent/child IDs, asset UUID, SHA, size, MIME and connection version. Original bytes, manifest, candidate and review-required transition commit atomically. Preserve job.asset_id's existing upload-input meaning. For initial IMAGE/VIDEO require one matching original; carousel stays gated. |
| `backend/app/workers/v1_imports.py:_drain` (17), `backend/app/v1/imports/runner.py:drain_jobs` | Construct the trusted provider/factory explicitly from existing approved Graph version configuration and session lifecycle. The runner already forwards `instagram_provider`, but the worker supplies none. Job-specific creator checkpoint must bind to the current claim without storing mutable shared job state in a serial-global provider. A reviewed provider factory or job-bound wrapper is preferable; preserve serial bounded recovery, worker engine disposal and feature gate. No import-time credential/network work. |

The immutable manifest proposal was independently reviewed against provider commit
`d5ab4588b651f917fd92f38c5ffc7f1fd8a7f8a6`. Its source hashes match the tested
read-only assembly. Byte-identical same-job retries replay the asset/manifest;
different job/content yields retained source versions, preserving prior originals.
Skip originals/manifests alongside `stale_capture_ignored` rather than attaching
obsolete output to a newer candidate. Signed URLs are never source versions. The
local review API/UI must implement tenant-scoped manifest/byte readers before
claiming accessible retained originals. An import attachment and later catalogue
media bridge are separate proofs; do not claim storefront originals until the bridge
carries the retained original correctly. No automatic approval/publication follows.

## CSV and recovery preservation requirements

CSV32a2d11 keeps the Instagram branch but inserts CSV handling before uploaded media.
Integrate additively, never replace the service with the older QA/provider base.
Preserve all of the following exact semantics:

- CSV source identity is `csv-document:{document_id}` plus exact trimmed
  `product_ref`, namespaced by tenant; not filename, upload hash or row order.
- Original CSV bytes stay in tenant-owned ImportAsset. Candidate evidence records
  upload SHA and record line, not raw arbitrary cells. Preserve `text/csv` handling
  and the separately ordered migration `0053 → 0052`; this lane reserves no migration.
- Non-CSV job hashes continue excluding CSV-only document fields, preserving
  pre-existing exact-key replays. CSV/media upload MIME mismatch rejection and
  the separate `CSVSourceError` handling precede generic adapter error mapping.
- `claim_job` captures immutable CSV at `job.created_at`, while fresh adapters keep
  retrieval claim time. Starting an older queued CSV later cannot make it newer.
- `finish_claim` keeps `stale_capture_ignored` before `reimport_candidate`; seller
  overrides, review decisions and newer provenance survive older results.
- Persisted pending rows, lease-expiry reclaim, at most three attempts, pre-fetch
  access checks, cancellation/retry revision checks and runner's bounded serial
  dispatch remain unchanged. Latest recovery semantics are not replaced.

## Tests and gates

`test_v1_instagram_owned_pipeline.py` uses real service/domain functions and fake
provider/DB boundaries. SQL assertions independently require tenant bindings. It
covers body authority exclusion, current account selection, account/media mismatch,
bounded/duplicate results, unknown placeholder facts, candidate identity, overrides,
stale captures, cancellation/revocation/lease/account fences, transaction-free fetch,
credential-free failures, expired-attempt recovery and runner provider forwarding.

`test_v1_instagram_owned_pipeline_db.py` uses unchanged P01 `migrated_engine` and
actual Alembic migrations, with no `create_all`, allocation or alternative URL.
One reimport/private-state path and five after-fetch final-guard cases skip explicitly
when no disposable database is separately allocated. Skips are pending evidence.

`test_v1_instagram_owned_pipeline_provider.py` reads the actual adapter through
the normal package import after reviewed composition, or through the evidence
command's read-only source-path assembly. It exercises synthetic transport through
the actual provider into `collect_claim`/`run_job`/`finish_claim`, including original
bytes/hash, unknown facts, default capability denial before credentials, final
credential mutation/cancellation rejection, separately gated carousel, and final
shared account rejection after adapter success. On the uncomposed QA branch its
11 cases explicitly skip; assembly passes them. No Graph version support is
inferred from the synthetic version string `v99.0`.

The adapter's fixed `instagram_*` failures currently become `source_adapter_failed`
inside shared `run_job`, because its allowlist has not been integrated. This is
credential-safe but loses actionable expiry/reconnect distinctions. Only
`provider_capability_pending` already crosses unchanged. Review the adapter's
`ERROR_CODES` explicitly rather than accepting every future provider code.

The independent security owner owns official API/source documentation and transport
threat QA. Primary developers.facebook.com media pages are currently 429/login
blocked; no third-party substitution closes that gate. `/me` professional-account
proof, Instagram Login media-field eligibility, children/carousel behavior, versions,
permissions and authorized real seller/media retrieval still require primary and
explicit live acceptance. Native UI and physical-device acceptance also remain open.

Latest commands, counts, skips and exact source hashes are saved under
`artifacts/v1/instagram-owned-qa/`. No release-ready claim follows these tests.
