# Owned Instagram retrieval — ownership and interface freeze

18 October 2026. Base `3f01ae1` reviewed SEO composition. Latest separately pushed
CSV contract/source inspected at `32a2d11fb51293402dd814eb3c4216327e5eec5a`
(`origin/codex/v1-csv-import`). It is not merged into this remote base. CSV owns
adjacent import API/schema/service/UI and migration `0053 → 0052`. Local social
owns current-SKU replies; local catalogue owns remaining analytics instrumentation.
Do not duplicate those or edit shared files without a precise integration contract.

## Frozen file ownership before parallel writes

| Lane | Branch / worktree | Owned writes |
| --- | --- | --- |
| Provider implementation | `codex/v1-instagram-owned-provider` / `munimjee-wave7-instagram-provider` | New `backend/app/v1/imports/instagram_owned.py`, optional new `instagram_owned_transport.py`, dedicated new provider tests, `docs/v1-instagram-owned-provider.md`, `artifacts/v1/instagram-owned-provider/` |
| Independent security and official API contract | `codex/v1-instagram-owned-security` / `munimjee-wave7-instagram-security` | New `test_v1_instagram_owned_security*.py`, `docs/v1-instagram-owned-security.md`, `artifacts/v1/instagram-owned-security/`; provider source read-only |
| Independent durable pipeline QA | `codex/v1-instagram-owned-qa` / `munimjee-wave7-instagram-qa` | New `test_v1_instagram_owned_pipeline*.py`/dedicated harness if justified, `docs/v1-instagram-owned-qa.md`, `artifacts/v1/instagram-owned-qa/`; provider/shared source read-only |
| Coordinator | `codex/v1-instagram-owned-coordination` | This contract, reviewed composition, aggregate evidence and exact shared integration proposal |

All three workers are explicitly GPT-6.1 Sol/high with fresh contexts. No subagents,
other-chat messages, production, real Graph/Meta API call, actual token reads,
provider canary, secrets/dotenv, charges, DNS/routing write, hosted retry/billing
change, Docker probe/restart or shared service operation. Public official API
documentation and Git source reads are allowed. Tests inject synthetic tokens,
resolvers and transports; unallocated actual DB checks remain explicit skips.

## Existing shared seam and local integration boundary

`collect_claim` currently calls
`fetch_owned_media(*, business_id, account_id, media_id)` and expects matching
`result.account_id`, `result.media_id`, and bounded `result.products` pairs of stable
source product key + `DraftFacts`. Both frozen remote and CSV32a2d11 preserve this
Instagram seam. `run_job`/claim/check/finish enforce creator membership, current
account binding, lease, cancellation and final transaction guard around network I/O.
The production worker still supplies no provider.

The inspected source has no ChannelAccount model: current authoritative mapping
is active Business/Seller plus Seller.instagram_page_id/token/expiry and current
ChannelConnectionState provider binding/version. Do not invent a new table or let
caller input select credentials/accounts. Credential loader must be an explicitly
trusted tenant/account-bound runtime callback; no environment/DB fallback at import.
Local integration owns its actual fresh DB lookup/decryption and creator/job guards.

No writes to `services/imports_v1.py`, `workers/v1_imports.py`, existing runner,
schemas/models/migrations, existing OAuth/client, config, native import UI or shared
go-live plan in this remote slice. Produce a precise reviewable shared patch proposal
after the new provider interface is frozen; applying it remains coordinated local
integration. Do not claim worker wiring from adapter-only source.

## Interface freeze required before provider writes

Implementation and security owners propose concrete DTO/callback/transport/limits/
error shapes to coordinator and QA. Keep the existing keyword fetch seam unless a
specific shared change is justified. Explicitly define:

- Trusted credential snapshot, expiry/revocation/connection-generation rechecks,
  token repr/log/error protection and current tenant/account proof.
- Supported Instagram Login route and professional-account/scopes, version supplied
  explicitly from existing configuration. No Facebook Login substitution, oEmbed,
  shortcode scraping or arbitrary public reel ownership inference.
- Account-owned media proof, bounded cursor pagination, children/carousel scope,
  strict media IDs, request/time/byte/asset budgets and cancellation checkpoints.
- Fixed Graph authority, no token query/redirect/proxy leakage; media CDN URL
  allowlisting plus public DNS/IP pinning, TLS authority and no unsafe redirects.
  Signed expiring URLs are ephemeral retrieval inputs, never durable identities,
  logs or candidate evidence. Fresh lookup, not stale URL replay, refreshes them.
- Original media byte retention/size/MIME/hash result and the exact local durable
  attachment proposal, if implemented. Current shared seam ignores additional
  result fields, so never claim durable media preservation before that hook exists.
- Stable media source identity, private review-required candidate(s), unknown
  price/stock/options/title and no guessed product count/facts from media/caption.
  Literal source text may be retained only as explicitly untrusted bounded evidence.
  No auto approval/activation/publication, financial action or message sending.
- Typed credential-free failure codes, redacted exceptions/results, no raw API
  bodies or token-bearing pagination URLs crossing durable/log boundaries.

## Research and acceptance truth

The existing native OAuth is Instagram Login: Instagram authorize/code exchange,
Graph Instagram long-lived token and `/me`, `instagram_business_basic` plus the
existing message/comment scopes; do not add publish permissions for retrieval.
Official developers.facebook.com pages currently return 429/login walls to this
environment. Meta's own public Postman collection is readable and distinguishes
Instagram Login from Facebook Login, but its exact media fields must still be
verified. Record primary links, retrieval status and remaining uncertainties; do
not substitute third-party claims for official supported API facts.

Fake transport proves workflow/security behavior, not actual seller permission,
media retrieval, provider approval or current live capabilities. Independent QA
must cover ownership/scope swaps, expiry/revoke/version changes, bounded pagination,
malformed/oversized/private/redirected responses, cancellation/error redaction and
existing candidate identity/review/reimport/override semantics. Use P01 unchanged
for any optional separately allocated DB lane; no fallback or new allocation here.
Python3.11 test interpreter: `/tmp/munimjee-release-ci-py311/bin/python`.
Push bounded separate branches with exact commits, source hashes, commands and
passed/skipped/real-provider-pending evidence. Keep full V03 and V1 acceptance open.
