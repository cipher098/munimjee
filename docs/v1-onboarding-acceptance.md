# V01/V07 independent seller-onboarding acceptance audit

Audit source: pushed `abab30aaf1ab94052344b0ef21d05b3922f260dc`, isolated
`codex/v1-onboarding-acceptance`. Existing GPT-6.1 Sol/high. This packet owns only
new QA tests/docs/artifacts. Shared native/channel runtime fixes belong to the
integrator until a precise separate ownership handoff. No provider authorization,
real tokens, messaging, external delivery, production writes or deployment occurs.

## Acceptance and evidence boundaries

V01 requires invite/signup, business details, roles, resumable progress/blockers
and audited assisted access without shared passwords or engineering intervention.
V07 requires supported authorization/account selection, current permission and
readiness checks, an explicit test path, reconnect/disconnect and actionable expiry.
The plan's actual acceptance additionally requires authorized real channel delivery.
Synthetic account GETs, encrypted credential saves and local checks cannot satisfy
that external gate.

| Path | Actual source / existing evidence | Current disposition |
| --- | --- | --- |
| Signup, password login, persistent native session | `/v1`, native `/api/v1/auth/*`; native-session rows and CSRF; existing auth tests and real browser harness | Implemented. Existing evidence is historical; this audit does not relabel its count as a fresh rerun. No seller-token fallback is proposed. |
| Invite and profile | One-use hashed invitation, existing-account password proof, membership roles; versioned profile save | Implemented core path. Wait/revocation and stale-page cases below need explicit acceptance; a configured profile alone does not complete onboarding. |
| Sales membership and responsibility | `/v1/assistance`; existing membership only, owner assigns active owner/manager; exact-key receipt/audit | Implemented local workflow. Responsibility assignment does not grant access. |
| Separate assisted read-only access | `/v1/support`, owner consent, fixed readiness.summary, 5–60-minute expiry, allowlisted native operator | Implemented bounded local path. No inbox/provider/credential access or impersonation. Existing permission gates remain required. |
| Resumable native checklist | `services/onboarding.py:20–37` derives profile/counts, but permanently sets catalogue/storefront to action_required, channels to pending_external and onboarding_complete=false | Code-owned completion/progress gap. Even real activated/published inventory cannot advance those local steps here; the newer assistance projection already derives some local progress. Keep external tests separate rather than marking everything ready. |
| Instagram connection | Native owner start/callback, signed actor/business/attempt, browser nonce, consumed one-use exchange; same-inbox binding and generation checks | Local OAuth implementation exists. Actual grants/current response shapes and enum/version compatibility remain provider gates; official evidence packet adcdad1 identified documentary discrepancies without enabling retrieval. |
| WhatsApp connection/account selection | Channel page requires manually supplied WABA ID, phone-number ID and access token; server verifies number membership and stores encrypted token | Local technical setup exists. A fresh seller-facing consent/discovery/account-picker flow is absent; this is a code/product path gap distinct from missing provider approval. Do not treat manual token entry as verified self-service consent. |
| Check connection | Provider account-access GET; saved checked_at/status | Implemented local check. UI correctly says no message test, approval not evaluated. It must not be relabelled delivered/approved. |
| Authorized channel test | No native test action or durable result recording found in current channel workspace | Code-owned test workflow gap plus separate real-recipient/provider gate. Do not silently send to an inferred recipient. |
| Reconnect/disconnect | Local disconnect clears/pauses credentials, retains inbox account binding and cancels IG attempts; reconnect rejects a different inbox account | Implemented local path, with native session-wait/privacy defects below. Provider-side permission revocation remains a separate action. |

## Confirmed or targeted defects

### P1: channel workspace retains private content after confirmed session failure

`backend/static/channel_operator.js:13,16–21,28–29` handles401 as an error string
without clearing private business, receipt/dialog/history or connection DOM. No
native focus/visibility/session-identity fence is installed. A previously loaded
page can retain customer content after logout/identity replacement. An open WA
password input is not reset on that failure or when its dialog is closed.

The dedicated VM reproduction runs the **actual unchanged script**, reaching its
initial load through minimal DOM/API doubles, then returning401 on Refresh.
`channel-401-retention-repro.json` records only booleans/source hash and confirms
business/message/connection facts and open password input remain. This is source/VM
behavior proof, not rendered Chromium, actual session or provider proof. Existing
channel browser coverage checks the session-error text after logout but not scrub.

Minimum repair: shared native session/CSRF client; current user/session/business/
capability checks before and after awaited reads/writes; latest-response ordering;
focus/visibility revalidation; physical scrub/secret-input erase and closed dialogs
on ended/replaced access; stale responses cannot repopulate the page. Preserve
unknown-operation identity instead of generating a new POST after ambiguity.

### P1: native channel mutations do not recheck the session after provider waits

`api/v1/channel_operator.py:78–111` uses preflight native auth; `verify` and
`connect_whatsapp` wait on provider access before local writes. The domain's
locked_access protects current membership/User/Business rows, but it does not lock
or revalidate the specific UserSession. The IG callback consumes its attempt before
token exchange, then rechecks membership/generation but not the current native
session before persisting credentials. Revoking that session during the network
gap can therefore leave current membership intact while authorization has ended.

`test_v1_onboarding_acceptance_db.py` contains three desired-safety HTTP probes:
IG account verification, WA credential verification, and consumed IG callback
exchange. Each holds only synthetic provider work, revokes the actual UserSession
from a second DB session, releases the provider response and expects401 with no
new committed credentials/check/audit. The callback must retain consumption of its
one-use attempt; denying the final save must not permit blind exchange replay.
All three probes reproduced on actual app.main, current native signup/session/CSRF and the real migration chain: IG verification returned200 with one committed audit and verified access; WA connect returned200 with one committed audit and saved encrypted credentials; the consumed IG callback returned303 and saved credentials. In each case the exact UserSession was revoked and committed before the synthetic provider response was released. Raw failure logs/XML preserve these desired-safety failures.

Minimum repair: final current native-session plus capability check at a
caller-owned transaction boundary, including explicit post-network/post-lock
checks. Preserve the callback's intentional pre-exchange consume commit; protect
its later credential commit separately. Never add an implicit retry or claim an
unknown exchange failed before acceptance.

### Further source findings requiring separate bounded proof

- `identity_auth.save_profile` checks business.write before awaiting its Business
  lock; profile/invitation routes use preflight guards. Apply the same current-session
  boundary review separately. This packet's allocated three-case DB slot does not
  prove these extra races.
- `static/v1_app.js` has no focus/visibility identity revalidation. Its current
  business/role/profile/team projection can remain stale until an API action. Existing
  generation fences correctly discard some switched-business responses but do not
  replace a current native-session fence.
- Current native progress and channel test/consent gaps are implementation scope to
  agree with the integrator, not permission to invent an all-ready completion state.

## Verification and next gate

- VM privacy reproduction: confirmed, using actual source and safe synthetic values.
- Python/JS syntax and diff checks: passed. Initial VM harness syntax failure is
  preserved as a fixture failure; it is not application evidence.
- Three actual HTTP/PG probes: **3 desired-safety failures confirmed**,4.24seconds,
  newly allocated disk-backed payment_w6, numeric loopback55443, actual0053 and
  unchanged P01 reset lease. No old DB access. The exclusive slot was released.
  One inherited Pydantic deprecation warning. The first run reproduced two source
  failures but its OAuth case hit an owned fixture transaction mismatch; that raw
  log is preserved. The corrected fixture matches production get_db and all three
  failures above are application behavior, not fixture failures.
- New rendered/mounted checks: pending allocation and coordinated fixes. No fresh
  desktop/mobile, accessibility/contrast, keyboard or physical-device score is claimed.
  Impeccable audit guidance was used for current native operate-surface review;
  its five-dimension render score remains unavailable until actual mounted checks.
- Current official app access/granted scopes, Meta consent/account eligibility,
  authorized test recipients and real Instagram/WhatsApp inbound/outbound delivery:
  pending external evidence. No local test in this packet clears them.

All failed desired-safety probes remain failures until reviewed source fixes and
same-race reruns pass. Existing broad green suites do not substitute for these
specific native-session/privacy boundaries.

## Coordinated minimal repair ownership proposal

Keep this failing-baseline QA packet immutable. Start a separate runtime branch
from an integrator-approved checkpoint containing the final Instagram credential
writer/generation work. Proposed owned paths are channel_operator API and
channel_connections service, channel_operator HTML/JS, native v1_app JS, and new
focused tests/harness. Integrator retains main/config/package/scheduler and any
other shared OAuth/credential writer. Do not overwrite their newer guards.

- Use the shared native session/CSRF client and explicit current identity/session
  binding for channel page operations. Final fresh current-session/capability checks
  must happen before credential/check/operation commit after provider and lock waits.
- The callback's consumed-at commit remains durable before token exchange. A later
  revoked-session denial rolls back only final credential mutation, never makes the
  code exchange replayable. No network provider retry or implicit new OAuth attempt.
- Physical ended-access scrub must remove current facts, customer text/history,
  secret input values, open dialogs and action handlers. Replaced/older responses
  cannot restore them. Current role changes remove controls and links immediately
  after fresh checks. No credentials may enter browser journals/logs.
- Preserve existing exact idempotency keys/unknown results; secret-bearing pending
  setup needs explicit re-entry after uncertainty, with current configuration and
  generation safeguards. Do not claim GET or a generic error proves a secret save.
- Add actual mounted logout/session-replacement/stale-response/revocation tests,
  desktop/mobile captures and same-race PG reruns after approval. Existing provider
  connection checks remain synthetic and sends remain forbidden.

Profile/invitation wait checks and checklist completion semantics remain separate
coordinator-owned repair decisions. Consent/account selection/test features require
their own frozen product/provider contract; they are not part of this safety repair.
