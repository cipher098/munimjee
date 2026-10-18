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
| `finish_claim` after final live guard and stale-capture check, in the draft/audit transaction | Validate bounded exact original bytes, SHA256/MIME and media association again. Adopt the provider owner's reviewed existing-table proposal: `ImportAsset` rows use claim tenant/creator and `uuid5(job.id, 'instagram-original:' + asset.media_id + ':' + asset.sha256)`; replay verifies exact metadata/content. Flush the candidate first, then add proposed append-only `ImportAudit(action='instagram_assets_retained')` entries with tenant candidate/job FKs and `uuid5(job.id, 'instagram-manifest:' + str(candidate.id) + ':' + asset.media_id + ':' + asset.sha256)`. Canonical details contain only parent/child IDs, asset UUID, SHA, size, MIME and connection version. Original bytes, manifest, candidate and review-required transition commit atomically. Preserve job.asset_id's existing upload-input meaning. For initial IMAGE/VIDEO require one matching original; carousel stays gated. |
| `backend/app/workers/v1_imports.py:_drain` (17), `backend/app/v1/imports/runner.py:drain_jobs` | Construct the trusted provider/factory explicitly from existing approved Graph version configuration and session lifecycle. The runner already forwards `instagram_provider`, but the worker supplies none. Job-specific creator checkpoint must bind to the current claim without storing mutable shared job state in a serial-global provider. A reviewed provider factory or job-bound wrapper is preferable; preserve serial bounded recovery, worker engine disposal and feature gate. No import-time credential/network work. |

The proposed application-append-only manifest was independently reviewed against provider commit
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

## Bounded manifest follow-up — schema, readers and writer fencing

Reviewed after QA commit `5d986084750bb441d7a312a554c8e63e7b50aea8`, against
actual model/0046 DDL and CSV32a2d11. The proposal fits existing required columns
without a migration, but **immutable is a required application contract, not an
existing import-table guarantee**. No UPDATE/DELETE-prevention trigger exists for
ImportAsset or ImportAudit. The asset CHECK verifies nonempty bytes, exact length,
at most 5,000,000 bytes, MIME membership and lowercase 64-character hash shape; it
does not recompute SHA256 or verify the media signature. The shared hook must do so.

The audit has real composite foreign keys `(business_id, job_id)` to ImportJob and
`(business_id, candidate_id)` to ImportDraft. Its JSON `details.asset_id` has **no
foreign key** to ImportAsset. Nor do those FKs enforce job/candidate source-media
association, nonnull manifest job/candidate IDs, creator membership, or current
connection generation. `actor_id`/`creator_id` reference User, not a tenant-scoped
Membership. Those relationships remain explicit validated application invariants.
Do not treat manifest-only assets as unreferenced because `ImportJob.asset_id` is
null; any future cleanup must preserve their JSON references and retained history.

Exact insertion shape, after the final credential/lease/creator guard and after
excluding stale captures, is:

```python
# Pseudocode only. No shared hook implemented by this QA lane.
# locked_job.authorized_at is the accepted job's source-authorization timestamp.
# verified_* values come from exact bytes revalidated inside this guarded path.
asset_key = uuid5(locked_job.id,
    "instagram-original:" + original.media_id + ":" + verified_sha256)
asset = ImportAsset(
    id=uuid4(), business_id=locked_job.business_id,
    creator_id=locked_job.creator_id, idempotency_key=asset_key,
    content_type=verified_mime, sha256=verified_sha256,
    size_bytes=len(original.content), content=original.content,
    authorized_at=locked_job.authorized_at,
)
# On existing tenant+asset_key: reuse its ID only after exact content/metadata,
# creator and authorization-time verification; do not INSERT or overwrite it.
# Flush the accepted candidate and new asset before inserting this audit.
manifest_key = uuid5(locked_job.id,
    "instagram-manifest:" + str(candidate.id) + ":" + original.media_id
    + ":" + verified_sha256)
manifest = {
    "contract_version": "instagram-owned-manifest.v1",
    "parent_media_id": locked_job.source["media_id"],
    "asset_media_id": original.media_id,
    "asset_id": str(asset.id), "sha256": verified_sha256,
    "size_bytes": len(original.content), "content_type": verified_mime,
    "connection_version": verified_connection_version,
}
audit = ImportAudit(
    id=uuid4(), business_id=locked_job.business_id,
    job_id=locked_job.id, candidate_id=candidate.id,
    actor_id=locked_job.creator_id, idempotency_key=manifest_key,
    request_hash=digest(manifest), action="instagram_assets_retained",
    details=manifest,
)
# Same tenant+manifest_key replays only after action/job/candidate/actor/hash
# and canonical details match exactly. Any collision fails the transaction.
```

Both tables enforce uniqueness only on `(business_id, idempotency_key)` in addition
to their IDs. `instagram_assets_retained` fits the existing VARCHAR(32), which has
no action enum/CHECK or automatic action handler. Existing `_replay` consumers for
review/cancel/retry expect `details['result']`; this manifest has no command result.
Use a distinct typed internal replay path and namespaced keys, not those DTO replay
consumers. The catalogue bridge also rejects a command key already in ImportAudit.
All details must be JSON primitives: serialize UUIDs to strings before `digest`,
which has no UUID fallback serializer. Never hash or embed asset bytes in JSON.

Current import GETs expose jobs and candidates only. There is no original-byte or
manifest reader, and `import_catalogue.create_draft` consumes supplied `photo_urls`,
not retained ImportAsset originals. A future private reader must authorize current
`catalogue.read`, select audit by tenant+candidate+manifest action, resolve its job
under the same tenant, then select asset by **tenant and parsed asset UUID together**.
Cross-check parent media/account against that Instagram job, candidate source/media
and provenance, original child association (single media ID must equal parent while
carousel remains gated), canonical manifest digest, MIME, length and recomputed byte
hash. Recompute and compare both deterministic idempotency keys from the trusted
job/candidate/media/hash rather than treating the manifest's child ID as proof by
itself. Reject missing/malformed/mismatching relationships. Current-original selection
uses the accepted candidate's `last_job_id`; historical manifests require explicit
historical-job context, not greatest audit timestamp. Do not return arbitrary bytes
merely because an audit JSON object names a globally existing UUID.

Keep all asset/manifest inserts after `stale_capture_ignored`'s early continue.
Candidate, originals, manifests and job transition form one rollback unit under the
existing tenant/job serialization. A completed job does not fetch again; a fenced
old lease creates no records. Same-job/media/hash uses existing exact records;
new job/content creates a retained historical version. Never overwrite/delete an
old original, replace a seller override, or reuse lease-token keys for manifests.

Credential writers require a separate coordinated correction before final-guard
proof is complete. Native `channel_connections.disconnect` and `finish_instagram`
increment connection version through `locked_access`/`state_for`; legacy writers
`api/routes/auth.py` (token connect at lines 228–231, OAuth at 380–383) and
`workers/refresh_tokens.py` (41–42) update account/token/expiry without compatible
explicit connection-version increments. Those sources are unchanged by CSV32.
Every reconnect/revoke/refresh/bootstrap writer must share reviewed lock ordering
with the final importer guard, including the relevant Seller and connection-state
rows, and increment the authoritative version when credential binding changes.
After a network gap, re-read fresh scalars and compare-and-set the expected prior
account/token-or-fingerprint/expiry/version before applying refresh/OAuth results;
otherwise an old refresh can overwrite a disconnect. A row lock at importer finish
cannot establish this invariant when other writers bypass the same fence. Do not
persist tokens/fingerprints in manifests or imply that new importer locks repair
existing writers. Actual concurrent-session verification remains a P01 gate.

CSV0053 only widens the asset MIME CHECK to include text/csv; it adds no asset JSON
FK, append-only enforcement, reader or action handler. The provider-specific hook
must still allow only JPEG/PNG/MP4 and preserve CSV authorization, MIME mismatch,
document identity, created_at capture and stale/replay semantics already listed.

Follow-up evidence: `manifest-contract-check.py` and its JSON output record **18
passing source/ORM-metadata assertions**, exact hashes and the synthetic manifest.
These are not migrated-PostgreSQL constraint tests. Exact command from repo root:

```sh
env -u TEST_DATABASE_URL -u TEST_LANE -u TEST_DB_RESET /tmp/munimjee-release-ci-py311/bin/python artifacts/v1/instagram-owned-qa/manifest-contract-check.py > artifacts/v1/instagram-owned-qa/manifest-contract-check.json
```

No shared runtime, test suite, DB, credential, provider or production behavior was
changed by this follow-up. Previous pytest counts remain the earlier snapshot.
