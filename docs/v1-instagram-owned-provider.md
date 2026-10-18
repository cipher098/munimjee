# Owned Instagram provider: isolated implementation and integration proposal

18 October 2026. Base `3f01ae1`; CSV service contract/source inspected separately at
`32a2d11fb51293402dd814eb3c4216327e5eec5a`, without merging or changing shared files.
Coordinator froze this interface before source writes. This slice adds an adapter,
its isolated transport and synthetic tests only. It does not wire a worker, persist
originals, grant provider permissions or satisfy V03 acceptance.

## Default capability and official API evidence boundary

`OwnedMediaCapabilities(ig_login_media=False, carousel=False)` is frozen and supplied
only by trusted runtime construction. The default raises `provider_capability_pending`
before loader, checkpoint, DNS or HTTP. Jobs cannot select or override capabilities.
The proposed versioned Instagram Login `/me?fields=user_id,account_type`, account
`/{account_id}/media?fields=id,media_type,media_url` and matched carousel
`/{media_id}/children` logic is exercised only under explicit synthetic grants.
Both media and carousel grants must stay false in real composition until primary
sources verify the exact Instagram Login endpoint/field mapping for the configured
version and actual seller permission/provider approval is separately established.

Primary reference: [Meta's Instagram Postman collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).
The independent security lane confirms Instagram Login uses professional business or
creator accounts, `graph.instagram.com`, `instagram_business_basic`, and Bearer
authentication. Its visible media examples mix Facebook Login, so they are not proof
of these Instagram Login media fields. Developers documentation returned 429/login
walls during this research. See the independently owned security evidence for exact
retrieval status and links. No third-party endpoint claims substitute for verification.

## Frozen runtime interface

```python
OwnedCredentialSnapshot(
    business_id: UUID, account_id: str, token: str, expires_at: datetime,
    connection_version: int, revoked: bool = False, login_route: str = "instagram",
    granted_scopes: frozenset[str] | None = None,
)
OwnedInstagramProvider(
    *, credential_loader, checkpoint, graph_version,
    resolver=system_resolver, transport=None, limits=None, capabilities=None, utcnow=None,
)
await provider.fetch_owned_media(*, business_id, account_id, media_id)
```

The two mandatory callbacks are trusted async `(business_id: UUID, account_id: str)`
functions. The loader returns a fresh `OwnedCredentialSnapshot`; the checkpoint
returns the literal boolean `True` only while its enclosing claim remains valid.
No database, settings, environment or secret lookup is imported or performed by the
adapter. A local factory must read the actual Business/Seller and current Instagram
`ChannelConnectionState`; DTO `connection_version` maps explicitly to its `version`
(integer zero is valid). No new channel-account or granted-scope storage is assumed.
Requested OAuth scopes are not granted scopes: `None` means not recorded and makes
no grant claim; a recorded scope set missing basic denies. Graph permission failures
fail closed. `/me` must independently match exact string `user_id` and professional
`account_type` BUSINESS/CREATOR before any account-media request.

The loader/checkpoint run before each network request, again after DNS immediately
before HTTP, and after all bytes are collected. Every fresh snapshot validates exact
tenant/account, route, token header safety, current UTC expiry, revocation and integer
version; changes to token/version/expiry/scopes discard results. Checkpoints must
include current creator membership, job state/lease, cancellation and binding using
trusted closure context rather than caller-selected credentials. The outer shared
`collect_claim` still has its existing 15-second timeout.

`OwnedMediaResult` contains account_id, media_id, products, assets, media_type and
connection_version. `products` is always exactly one `("media-product", DraftFacts())`
review placeholder, regardless of carousel size or visible garment count. Title,
description, price, stock and options remain unknown. Captions, OCR and media content
produce no factual claims. Exact original asset bytes, SHA256, MIME and child media
ID are returned ephemerally in `OriginalMediaAsset`; no signed URL appears in results,
evidence or durable identity. Bytes and URLs/tokens/headers/bodies are excluded from
DTO repr. No automatic approval, activation, publication or external action exists.

## Bounds and security behavior

`OwnedMediaLimits` defaults/hard maxima are: 14-second total deadline (15 maximum),
5 pages per edge, 25 records per page, 8 Graph requests including `/me`, 10 assets,
5,000,000 bytes per asset, 10,000,000 total response bytes including JSON, and
256,000 bytes per JSON response. Smaller limits are supported. Unknown media outside
the bounded account edge fails closed, not a direct-ID lookup. Carousels require the
separate grant, and children come only from that already matched parent's edge.

The monotonic deadline includes credential/checkpoint/resolver/transport waits.
Timeout uses `asyncio.wait` and retained admission, so cancellation-suppressing
injected awaitables cannot extend the caller wait or accumulate beyond four pending
operations per provider instance. Cancelled admission stays occupied until actual
completion. The default resolver and transport additionally cap their worker pools
at four, without an unbounded work queue. Trusted callbacks must be asynchronous;
Python cannot preempt callback code that synchronously blocks the event loop.

The transport fixes Graph to `graph.instagram.com` and requires an explicit syntactic
API version, supplied from existing configuration by the local factory. Graph tokens
travel only in Authorization headers. CDN URLs allow only proper subdomains of
`cdninstagram.com` or `fbcdn.net`, with HTTPS/443, strict ASCII DNS labels, no userinfo,
fragments or IP literals. Signed queries are ephemeral. Raw or recursively encoded
active-token content in CDN URLs/cursors is rejected. All DNS answers must be public;
the socket pins one validated address, verifies its peer and TLS hostname/SNI. No
proxy discovery, cookies, redirects, retries or decompression is implemented. TLS
finishes and the absolute deadline is checked before sending the HTTP Authorization
header. Error/redirect bodies are not downloaded by the default transport.

Pagination rebuilds only the trusted endpoint and a bounded ASCII
`paging.cursors.after`; repeated/invalid cursors fail. `paging.next` is only a
continuation signal and never parsed, requested, retained or logged. JSON rejects
duplicate keys, non-finite constants, malformed encoding and wrong data shapes.
Response/header/byte/MIME/signature limits are enforced for synthetic transports too.
JPEG/PNG/MP4 signature checks are not full decoding, malware scanning or proof of a
product. Existing unauthenticated website `SafeFetcher` is not widened.

## Exact local shared integration proposal (not applied here)

1. Construct the provider only in the locally owned composition root. Inject the
   current tenant-bound loader and claim-bound checkpoint; keep both capabilities
   disabled until independent official and authorized actual-provider gates pass.
   Never import environment/DB fallback into the adapter or pass a seller token via
   an import job. Use the existing configured Instagram API version explicitly.
2. Keep `fetch_owned_media` keywords and `products` unchanged. Change the shared
   collection result to a typed internal `CollectedClaim(candidates, originals,
   provider_account_id, connection_version)` where `originals` is the bounded tuple
   returned here. Website/upload/CSV return empty originals. Do not attach binary
   content or signed URLs to candidate JSON, job.source, logs or API responses.
3. Before any candidate/asset writes, `finish_claim` must lock the existing Business,
   job and Instagram connection row and freshly check creator membership, active
   Business/Seller, unexpired matching lease, cancellation, matching current account,
   token presence, UTC expiry and **exact returned connection version**. Current
   shared guards check role/account but not generation/expiry/token, so this remains
   a real integration gap. Every credential replacement/revoke/reconnect writer must
   increment that locked version; otherwise the local invocation wrapper must carry
   an ephemeral expected token fingerprint and compare the fresh token too. Do not
   serialize that fingerprint or the token into any durable receipt.
4. In that same guarded transaction, validate bytes/hash/MIME again, then insert each
   original into existing `ImportAsset` with business_id and creator_id from the
   claim, authorization time from the original authorized job, and idempotency key
   `uuid5(job.id, 'instagram-original:' + asset.media_id + ':' + asset.sha256)`.
   Replays must verify exact metadata/content instead of accepting key collisions.
   Existing 5MB and MIME constraints fit; no migration is required for this proposal,
   and separately owned CSV migration 0053 remains untouched.
5. After the candidate exists, link the retained original through an immutable
   `ImportAudit` with action `instagram_assets_retained`, candidate/job tenant FKs,
   key `uuid5(job.id, 'instagram-manifest:' + candidate.id + ':' + asset.media_id + ':' + asset.sha256)`
   (stringify candidate UUID). Details contain only parent/child media IDs, asset UUID,
   SHA256, size, MIME and connection version. Its request_hash covers those canonical
   details. Store no CDN URL, credentials, raw source body or binary in that audit.
   This is a proposed existing-table attachment manifest; the local review API/UI
   must separately read its tenant-scoped asset references and bytes. Original
   candidate facts and identity remain unchanged. Reimports retain previous manifests
   and originals; new job+content produces a new version, not overwrite/delete.
6. Make candidate upsert, original inserts, manifest audits and job review_required
   transition atomic. Late/cancelled/revoked/stale claims must insert neither bytes
   nor candidate changes. Preserve existing stale-capture/review override semantics.
   Local integration must explicitly decide whether stale captures retain a historical
   manifest or skip them; the safe default is skip originals alongside ignored candidates.
7. Add credential-free error codes below to the shared allowed-error mapping. Current
   `run_job` safely collapses unknown codes to `source_adapter_failed`, so adapter-only
   source does not yet expose actionable expiry/reconnect errors. Existing retry policy
   is unchanged here. Propose retryable timeout/busy/rate_limited/http_error/transport_failed
   within existing attempt limits; credential/binding/ownership/capability/validation
   failures require owner repair/review and must not become uncontrolled retry loops.

## Typed errors

`OwnedInstagramError` subclasses existing `FetchError`; str/repr expose only a code.
`ERROR_CODES` is exported from both modules and restricts constructor input to:

```text
provider_capability_pending
instagram_invalid_request instagram_credentials_unavailable
instagram_credentials_invalid instagram_credentials_expired instagram_binding_changed
instagram_access_revoked instagram_cancelled instagram_timeout instagram_busy
instagram_request_limit instagram_media_not_owned instagram_pagination_invalid
instagram_response_invalid instagram_unsupported_media instagram_asset_invalid
instagram_body_too_large instagram_unauthorized instagram_rate_limited
instagram_http_error instagram_transport_failed instagram_unsafe_address
instagram_peer_mismatch instagram_redirect_forbidden instagram_unsafe_url
instagram_content_encoding
```

## Verification and remaining gates

All tests use synthetic tokens, byte fixtures, resolvers and transport responses.
Provider success proves workflow/ownership checks against this proposed contract;
it does not prove actual Meta availability, permission, correctness of media fields
or production readiness. No real Graph/CDN request, token read, DB allocation,
provider canary, Docker operation, production access or charge occurred. Actual
media capability, shared worker wiring, durable asset transaction/API/UI integration,
final generation guard and migrated database acceptance remain unrun gates.
