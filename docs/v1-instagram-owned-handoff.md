# Owned Instagram adapter handoff

18 October 2026. Reviewed composition on `codex/v1-instagram-owned-coordination`,
based on `3f01ae1`. Application source tested at `fd05305` changes only two new
modules: `backend/app/v1/imports/instagram_owned.py` and
`backend/app/v1/imports/instagram_owned_transport.py`. Existing imports, worker,
runner, OAuth, config, schemas, migrations and UI remain untouched. CSV source and
contract were inspected separately at `32a2d11`; integrate additively into the
latest local service rather than replacing it with this older base. Local Wave5
`32de1ac` / 1,524 passes and eight skips are coordinator-reported, not verified by
this branch. Local social current-SKU and catalogue analytics remain locally owned.

## Ready isolated source

| Lane | Pushed original commit | Composed commit |
| --- | --- | --- |
| Provider, DTOs, transport, 43 synthetic cases | `d5ab4588b651f917fd92f38c5ffc7f1fd8a7f8a6` | `c899ddc` |
| Independent security, 103 cases | `6eabd6f79612300ae1b5155707654742f1f41c67` | `5ad7c1f` |
| Pipeline contract QA and six pending DB cases | `5d986084750bb441d7a312a554c8e63e7b50aea8` | `fd05305` |

Cherry-pick the three originals in that order, or their three composed equivalents;
do not replay both sets. The security branch contains its own provider cherry-pick
`89b6586`; omit that duplicate. Coordinator contract/handoff commits are additive
documentation and evidence. All three named workers used GPT-6.1 Sol/high.

The existing keyword seam is unchanged:
`fetch_owned_media(*, business_id, account_id, media_id) -> OwnedMediaResult`.
Trusted async credential and claim-checkpoint callbacks, explicit Graph version,
resolver/transport and bounded limits are constructor inputs. Tokens, response
bodies and signed URLs are excluded from representations and durable output.
Returned original bytes have media ID, exact MIME and SHA256. One stable
`media-product` placeholder has entirely unknown facts; assets do not imply a
product count, title, price, options or stock. No publication follows retrieval.

Both capability flags default **false**. The media gate returns
`provider_capability_pending` before credential lookup, DNS or network work.
Synthetic tests explicitly enable proposed capabilities. Exact Instagram Login
media fields, carousel applicability and supported API version still lack accessible
primary-source confirmation; Meta developer reference requests were rate/login
blocked. Accessible Meta-owned materials confirm the login/professional/basic-scope
boundary, not the whole proposed retrieval contract. See the primary-source matrix
in `docs/v1-instagram-owned-security.md`. No production enablement is justified.

Retrieval proves the principal, professional account and bounded account-edge
membership before downloading originals. It uses fixed authenticated Graph
authority, unauthenticated allowlisted CDN hosts, validated public DNS answers,
pinned sockets/TLS, no redirects/proxies/retries/decompression, rebuilt bounded
cursors, credential checks around DNS/requests and before return, and a total
deadline. Default limits are 14 seconds, five pages of 25, eight Graph requests,
ten assets, 5 MB per asset, 10 MB across all response bodies including JSON, and
256 KB per JSON response. Carousel has a separate closed gate. The independent
review's active-bearer-in-CDN-URL finding was fixed before the original source
commit and has raw/encoded regression coverage.

## Exact shared integration seams — proposal only

The full insertion/guard proposal is in `docs/v1-instagram-owned-provider.md` and
the target-by-target contract is in `docs/v1-instagram-owned-qa.md`.

1. In `services/imports_v1.py`, extend only the Instagram claim/access path with
   fresh trusted connection proof: active tenant/Seller/creator access, matching
   Seller and ChannelConnectionState account, token presence/expiry and version.
   No ChannelAccount model exists in this base. Bind proof to the job; do not trust
   HTTP account/version/grant inputs. Missing grant metadata stays unknown.
2. Supply a short-session fresh-scalar credential loader and job-bound checkpoint
   through an explicit provider factory/wrapper. The runner already forwards an
   optional provider; `workers/v1_imports.py` currently supplies none. Avoid mutable
   job state shared between invocations. Keep capabilities disabled.
3. At `check_claim` and especially `finish_claim`, under compatible tenant/job/
   connection locks, compare account and generation with fresh committed state,
   require token presence and future expiry, and retain creator, lease and cancel
   checks. Same-account reconnect is currently missed by the shared final guard.
   Every credential writer must follow compatible lock ordering and increment the
   version, or compare an invocation-only expected token fingerprint as well.
   Provider callbacks cannot atomically authorize a later DB write.
   Source audit identified legacy writers in `workers/refresh_tokens.py` and both
   credential update paths in `api/routes/auth.py` that do not increment connection
   version. The final guard must lock the actual Seller credential row as well as
   the connection/job rows and use fresh scalar values; a fingerprint comparison
   without a lock covering the following writes is insufficient. Network-gap
   refresh/reconnect results also need a compare-and-set against their original
   generation so they cannot restore credentials after disconnect. Coordinate
   writer changes with their local owner rather than assuming native OAuth is the
   only entry point.
4. Change `collect_claim`'s internal tuple into a typed collected batch that carries
   bounded originals and returned account/version alongside candidates. The current
   service discards `result.assets`. Keep all other source paths compatible. Review
   the fixed `ERROR_CODES` allowlist; current unknown Instagram failures safely
   collapse to `source_adapter_failed`, losing repair distinctions.
5. After the final live guard and stale-capture decision, revalidate bytes/hash/MIME
   and parent/child association. Atomically retain originals in existing ImportAsset
   rows plus immutable ImportAudit manifests with draft/job changes. Proposed asset
   idempotency is `uuid5(job.id, 'instagram-original:' + media_id + ':' + sha256)`;
   manifest idempotency additionally includes candidate ID. Verify replay metadata
   and content, preserve old originals, and skip originals for stale captures.
   `job.asset_id` retains its upload-input meaning. Initial IMAGE/VIDEO expects one
   matching original; carousel remains disabled. No migration is proposed here.
6. Manifest details contain only IDs/hash/size/MIME/version. Audit job/candidate
   tenant FKs do not create an FK for a JSON asset UUID: every writer/reader must
   resolve the asset under the same business and verify its metadata. Add private
   tenant-scoped manifest/byte readers to the local review API/UI before claiming
   accessible retained originals. A later catalogue media bridge needs separate
   acceptance. Never persist signed CDN URLs or credentials as evidence/identity.

Preserve CSV's stable document UUID + exact trimmed product_ref namespace, immutable
original bytes, `captured_at=job.created_at`, stale-capture/override/review behavior,
non-CSV request-hash compatibility, its separate errors and `0053 → 0052` ordering.
Preserve durable pending jobs, serial dispatch, lease recovery/three-attempt bound,
cancellation/retry revisions and private review-required output.

## Verified here and remaining acceptance

- Focused composed provider/security/pipeline/import regressions: **393 passed,
  15 skipped**, zero failures, 0.89 seconds.
- Full composed backend: **1,350 passed, 582 skipped**, zero failures, 9.14 seconds.
  Counts overlap and are not added. Existing dependency deprecation warnings remain.
  No disposable DB lane was allocated; skipped cases establish no DB acceptance.
- Clean runtime package: **291 files**, both modules included, repeated archives
  identical. No image build/run. Exact hashes, commands and worker configuration
  are in `artifacts/v1/instagram-owned-coordination/`.
- Provider/security hashes match the original committed source; shared runtime
  remains unchanged from the reviewed base. `git diff --check` passed.

Local integration must execute the six pipeline DB cases and new generation/
original-manifest transaction cases on a separately allocated unchanged P01 lane,
then mounted/native review and tenant-isolation acceptance. Primary API confirmation
and explicitly authorized real seller/media retrieval remain separate gates; this
batch uses synthetic transport only. No actual tokens, Graph/CDN calls, provider
canary, Docker action, hosted retry, billing change, charge or production operation
occurred. Worker wiring, durable retention and its readers remain code work.
Full V03/V04 and V1 acceptance remain open.
