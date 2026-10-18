# Owned Instagram retrieval: independent security and official API review

Review date: 18 October 2026. Security lane base: `3f01ae1b8f0296df8c761d9ce52b534aa6b74b9a`.
Read-only shared contract: coordinator `docs/v1-instagram-owned-contracts.md` at
`0523488`; read-only CSV seam: `32a2d11fb51293402dd814eb3c4216327e5eec5a`.
This lane owns only new security tests, this document and its artifact directory.

## Official API evidence and unresolved gates

Only Meta-owned public documents/source below establish provider claims. Search
results from third parties were not used as a basis for capability assertions.
No login wall, rate limit or access control was bypassed. No Graph API request,
real credential lookup, application environment, database or provider canary was used.

| Claim | Primary source and observed result | Review conclusion |
| --- | --- | --- |
| Instagram Login serves business/creator accounts and needs no linked Facebook Page | [Meta Instagram Login folder](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login), public indexed content retrieved | Supported; do not substitute Facebook Page credentials. |
| Current basic scope name and bearer authentication | Same Meta folder lists `instagram_business_basic`; folder inherits bearer token authentication | Supported. Do not add publishing permission for retrieval. |
| Instagram Login uses a versioned `graph.instagram.com` authority | [Meta IG Login messaging request](https://www.postman.com/meta/instagram/request/psiv6gj/media-message-gif?tab=body) explicitly places its request below the IG Login folder and uses `https://graph.instagram.com/{{api_version}}/{{ig_user_id}}/messages` | Supported for this route's Graph authority/version placement. Messaging documentation is not media endpoint proof. |
| Exact authorization/code exchange/token lifetime semantics | [Instagram Login overview](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/) returned HTTP 429; get-started failed fetch | Unverified in this review. Existing local integration uses Instagram authorization, `api.instagram.com/oauth/access_token`, and `graph.instagram.com/access_token`; local source establishes implementation only. |
| Exact IG Login `GET /{account_id}/media` and fields `id,media_type,media_url` | [Get started](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started), [IG Media](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media) failed fetch | Unverified primary gate; generic business SDK/mixed collection cannot establish login applicability. |
| Generic IG Media schema and children edge | [Meta Python Business SDK IGMedia](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/igmedia.py) exposes media fields and `GET /children` targeting IGMedia | Supports generic SDK schema/edge only, not IG Login permission applicability or maximum children. |
| Carousel children applicability and exact maximum | [IG Media children](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/children) failed fetch | Unverified; local asset/page limits are defensive policy, never claimed Meta maximums. |
| Exact IG Login media pagination/permission contract | [Meta collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api) is mixed with a Facebook Login folder; its cursor-pagination text appears under Facebook Login | Do not transfer that scope/edge contract to IG Login. Opaque cursor reconstruction is a defensive implementation proposal. |
| Media URL lifetime and download availability | No readable Meta primary source verified a duration or universal availability | Treat URLs as ephemeral sensitive inputs, retain stable media IDs and separately authorized original bytes; no TTL claim. Missing media URL fails closed. |
| Current supported/latest Graph versions or version sunset | No readable Meta primary source verified release/sunset dates | Require explicit trusted version; syntactic validation is not live version support proof. |

Root froze default-closed `OwnedMediaCapabilities(ig_login_media=False, carousel=False)`.
The media retrieval capability remains closed by default until the exact
Instagram Login endpoint, fields and scopes are verified. A constructor-only
capability grant may enable deterministic tests of the proposed request contract;
it is not seller-facing permission or proof of live provider approval. Carousel
capability needs a separate primary-source decision. No arbitrary reel, shortcode,
oEmbed or public post lookup establishes tenant ownership.

## Review boundary and security requirements

Current authoritative account mapping is Business/Seller plus current
ChannelConnectionState; no ChannelAccount table is introduced. A trusted callback
must look up the current business/account binding, decrypt the current token, and
return a frozen snapshot with expiry, revocation, connection generation and login
route. The existing schema does not durably record granted scopes or account type:
optional known granted scopes may be supplied only from actual proof (`None` means
unrecorded; a known set missing basic scope denies). The adapter separately checks
`/me?fields=user_id,account_type` for exact account ID and BUSINESS/CREATOR type. A caller-supplied account ID alone
never selects credentials. Fresh snapshot and cancellation checkpoints must run
before every request, after DNS, and before returning. Local integration retains
creator membership/job/lease guards and final durable transaction fencing.

Ownership proof must be exact requested media membership in the current connected
account media edge; an arbitrary successful media-ID fetch or caller assertion is
insufficient. Any children request must use the previously matched parent. Keep
unknown commercial facts unknown and produce only a private review placeholder.
Media count is not product count. Caption text never supplies authority/instructions.

Graph tokens are authorization headers only. Never follow raw `paging.next`; rebuild
fixed-authority paths from bounded opaque cursors. No redirects, proxies, cookies,
auth transfer to CDN, decompression or hostname re-resolution after public DNS
validation. All returned addresses must be public, peer IP pinned and TLS hostname
verified. Bound aggregate requests/pages/assets/bytes/time and in-flight resolver/
transport work; cancellation-suppressing late tasks must not start later child/CDN
requests. Strict JSON must reject malformed UTF-8, duplicate keys and non-finite
values without leaking bodies into errors.

Signed CDN URLs, credentials and raw provider bodies must not appear in result repr,
exceptions, causes, logs, candidate evidence or durable identities. Retained original
bytes/hash/MIME are additional adapter results: existing `collect_claim` ignores
these fields, so durable retention remains an unimplemented integration gate.

## Verification evidence

Provider original source `d5ab4588b651f917fd92f38c5ffc7f1fd8a7f8a6` was
reviewed and composed as `89b65869e126c7da12e01ee6fa614f8a7be9bf3b`.
The independent suite passed **103 tests, zero skips** (0.24 s). The focused
composition with owner provider tests and existing website/upload fetcher tests
passed **193 tests, zero skips** (0.40 s). Commands and exact source/test SHA256
values are recorded in `artifacts/v1/instagram-owned-security/verification.json`.

A pre-commit review finding was resolved by the implementation owner: a Graph
response could echo the active bearer into an otherwise permitted CDN URL query.
The provider now rejects known-credential taint, including recursively encoded
forms. Independent plain/encoded regression tests passed against the committed
source. No additional source defect was observed in these bounded tests.

Coverage includes default gating before callbacks; native `/me` principal proof;
known/unrecorded scope behavior; business/account mismatch; expiry, revoke and
connection-generation changes; strict malformed/duplicate-key JSON; arbitrary
paging targets and unsafe cursors; fixed Graph/CDN authorities; all-address public
DNS validation and pinned peers; header-only auth; no error-body download; MIME,
signature, per-asset and aggregate byte bounds; cancelled late media and children
responses; cancellation-suppressing callback/resolver admission; and the four-thread
transport ceiling. Results preserve exact original bytes/hash/MIME and no signed
URL. These are synthetic workflow/security checks, not physical file decoding or
provider permission/capability certification.

Both capabilities remain closed by default. Exact official IG Login media and
carousel field contracts, current provider version support, live seller permission
and App Review, actual DB/job fencing, and durable original attachment persistence
remain unrun/unverified gates. No green release, real provider success, durable
attachment persistence or DB acceptance is claimed by this document.
