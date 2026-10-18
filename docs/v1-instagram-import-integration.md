# Owned Instagram original integration

This extends the isolated provider contract into the real durable importer. The
production capability `V1_INSTAGRAM_OWNED_MEDIA_ENABLED` defaults false; carousel
remains unconditionally closed. Primary API/version/permission confirmation and
an explicitly authorized real seller/media canary remain external gates. Synthetic
Graph/CDN transport proves wiring, never provider approval or real retrieval.

At acceptance, an Instagram job records a private connection proof from fresh
active Business/Seller/control state: account, generation, HMAC credential digest
and exact expiry. Request fields cannot supply these. Job projections omit that
private proof; candidate provenance contains no token/digest/CDN URL/caption.
Old jobs without a binding fail closed and require a newly authorized request.

Claim/check/result transactions use Business NO KEY UPDATE, job, Seller/control
locks and fresh committed scalars. Final result writes retain current creator
User/Membership SHARE locks to prevent a concurrent revocation from committing
inside the persistence transaction. No provider HTTP occurs under these locks.
Job-bound short-session callbacks check cancellation, lease, account, expiry and
credential generation around provider work. Request session guards still own
native HTTP authority; the worker rechecks its original creator membership.

Legacy token connect/OAuth and scheduled refresh now use the same locked
compare-and-set helper and advance generation. A network result from an older
account/token/expiry/generation cannot restore a disconnect or replace newer
credentials. Native disconnect/OAuth already advances generation under its
business/Seller lock. A connection cannot silently change an existing account.
Provider exception/body logs were removed from those legacy paths.

A typed internal collected batch carries candidates and originals together.
Single IMAGE/VIDEO output requires exactly one matching parent/media original,
allowed MIME, size and recomputed SHA256. The final transaction revalidates it,
then inserts deterministic per-job assets and append-only manifest audits with
candidate/job/tenant references. It commits bytes, manifest, candidate and job
transition together, skips stale-capture originals and preserves previous
versions/overrides. The upload-input `job.asset_id` meaning is unchanged. Existing
CSV chronology, document identity, review and private draft gates are preserved.

Private manifest and attachment-download routes resolve the current candidate's
accepted job, verify all tenant/job/actor/media/idempotency/digest/byte relations,
recompute content integrity and recheck current native session after reads. JSON
asset UUIDs are never treated as foreign-key proof. These application paths never
update/delete originals/manifests; existing tables have no database immutability
trigger, so database-admin tamper resistance is not claimed. Private reads fail
closed on corruption. Catalogue/storefront publication of those bytes remains a
separate media bridge, not an implicit photo URL or product activation.

The existing native Imports page exposes retrieval only when the real capability
and current connection are available. It journals the exact authorized media
request before POST, retains uncertainty/retries the same key, and downloads exact
retained originals without URL credentials. Source facts remain unknown pending
human review. Identity change clears private original links along with existing
facts/history. Default-off UI truthfully offers other source imports.

No new DDL is introduced. Existing0053 is used on the dedicated guarded lane.
Owned acceptance evidence is recorded separately in
`artifacts/v1/instagram-owned-integration/`; the interrupted old-tmpfs infrastructure
run is preserved and is not acceptance. The new disk-backed PG16 lane is used for
final migrated evidence. Central composition/full-suite acceptance remains separate.
