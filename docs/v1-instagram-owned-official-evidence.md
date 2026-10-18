# Owned Instagram media: official documentation evidence

Observed 18 October 2026, through 08:38 UTC. Documentation research only: no token
read, Graph/CDN API call, account access, database operation or provider canary.
Both `ig_login_media` and `carousel` remain **false**. This packet narrows the
documentation gate; it does not establish seller permission, current configured
version compatibility, downloadable originals or V03 acceptance.

Reviewed remote handoff/contracts/provider at
`origin/codex/v1-instagram-owned-coordination`, resolved commit
`e0e836fa54242d1b1b434f68c10f2808505a5e13`. Provider Git blob:
`b010e67a11fd881fe52c1f54507fb3f987b37a2c`. No adapter/shared source changed.

## Retrieval method and primary sources

Earlier `/docs/` fetches returned rate/login failures. Normal public Chrome
navigation reached Meta's current `/documentation/` pages; their rendered text,
title and URL were read without signing in. Search-tool fetch failures are not
evidence that a page or endpoint is unsupported. No full copyrighted page is
republished here. The adjacent JSON records source observations and explicitly
synthetic parser-shape examples, not real API responses.

| ID | Primary source | Visible update / retrieval |
| --- | --- | --- |
| S1 | [Instagram Login Get Started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started) | Dec 2, 2024; public browser |
| S2 | [Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) | Mar 13, 2026; public browser |
| S3 | [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) | Aug 12, 2026; public browser |
| S4 | [Children](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/children) | Aug 12, 2026; public browser |
| S5 | [/me](https://developers.facebook.com/documentation/instagram-platform/reference/me) | Mar 3, 2025; public browser |
| S6 | [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) | Apr 22, 2026; public browser |
| S7 | [IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) | Sep 28, 2026; public browser |
| S8 | [Instagram error codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) | Jun 2, 2026; public browser |
| S9 | [Meta official Postman: Instagram Login](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login) | indexed official folder text |
| S10 | [Meta official Postman collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api) | indexed official collection text |

These dates identify what the page displayed, not an API release or proof that
every example matches the configured Graph version. Current reference examples
display `v26.0`; that is not authorization to upgrade the application's version.

## Authentication routes must remain distinct

S2 documents Instagram authorization at `www.instagram.com/oauth/authorize`, a
server POST of the code to `api.instagram.com/oauth/access_token`, a server GET
exchange at `graph.instagram.com/access_token` (`ig_exchange_token`), and refresh
at `graph.instagram.com/refresh_access_token` (`ig_refresh_token`). Codes are
single-use and valid for one hour. Long-lived tokens last 60 days; refresh requires
an unexpired token at least 24 hours old and the basic permission. S2 requires the
Instagram App ID/Secret and matching redirect URI; secrets belong server-side.
These are documentation facts, not an audit of existing OAuth implementation.

S3/S4/S6 explicitly distinguish these routes:

| Route | Token / host | Reading permission and account setup |
| --- | --- | --- |
| Instagram Login | Instagram User token; `graph.instagram.com` | `instagram_business_basic`; professional business/creator account; S9 says no linked Facebook Page required |
| Facebook Login | Facebook User token; `graph.facebook.com` | `instagram_basic` plus `pages_read_engagement`, with conditional Business Manager permissions described in the reference; connected Page flow in S10 |

S9 inherits Bearer authentication. The existing header-only bearer/no-token-query
adapter is a local protection consistent with that example. S2's examples also
contain token query parameters; those examples do not require copying that leakage
pattern into our implementation. Requested permissions are not proof of actual
granted permissions, app access level or seller consent. Standard versus Advanced
Access remains governed by account ownership/management and App Review (S2).

## Adapter assumption matrix

Line references below are against the frozen provider blob above.

| Adapter assumption | Evidence / qualification | Contract consequence |
| --- | --- | --- |
| `/me?fields=user_id,account_type` proves the principal (309–313) | S5 maps `/me` to the token's user node. S1 lists both fields and demonstrates `user_id,username`. Its example uses a top-level `data` array; S5 does not settle response wrapping. | Flat-only parsing is not covered by every official example. Add strict single-principal documentary fixtures; reject empty/multiple/mixed principals and exact-ID mismatch. Do not permissively select an account from a list. Actual wire shape remains a canary item. |
| Professional enum is `BUSINESS` or `CREATOR` (312) | S1 says account_type can be **“Business or Media_Creator.”** This is prose, not a wire JSON enum example. S6's generic fields table does not list this field. | `CREATOR` is not supported by the observed wording. Exact values/casing require an explicit reviewed mapping and authorized wire proof; do not silently relax the guard. |
| Account-owned `/{account_id}/media` (314) | S1 explicitly demonstrates this edge on `graph.instagram.com` using the Instagram User token. It returns media IDs and cursor fields. S6 describes the media collection. | Owned-edge membership is documented; retain exact tenant/token/principal/target checks. A direct arbitrary media-ID request is not a substitute for our ownership proof. |
| `fields=id,media_type,media_url` on that edge (267) | S3 explicitly supports those media fields for Instagram Login. Combining S1's media edge and S3's object reference supports the proposed field expansion; no observed S1 example shows that exact expanded request. | Supported by combined references, not an observed response. Verify configured-version field expansion in the canary. |
| `IMAGE`, `VIDEO`, `CAROUSEL_ALBUM` (318–325) | S3 lists these `media_type` values. `REELS` is a product type, not one of these media types. | Keep media_type distinctions. Do not introduce a `REELS` media_type from a caption or URL. |
| Every supported owned video has a `media_url` (333–335) | S3/S4 explicitly permit omission for copyrighted/licensed audio, including owned video and carousel video children. Disabled reel downloads affect other-user reads, not owned-account reads. | Missing original URL is a documented unavailable-original outcome, not proof of revoked ownership or a transient permission fault. Keep private review/upload fallback; no scraping or downloading a permalink as a workaround. Current fail-closed rejection is safe but needs truthful UX. |
| Matched `/{media_id}/children` works with Instagram Login (322) | S4 explicitly lists Instagram Login, `graph.instagram.com`, Instagram User token and `instagram_business_basic`, then defines the children GET. Its sample request still uses Facebook's host. | Strong primary support for the route, with a mixed-host sample caveat. Keep carousel separately disabled until configured-version/authorized canary and durable per-child handling pass. |
| Child fields/permalink | S4 returns IG Media objects; S3 defines media fields and S4 warns some fields, including permalink, are not available on album child photos. | No guaranteed child permalink fallback. Child URL can also be absent. |
| `paging.next` signals continuation; bounded `after` cursor rebuild (285–298) | S1's Instagram Login example has `paging.cursors.before/after` but no `next`. S7 discusses time pagination but its requirement table/sample are Facebook Login. S10's broad pagination wording is within that mixed collection. | Exact next/end semantics and cursor alphabet/length for this IG Login edge remain **unknown in this packet**. Existing bounded rebuilding is a safety policy; do not claim completeness or replay provider URLs. |
| Fixed CDN suffixes, URL lifetime and exact byte format | Observed official references do not promise `cdninstagram.com`/`fbcdn.net` as an exhaustive host list, a URL TTL, no redirects, JPEG/PNG-only images, MP4-only originals, or response decompression behavior. | These are local fail-closed compatibility limits, not Meta guarantees. Unknown/unsupported assets require review; retain exact bytes/hash only after existing safety checks. No fresh URL replay guarantee or exhaustive retrieval claim. |
| Limits of 5 pages/25 items/8 requests/10 assets/14 seconds/5 MB | No primary source here establishes these retrieval limits. Publishing-specific carousel limits in S7/S8 do not prove retrieval maxima. | Label them local budgets. Bounded search miss means not found within the budget, not exhaustive account nonownership. |
| HTTP401/403→unauthorized;429→rate_limited; other non200→http_error; JSON error→unauthorized (198–205,245–246) | S8 documents structured `error` objects and HTTP400 cases as well as403; much of that table concerns publishing/audio operations. It does not prove an exhaustive owned-read error map. | Current generic failures remain closed/redacted, but do not equate every error object with authentication failure or promise reconnect repairs. Exact expiry/permission/rate limits/subcodes and retryability remain canary/documentation gaps. |

## Review and acceptance work still required

1. Coordinator reviews strict principal-wrapper and account-type fixtures before
   any adapter edit. Documentary shape examples must never become fallback ownership
   logic. A response with two principals or conflicting IDs must fail closed.
2. Verify the configured Graph version and approved Instagram Login token route with
   a separately authorized seller/account. Capture only sanitized response structure,
   enum/field presence and version; no tokens, signed URLs, payload bodies or secrets
   in evidence. Do not run this as part of this docs task.
3. Cover single image, reel/video with and without downloadable URL, and carousel
   children separately. Observe real pagination/end behavior within local budgets;
   record partial retrieval truthfully. Keep both runtime capabilities disabled
   until the coordinator explicitly approves their separate gates.
4. Complete the already proposed current credential-generation/expiry/revocation
   guards and atomic retained-original manifest/tenant readers. This research does
   not supply worker wiring, persistence, schema/DB proof or customer UI acceptance.
5. Preserve upload/CSV fallbacks and unknown facts. Media availability never proves
   price, stock, variants, title, garment count or permission to publish/send.

No provider gate was cleared and no live outcome was inferred from documentation.
