# Wave 5 bounded contracts

Base: `3082f1aa2f579b622bb09ae1fc3e238e20818e1f`, 18 October 2026.
All workers remain GPT-6.1 Sol/high. Work stays isolated; no production deployment,
provider/customer send, paid request, original ParcelDesk edit or running checkout change.

## Ownership and schema order

- Integrator: support consent/grants, separate scoped assistance view, shared auth,
  main/nav/package/config, integration and evidence. New worktree
  `work/munimjee-v1-support-grants`; revision `0051_v1_support_grants` follows actual0050.
- Catalogue: new analytics_v1 service/schema/router/page/tests/docs, no DDL.
  `payment_w3` only; native browser8163. Shared seams proposed to integrator.
- Social: additive verified customer links and scoped proof hooks, revision
  `0052_v1_customer_links` follows real0051. `parcel_w3` only; coordinate8155/8156.
  Also independently reviews support security. No fake migration predecessor.
- Remote: CI/restore/rollback/multi-architecture rehearsal, dispatched by root.
  No schema reservation and no production access implied.
- Central/support own `wave3_integration` sequentially under P01's exact URL and lease.
  No new socket allowance, environment fallback or other database use.

## Explicit assisted access: minimal supported policy

Normal assignment and membership remain unchanged. No normal membership resolver,
legacy login, seller token or existing business mutation accepts a grant.

Default-off `V1_SUPPORT_GRANTS_ENABLED`; trusted operator UUID allowlist is an
explicit server setting, empty by default. No browser can provision operators or
turn an arbitrary signup/email/domain into a trusted support identity. Removing a
subject from the configured allowlist immediately denies its grants. UUID selection
is administrative provisioning, not email verification.

Only a current active native business owner can create or revoke consent. Owner
explicitly chooses one existing allowlisted active native user, an activity reason,
exact scope `readiness.summary`, and a UTC expiry between5 and60 minutes from the
current database clock. One active grant per business/subject is allowed; renewal
creates a new consent record after expiry/revocation. No extend/edit/resurrection.
Consent is never inferred from an assignment, support request, manager action,
login, shared password, email/phone/name or administrator impersonation.

Grant binds tenant, subject, consenting owner and both users' current auth versions.
All reads recheck active Business/Seller, current subject/user/session, configured
allowlist, current consenting-owner membership/user/auth version, immutable scope,
expiry and irreversible revocation. Native session/CSRF and current owner authority
are checked after waits and again before caller-owned commit. Use database wall
clock for expiry, not transaction-start time. Business NO KEY UPDATE serializes
creation/revocation without conflicting with ordinary tenant FK checks.

The separate operator board lists only the actor's currently consented businesses
(name/scope/expiry). It cannot search/discover other sellers. Readiness detail requires
an audited explicit native POST/open with exact-key command recovery; it returns
only safe counts/status and local/external gate descriptions. No source media,
customer/order/inbox facts, staff emails, credentials, provider identifiers or
native member-workspace links. No grant permits writes, publication, connection,
replay, messaging, stock/order/payment changes or membership management. Existing
native endpoints still require real membership even for a granted operator.

Owner management and operator reads use native own-account sessions, no-store,
no-referrer/noindex and current-authority checks. Exact actor/operation/body command
receipts and access audit are immutable, tenant-bound and atomic. Replayed open
requires a currently valid grant; expiry/revocation never returns an old snapshot.
Revocation cannot recall a response or provider action already completed; this slice
has no provider action. Private UI journals are session/user/business-bound and are
cleared on identity/401; no automatic mutation replay.

No unrestricted global seller access or support-write policy is inferred. Before
expanding this scope, the owner must define trusted operator provisioning, permitted
write capabilities, consent renewal/escalation and incident access policy. The
current implementation stays default-empty/read-only until provisioned explicitly.

## Truthful seller analytics

Read-only canonical commerce_orders; UTC created-order cohort [from,to), default
last30UTC dates, max366, current payment/fulfillment/method filters. Exact values
remain grouped by currency and include shipping. Placed includes unpaid; captured
Razorpay requires paid+gateway_payment_id; COD collected is separate; captured
review_required is separate. Cancellation union and expiry may overlap; never
claim net cashflow/settlement-date revenue. No paid_at/refund-completion source.
Known immutable credential snapshot mode=test is excluded by default; unclassified
COD/uninitialized orders are visibly unknown, not asserted production-only. No
current-account-mode inference. Visits/conversion/fees/refund completion/attribution
are unavailable/null, never fabricated zeros. Safe order rows contain no customer,
provider or credential data. One SQL statement gives a coherent cohort projection;
native analytics.read and session revalidated before/after reads. No support grant
confers analytics.read.

## Customer endpoint control and explicit consent

No matching or backfill merge by name, phone or profile. Add canonical customer and
seller/channel/account/sender-bound endpoints without moving messages, orders,
payment facts or consent. Native automation.manage starts an explicit pair challenge;
inbox.read views.10-minute challenge, exact whole text `LINK <43-char URL-safe secret>
I CONSENT` independently received from BOTH selected endpoints through the existing
signed provider ingress after issuance. Per-source message ID dedupe, current account
configuration binding and bounded provider/receipt times required. Hash-only durable
secret; audit/DTO/logs never echo raw proof command except its authorized no-store
creation/replay display. Reserved token-shaped commands are withheld from ordinary
agent processing even when disabled or invalid; no new sender is added.

Explicit current-native finalization requires both fresh proofs under locks and active
same-tenant/account bindings. Existing association conflict requires review; no merge.
Unlink immediately removes verified lookup while retaining provenance/history/consents.
The proof means control and consent for these two account records, not legal-person
identity or marketing/payment authority. Automation may obtain only canonical UUID,
not joined private history. Synthetic signed webhook tests are wiring evidence; real
provider/consent canary remains an external gate.
