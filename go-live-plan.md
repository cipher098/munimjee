# Munimjee V1 go live plan

Updated: 18 October 2026, Asia/Kolkata.

Status: execution remains authorized in isolated worktrees. The local implementation
now composes native signup/invitations, resumable profiles, reviewed catalogue imports
and private draft approval, explicit SKU activation, persisted publication of three
storefront designs, customer COD/online handoff, native payment settings, channel
operator recovery, ParcelDesk tracking/review and a membership-scoped assisted
onboarding board. Actual migrated PostgreSQL 16 and mounted browser checks provide
bounded local evidence; exact source, counts and failures are recorded in
`docs/v1-execution-status.md` and `docs/v1-wave6-validation.md`.

Assignment does not grant membership or impersonation. Wave5 adds explicit current-
owner-consented5–60-minute read-only readiness grants for server-provisioned operators,
truthful order-cohort analytics and dual authenticated endpoint-control customer links.
These remain deny-by-default and do not grant general tenant access, writes, history
merging or legal-person identity. Actual0052 full gate passes1524 tests with8 documented
skips; mounted support31/analytics21/customer14/native-import47 pass. Exact source,
failures and limits are in `docs/v1-wave5-validation.md`. V10 activity sources and the
complete onboarding/acceptance matrix remain tracked implementation scope.

Real SDK/payment and Meta approvals/canaries, private ParcelDesk provisioning/D1/TLS,
physical-phone testing and operational deployment remain gates. Isolated real PG16
restore tooling passes its fresh-pair reconciliation; packaged old/current compatibility,
native multiarchitecture and hosted CI billing remain separate release gates. Flags
stay off by default. No real provider request, charge, customer send, running-project
change or production cutover is authorized or claimed.

The verified/pushed complete checkpoint remains `abab30a`, actual0053:1950 backend
passes with8 documented skips; central native-import47/CSV74/SKU5 browser and28
mounted SEO HTTP checks. Its315-file arm64 image passes3 offline modes; fresh0053
restore53 is separate. Historical interrupted runs remain preserved.

Wave7 now composes observed first-party activity0054 (shared public hooks, new-order
provenance and ungated bounded retention cleanup), owned-Instagram private-original
retrieval/generation fences, and0055 immutable comment source/claim guards. The five
reproduced queued-comment safety failures are repaired in reviewed source and actual
owner tests; they are no longer labelled unfixed. Native channel late-session/privacy
and cross-writer generation fixes pass126 focused/25 mounted checks. Native workspace,
readiness and final invitation authority followup passes190 focused/6 mounted checks.
The local checklist advances from current reviewed facts while authorized messaging
acceptance remains explicitly unavailable. Instagram documentary compatibility is
bounded; both retrieval capabilities remain off and actual wire/grants are unproved.

Native comment controls and durable inferred-WhatsApp review0056 are now composed
and in their final actual-chain/browser gate (initial134 checks pass). They record
no-send reviews and preserve unknown effects; they do not replay earlier replies.
The older frozen0055 full run ended2325 passed,2 fixture failures,8 skipped; corrected
fixtures pass26 checks, but a new composed full run is still required. Source
composition is not complete acceptance. New-head runtime-image/restore/rollback
proofs are also pending; prior0053 artifacts never certify0054–0056.

Remaining code-owned work includes installed channel activity producers/outcome
reporting (currently null, not zero), supported WhatsApp v4 self-service consent and
account selection, authorized-recipient test/result workflow, and the rest of the
V1 acceptance matrix. Catalogue's0057 proposal is contract-first; no live provider
action is authorized. Remote mobile/accessibility/offline QA is active after the
connection recovered; only reviewed delivered results count. Provider approvals,
physical devices, international migration requirements and operational release
remain separate gates. Exact current evidence and ownership are in
`docs/v1-execution-status.md` and `docs/v1-wave7-contracts.md`.

## 1. The V1 outcome

A sales representative can onboard a boutique from its existing Instagram account and website, prepare and review its catalogue, publish a premium storefront, connect Instagram and WhatsApp, demonstrate catalogue-aware conversations, complete a purchase and manage the order without code changes or database edits.

Self-service sellers use the same onboarding flow. The sales team assists through permission-controlled access, not shared passwords. The initial supported segment is boutiques selling physical fashion products; "any seller" means any eligible seller within the documented V1 support envelope, not every business model or Meta account type.

V1 includes three ready website templates, reviewed catalogue imports, storefront and checkout, seller onboarding, channel connections, messaging and comment automation, orders/customer CRM, basic analytics and a sales onboarding console. Purchase dashboard means customer orders, sales and payments, not supplier procurement.

The existing 13-feature vision remains the longer-term roadmap. V1 is a complete selling workflow, not a thin implementation of all 13 features.

## 2. Scope and completion criteria

| ID | V1 capability | Completion criterion |
| --- | --- | --- |
| V01 | Seller and sales-team onboarding | Invite/signup, business details, roles, resumable checklist, progress/blockers and audited support access. A fresh seller needs no engineering intervention. |
| V02 | Three premium website templates | Editorial occasionwear, catalogue-led everyday fashion, and video-led boutique designs. Shared product/checkout components; configurable branding, sections, policies, previews and publication. Mobile and desktop work for all three. |
| V03 | Catalogue import | Import from a seller-authorized website and supported connected Instagram media. Uploaded videos/photos and CSV provide documented fallbacks. Jobs show progress, results and recoverable errors. |
| V04 | Catalogue review and maintenance | Candidate products, source evidence, image/video assets, duplicate candidates and reel mappings. Seller confirms factual fields, variants, prices and stock before publication. Reimports do not silently overwrite corrections. |
| V05 | Storefront and purchase | Searchable product/category URLs, filters, variants, stock, cart, Razorpay/COD, order confirmation and protected customer order status. Published APIs exclude private prices, credentials and notes. |
| V06 | Orders and customer CRM | Conversations, customer identities, order history, payment state, fulfilment, seller notes, tracking and cancellation handling. Identity links need a verified basis. |
| V07 | Self-service Instagram and WhatsApp | Official supported connection flows, account selection, permission/readiness checks, test, reconnect and disconnect. Expired access and incomplete provider setup have actionable states. |
| V08 | Catalogue-aware messaging and comments | Linked reel/post/product context, product questions, comment actions, human takeover, pause/resume and unresolved-product queue. Replies use approved facts; uncertainty triggers clarification or handoff. |
| V09 | Parcel tracking and customer updates | From an authorized order, seller scans an existing parcel barcode, confirms courier/AWB and order association, then the existing Parcel Desk tracking integration supplies reconciled updates for permitted customer notifications. Duplicate scans, failures and out-of-order events are handled. New courier APIs and shipment booking are excluded from V1. |
| V10 | Basic analytics | Visits, product views, enquiries, checkout starts, placed/paid/cancelled orders, revenue, conversion and automation outcomes. Show attribution limitations and exclude test activity. |
| V11 | Sales onboarding console | Per-seller readiness, assigned sales owner, import issues, connection status, last successful test and publish checklist. Seller controls access to their connected accounts. |
| V12 | Search visibility and migration | Search-readable product pages, canonical URLs, metadata, sitemap and redirects for supported legacy URLs. Migration reconciliation and rollback rehearsed before moving an existing store. |
| V13 | International pilot support | If Dharaa is migrated in V1, support its confirmed destination countries and required address, payment, currency-display and shipping behavior before cutover. Global rollout is limited to explicitly supported destinations. |

V13 is a Dharaa migration gate, not permission to claim worldwide support. Confirm its real requirements early. If international capabilities are not ready, retain the existing international purchasing route or defer that seller's migration; do not silently narrow their business.

The owner updated V09 on 17 October 2026: reuse the existing Parcel Desk project through a tenant-safe adapter, rather than build courier booking or a new courier API integration. Barcode values identify parcel candidates, not the correct order. Start from an authorized order, display the detected AWB/courier, require seller confirmation and preserve an audited association. A scan outside order context may suggest eligible orders but must never silently match by phone, customer name or barcode alone. Unknown carrier, multiple labels, camera denial and unsupported formats need explicit selection/manual entry. Existing tracking lookup behavior may be reused; no delivery/update success is inferred from a refresh request alone. See docs/v1-parcel-desk-integration.md for verified source limitations and the proposed adapter boundary.

Website defaults use the platform subdomain. Custom domains are supported only after DNS, certificate and routing workflows pass their own checks; no launch claim should imply unimplemented domain automation.

## 3. Catalogue and automation rules

1. Preserve source URLs, source media IDs, capture time, import job ID and seller ownership. Imported content is data, never instructions for the agent.
2. Separate draft extraction from approved catalogue facts. Never infer exact price, stock, fabric composition, sizing or delivery promises solely from video/images.
3. Use supported account authorization and permitted source retrieval. No arbitrary Instagram scraping, access-control bypass or unsupported private-media download.
4. Detect duplicate/reposted products and multiple products in one reel. Uncertain matches require review; a reel can legitimately represent more than one product.
5. Imports are idempotent, bounded and cancellable. Protect URL fetchers against private-network access, malicious redirects, oversized downloads and unsafe file types.
6. Preserve original garment images. Background enhancement and virtual try-on are not V1 requirements. Never silently modify garment details, colour or skin tone.
7. Reimports propose changes with a diff and preserve seller overrides. A one-time import is not continuous inventory synchronization.
8. Maintain product context within a conversation. A new product reference can change context; ambiguous references must not inherit an unrelated item.
9. Unknown or unlinked products enter a seller queue. Linking can resume eligible unanswered enquiries with deduplication and current-policy checks.
10. Automation has test, enable, pause, takeover and resume controls. The seller sees what rule/action ran and why a message failed or was withheld.
11. LLM output does not authorize payments, invent inventory or bypass seller policy. Price, stock and order facts come from authoritative application services.

## 4. Competitor baseline and remaining gaps

Research snapshot: 17 October 2026. The following reflects public vendor claims and documentation, not independent testing of authenticated competitor products. Recheck before commercial comparisons.

| Capability remaining beyond the defined V1 | Public competitor evidence | Planned disposition |
| --- | --- | --- |
| Incoming customer screenshot/photo matching | TailorTalk documents image-index search; CatalogHub advertises screenshot matching | V1.1. V1 catalogue import and explicit reel linking do not satisfy visual search. |
| Abandoned-cart and quiet-enquiry recovery | Both promote recovery/follow-ups | V1.1. Persist cart/checkout events now; automation sequences follow. |
| Alternatives, cross-sells and restock alerts | TailorTalk promotes these workflows | Later, using verified variant stock and explicit notification preferences. |
| Segmented WhatsApp broadcasts | Both advertise broadcasts/campaigns | After core messaging, consent, quotas and usage reporting are reliable. |
| Partial COD and COD confirmation | CatalogHub explicitly lists both | Next commerce increment; basic COD remains in V1. |
| Full returns, exchanges and refund automation | TailorTalk advertises assistance with returns/exchanges | V1 provides policy/handoff and visible refund-required states; full operational automation follows. |
| Ongoing external inventory sync | TailorTalk documents commerce connectors | Later. Import once and continuous synchronization are separate products. |
| Website chat and consultation scheduling | TailorTalk advertises both | Later. Website product enquiries can initially route to connected messaging. |
| Comment moderation | Both describe spam/impersonation protections | Later, with seller controls and review. |
| Virtual try-on | TailorTalk labels it beta | Research, not a release dependency. |
| AI website editing and broader marketing operator | CatalogHub promotes these; social publishing is marked coming soon | Keep on roadmap; do not copy every marketing promise into V1. |

Existing-parcel tracking and selected international commerce are included where the supported launch workflow requires them. Shipment booking and new courier API integrations are excluded from V1 by the owner’s 17 October scope change. Tracking must not be counted as delivered merely because the UI displays a tracking field or a currency selector.

CatalogHub's Dharaa case study reports existing search traffic and roughly half of recent orders shipping abroad. These vendor-reported figures justify validating international and SEO migration requirements early; they are not independently verified business metrics.

Primary sources:

- https://tailortalk.ai/
- https://tailortalk.ai/capabilities
- https://tailortalk.ai/guide/tools/image-search-tool
- https://tailortalk.ai/guide/catalog/catalog-tool
- https://tailortalk.ai/guide/getting-started/workflow
- https://www.cataloghub.in/
- https://www.cataloghub.in/instagram-auto-reply
- https://www.cataloghub.in/whatsapp-order-management
- https://www.cataloghub.in/customers/house-of-dharaa

## 5. The original 13 features

| Original feature | V1 position |
| --- | --- |
| 1 Instagram comment automation | Included |
| 2 Instagram DM automation | Included, bounded by catalogue/policies and human handoff |
| 3 WhatsApp automation | Included, bounded by catalogue/policies and human handoff |
| 4 Wholesale enquiry verification | Later: business evidence, seller decision, wholesale quotes |
| 5 Premium website with payments | Included |
| 6 Automatic delivery updates | Included through existing Parcel Desk tracking for confirmed order/parcel associations and permitted channels; booking excluded |
| 7 Global presence | Search visibility plus selected international destinations; not unrestricted worldwide commerce |
| 8 Organic reach optimization | SEO and basic measurement now; recommendations/experiments later |
| 9 Digital marketing | Later |
| 10 AI-generated personalized content | Catalogue draft assistance now; campaign studio later |
| 11 Social media post automation | Later |
| 12 Agentic abandoned-cart recovery | Instrumentation now; recovery automation in V1.1 |
| 13 Tailoring suite | Basic order note/customization enquiry now; measurements/production/trials/deposits later |

Longer-term differentiation remains occasion-aware custom orders, tailoring operations and wholesale qualification through quotation. These are hypotheses to validate with boutiques, not claims that competitors lack them.

## 6. Architecture decision

Use a selective rebuild in the existing application repository. Retain FastAPI, PostgreSQL, SQLAlchemy/Alembic and Celery/Redis. Keep a modular backend with shared contracts; parallel developers do not require microservices.

Retain and adapt:

- Razorpay validation, captured-payment authority, signed callbacks, encrypted credential snapshots and late-payment review behavior.
- Server-authoritative totals, idempotent checkout, stable stock locking and once-only reservation release.
- WhatsApp signed ingestion, durable outbound delivery, consent checks and uncertain-send review.
- Instagram provider adapters, comment rules, reel mapping, seller takeover and useful regression cases.

Redesign shared seams:

- Business, User, Membership/Role and ChannelAccount instead of a single Seller object carrying every responsibility.
- Canonical Customer plus independently identified channel accounts; explicit identity-link provenance.
- One channel-independent order core with payment, fulfilment and immutable item/price snapshots.
- Real SKU/variant inventory and reservations; JSON labels and aggregate stock are insufficient.
- Durable incoming events and outgoing actions, replay protection and structured automation history.
- One seller application shell and a server-rendered storefront with stable product routes. The marketing site stays a separate surface; its claims follow released functionality.

Existing source evidence: `backend/app/models/seller.py`, `models/order.py`, `models/commerce.py`, `models/product.py`, `services/commerce.py`, `services/razorpay_payments.py`, `workers/whatsapp.py`, `workers/message_batch.py`, and `backend/static/`.

Known risks to address, not assertions of observed production incidents:

- Legacy Instagram messages use a Redis buffer with a 120-second TTL; accepted work needs durable persistence before acknowledgement.
- Provider order creation can succeed before its response is persisted. Introduce an explicit uncertain-operation state and reconciliation rather than assuming every retry is safe.
- Test fixtures reset schemas, and some trust the configured database URL. Parallel testing requires a safe centralized harness first.
- CI currently applies migrations but many tests then recreate tables from ORM metadata. Add tests against the actual migrated schema.

## 7. Shared contracts before implementation branches diverge

Contract owners agree on versioned schemas, examples and error responses for:

| Contract | Required decisions |
| --- | --- |
| Tenant/access | Business ID, user memberships, role capabilities, support authorization and audit events |
| Catalogue | Product/SKU IDs, media, prices/currency, stock/reservation rules, source mappings and approval state |
| Import jobs | Source authorization, progress, checkpoints, draft changes, review decisions and cancellation |
| Customer/conversation | Channel identifiers, linked identities, consent, product context, takeover and message pagination |
| Order/payment | Idempotency, order lines, totals, payment attempts, fulfilment, cancellation and refund-required states |
| Shipment | Order-scoped confirmed parcel association, normalized courier/AWB, trusted Parcel Desk adapter, tracking events, reconciliation and customer-update idempotency; no booking |
| Analytics | Event IDs, timestamps, tenant, source, test exclusion and precise metric definitions |
| Website | Theme configuration, preview/publish state, public field allowlist and canonical URL rules |

Use contract fixtures so UI and backend can develop concurrently. Proposed changes require consumer-impact review; do not silently change a field or event meaning.

## 8. Six parallel workstreams

Target capacity is three implementation workers on this Mac and three on the Mac mini, plus coordination. Actual remote runtime/account capacity must be checked; if fewer workers are available, queue the same tasks without weakening ownership or gates. This chat does not assume it can directly spawn agents on the other host.

| Lane | Host | Ownership |
| --- | --- | --- |
| A | This Mac | Business/user/customer foundation, seller onboarding, sales console, CRM and analytics UI |
| B | This Mac | Catalogue/SKUs, inventory, unified order/payment core and domestic/international checkout |
| C | This Mac | Instagram/WhatsApp account connections, inbox, durable channel events, rules and catalogue-aware replies |
| D | Mac mini | Website/media import and catalogue review; then existing Parcel Desk adapter, barcode association and tracking updates |
| E | Mac mini | Shared frontend components, three storefront themes, real catalogue/checkout wiring and SEO routes |
| F | Mac mini | Isolated environments, contract/regression/migration tests, browser acceptance and evidence review |
| Integrator | This chat / designated integration checkout | Contract decisions, shared-file changes, migration ordering, branch integration and release gates |

Feature owners implement their feature screens using E's shared UI components. E does not become the sole frontend implementer for every lane. F writes independent cross-feature checks; implementation owners fix failures.

### Preparation tasks

| Task | Owner | Dependencies | Deliverable |
| --- | --- | --- | --- |
| P00 Preserve baseline | Integrator | None | Inspect both existing checkouts, preserve valuable uncommitted work, record source SHA and baseline failures. Do not reset the running setup or copy secrets into Git. |
| P01 Establish isolated runtimes | F | P00 | One environment per task on both hosts: worktree, ports, DB, Redis namespace/instance, queues, uploads and disposable fixtures. Safe reset guard demonstrated. |
| P02 Freeze initial contracts | Integrator with A/B/C/D/E | P00 | Entity/API/event schemas, module ownership, representative fixtures, migration strategy and acceptance cases. |
| P03 Resolve external dependencies | Integrator with account owner | P00 | Current Meta app access, supported onboarding flows, authorized test accounts, Razorpay test account, Parcel Desk machine-access/tenant boundaries and authorized tracking test path, and Dharaa destination requirements. Independent development continues if these are pending. |

P01, P02 and P03 can proceed concurrently after P00. UI prototypes and contract fixtures may start while provider access is pending; they are not integrated completion.

### Build wave one

| Task | Owner | Dependencies | Acceptance |
| --- | --- | --- | --- |
| A10 Business and identity | A | P01/P02 | Roles and seller-scoped APIs; verified identity links; inviter and seller access tests |
| B10 Catalogue and inventory | B | P01/P02 | Variant prices/stock, reservations, protected public fields, legacy mapping |
| C10 Connections and durable ingress | C | P01/P02 | Connect/reconnect/disconnect states, seller-account binding, durable receipt and replay protection |
| D10 Import and review | D | P01/P02 | Website plus supported Instagram/media import, deduplication, resumable jobs and seller-approved publishing |
| E10 Frontend shell and themes | E | P01/P02 | Shared components and all three themes against contract fixtures; responsive preview/publish UI |
| F10 Independent acceptance harness | F | P01/P02 | Multi-seller fixtures, contract checks, migrated-schema tests and browser journey scaffolding |

### Build wave two

Tasks begin when their own dependencies pass; no need to wait for the entire previous wave.

| Task | Owner | Dependencies | Acceptance |
| --- | --- | --- | --- |
| A20 Onboarding and sales console | A | A10, connection/import contracts | Fresh seller checklist; audited sales assistance; visible blockers and resumability |
| B20 Checkout and payment | B | B10, A10 customer contract | Canonical orders, COD/Razorpay, retries, cancellation, uncertain attempts and protected status |
| C20 Inbox and automation | C | C10, B10, A10 | Product context, comment/DM rules, previews, takeover, unresolved mapping and guarded resume |
| D20 Parcel tracking | D | B20 order contract, C10 delivery contract, P03 adapter trust | Order-context barcode scan with seller confirmation, tenant-safe existing Parcel Desk integration, tracking reconciliation and idempotent customer-update outbox |
| E20 Real storefront integration | E | E10, B10, B20 | All three themes use real APIs; browsing to purchase; URLs and indexing validated |
| F20 Cross-module verification | F | Completed slices | Independent tests on integrated source SHA; failures routed to owners |

D can build the Parcel Desk adapter and confirmed association contract against fixtures before B20 is merged. E can wire read-only catalogue pages before checkout is ready. C can verify inbound/context flows before outbound live access is available.

### Build wave three and release candidate

| Task | Owner | Dependencies | Acceptance |
| --- | --- | --- | --- |
| A30 CRM and analytics | A | A10, B20, C20, shared event schema | Unified seller view and metrics reconciled to source orders/events |
| B30 International pilot and migration | B | B20, D20, P03 | Supported destinations, address/shipping/payment rules, ledger reconciliation and migration rehearsal |
| C30 Provider canaries | C with integrator | P03, C20 | Actual account connection and inbound/outbound/comment evidence; reconnect/revocation behavior |
| D30 Import/tracking recovery | D | D10, D20 | Restart, rate-limit, partial import, tracker timeout, duplicate association and status ordering checks |
| E30 Usability and SEO migration | E | E20, source URL inventory | Mobile checks, theme parity, redirects, metadata, accessible critical controls |
| F30 Full product verification | F | Integrated release candidate | Entire acceptance matrix, provider evidence, load/restart checks and release report |

The critical path is baseline/contracts/isolation → SKU/customer/order foundations → real checkout and channel integration → shipment/status/analytics → release verification. More workers cannot bypass these dependencies.

## 9. Agent execution protocol

Each task ticket must contain: task ID, owner/host, exact base SHA, branch/worktree path, allowed modules, contract version, dependencies, acceptance tests, fixtures, expected artifact paths, forbidden external effects and known blockers.

Execution loop:

1. Claim one ready task; inspect current instructions and dependencies.
2. Create/reuse the assigned isolated worktree from the recorded integration SHA.
3. Implement within ownership boundaries. Request a contract decision before modifying a shared interface.
4. Run focused tests and the relevant browser workflow. Use synthetic tenants and test providers by default.
5. Submit a small reviewable diff with evidence, known limitations and exact tested SHA.
6. Integrator reviews and merges in dependency order; run relevant integrated checks on the merged SHA.
7. F independently verifies the cross-feature behavior. Failed tasks return to their owner.
8. Continue with the next unblocked task. Report external blockers precisely and work on independent tasks.

Only the integrator orders migrations and changes shared startup/auth/worker registration or dependency files. Domain owners can propose migrations; integrations must end with a reviewed coherent migration history. No blanket automatic schema conflict resolution.

Use Git pushes/PRs to exchange code between hosts, not shared editable folders. Preserve the existing development setup and demo deployments. No blanket copying of `.env`, customer data or credentials to the Mac mini.

Remote task dispatch requires a verified saved project and explicit delegation through the available host tools. Work instructions must identify this plan and authorize status reporting to the coordinating task. A sent task is not a completed task: wait for its final status, inspect the diff and verify evidence.

UI automation is serialized per browser session. Different hosts can run independent sessions. Do not let two agents drive the same tab or consume the same provider test number concurrently. Account for shared Codex/provider rate and usage limits; reduce concurrency if it causes contention.

## 10. Test strategy

"Completely tested" means every agreed critical path and failure case has passing evidence on the release candidate. It cannot mean all possible inputs or provider behavior have been exhausted. Mocked providers, successful builds and existing test files alone are not release proof.

### Automated code verification

- Unit tests for validation, state transitions, pricing, context selection, import matching and permissions.
- Contract tests for API/event producers and consumers, including error formats and pagination.
- Integration tests against independently disposable PostgreSQL/Redis using actual Alembic migrations. At least one complete path must not recreate tables with ORM metadata.
- Negative multi-tenant tests for every seller-owned resource and worker action; owner, staff, sales-support and unauthorized roles.
- Concurrency/replay tests for checkout, stock, payment callbacks, inbound events, imports, comment replies and resumed conversations.
- Provider fault tests for timeouts after acceptance, retries, rate limits, reordered callbacks, worker restart and revoked access.
- Frontend type/build checks plus maintained browser end-to-end tests in CI. JavaScript syntax checks alone are insufficient.
- AI regression set covering known products, multi-product reels, unavailable variants, unknown prices, switching product context, mixed-language questions, malicious imported instructions and handoff. Hard gates: zero cross-tenant disclosure, invented price/stock or unauthorized financial action in this set. Soft answer-quality thresholds are recorded before evaluation, not adjusted to fit results.

### Actual product acceptance matrix

| Test | Required observed result |
| --- | --- |
| Fresh seller onboarding | New seller completes invitation/signup, settings, reviewed catalogue, theme and publication without DB edits. Checklist resumes after logout. |
| Sales assistance | Sales rep sees assigned seller readiness and authorized support tools; cannot access another seller or reveal credentials. |
| Website import | Seller-authorized source yields drafts with provenance; repeat import creates no accidental duplicates; seller corrections survive. |
| Instagram/media import | Connected seller's supported media imports; expired access is recoverable; multiple products/unknown prices require review. Uploaded-media fallback is tested separately, not counted as successful API import. |
| Three-theme parity | Each theme passes browse → variant selection → cart → checkout → confirmation on desktop and phone layouts. Theme changes preserve catalogue, cart semantics and links. |
| Product integrity | Sold-out size cannot be purchased; private floor price is absent; inactive/unpublished products are hidden. |
| COD purchase | Customer and seller see the same order; confirm/pack/ship/deliver and COD collection behave consistently. |
| Razorpay test purchase | Real provider test checkout, callback and webhook reach the application; refresh/retry does not duplicate the order or settlement. Failed/cancelled/late payment paths also have evidence. |
| Stock contention | Concurrent attempts against limited stock never reserve or sell more units than available; expiry/cancellation releases once. |
| Instagram comment | Authorized test comment on linked media triggers the configured action; duplicate delivery does not duplicate actions. |
| Instagram DM | Actual inbound DM appears and receives a correct catalogue-grounded response; handoff prevents competing bot replies. |
| WhatsApp connection and reply | Seller authorizes the correct account; actual test-recipient inbound/outbound delivery appears in the inbox with provider status. |
| Unknown reel | Enquiry enters the queue; linking and eligible resume sends the correct product response once; ineligible cases show the reason. |
| Product context switch | A second product reference updates context; an ambiguous message is clarified rather than answered about an unrelated item. |
| Messaging policy | Paused/disconnected/opted-out recipients are not sent messages; closed-window behavior follows the configured current provider rules. Boundary timing can use controlled fixtures; live delivery is verified separately. |
| Parcel association and updates | Seller opens the correct order, scans its existing parcel barcode, confirms courier/AWB and association, then an authorized existing-tracker lookup and permitted customer update succeed. Ambiguous/unknown couriers require selection or manual fallback. Cross-seller association is denied; duplicate scans/notifications and out-of-order updates cannot duplicate or regress state. No booking test is required in V1. |
| Order privacy and history | Customer order link authorizes only its order; seller sees consistent messages, history and fulfilment state. |
| Analytics reconciliation | Known test dataset produces exact defined totals; test activity is excluded from seller production metrics; unknown attribution remains unknown. |
| Disconnect/reconnect | Revoked access becomes visible, queued actions respect state, and reconnection cannot attach another seller's account. |
| Import/worker restart | Interrupted work resumes or reports a recoverable state without duplicate products, messages, payments, parcel associations or tracking notifications. |
| Search and migration | Supported old URLs redirect to correct products; canonical/meta/sitemap content is correct; existing order links still work. |
| International pilot | For every supported launch destination, address acceptance, delivery eligibility, charges, payment currency and confirmation are tested. Unsupported destinations are explicit. |
| Backup and rollback | Restore a sanitized backup in an isolated environment; reconcile IDs, totals, reservations and pending actions; demonstrate safe application rollback/forward fix. |

Agent browser testing exercises the deployed staging product using the available computer-use browser tools, including actual button interactions, form validation, network-backed results and screenshots. CI browser tests provide repeatability; exploratory product testing catches usability and integration issues beyond those scripts.

Inspect 360/390px phone, 768px tablet and 1440px desktop layouts. Check keyboard navigation, focus, labels, contrast, empty/error/loading states and long names. Record mobile/browser limitations honestly. A real iPhone/Android check is required for critical login, checkout and touch-media flows before claiming physical-device validation; request an owner check if no device is available.

Load checks use synthetic traffic and fake provider transports, not mass live messages. Define an expected pilot traffic envelope before running the test; record latency, error rate, backlog drain and recovery. Compare measured mobile performance against an agreed budget, distinguishing lab results from field metrics.

### Evidence and reporting

For each task/release save `artifacts/v1/<task-id>/<run-id>/`: source SHA, environment identifier, commands/results, test counts and skips, browser screenshots, sanitized provider references, observed outcomes and unresolved issues. Do not store tokens, customer message bodies or sensitive payment data in public artifacts.

Task states: planned → ready → implementing → code-verified → product-verified → integrated → released. Also track blocked and failed explicitly. Tests skipped because credentials, permissions or devices are unavailable remain pending gates, not passes.

Only call a feature complete when its API, UI, persistence, error paths, permissions and acceptance evidence are present. Any mock-backed-only feature is labelled simulated until the real integration gate passes.

## 11. External dependencies and autonomous boundaries

Resolve these early, while independent development runs:

- Meta app's actual permission/access status, business onboarding eligibility and supported Instagram/WhatsApp signup flow. Historical approvals are not assumed current or sufficient.
- Seller-owned test Instagram account/media, WhatsApp account/number and specifically authorized message recipients.
- Razorpay test credentials, webhook access and approved production account when launch requires it.
- Parcel Desk connector trust and machine access, tenant/order ownership, supported existing carriers, actual refresh schedule for the selected deployment, authorized synthetic parcel/order fixtures and recipient permission. No courier booking credentials or shipment-purchase budget are required in V1.
- Seller permission to import media/catalogue, publish policies and connect accounts; Dharaa's real migration requirements.
- Production hosting, domain ownership, secret provisioning, backup destination and operational owner.

Agents can autonomously implement, refactor within scope, create test fixtures, run isolated checks, inspect staging and fix failures. Live account login/OTP, consent screens, legal declarations, new permissions, paid transactions and provider approvals may require account-owner actions. Never bypass them or mark them passed from mocks. Request a narrowly scoped action, record the blocker and continue other lanes.

No unsolicited real-customer messages or ad spend. Live canaries use explicitly authorized accounts/recipients. Production deployment/cutover is a separate release action after evidence is ready and the owner authorizes it. Current authorization includes parallel implementation and isolated testing; production cutover remains separate.

## 12. Release gates

| Gate | Required evidence |
| --- | --- |
| G0 Baseline | Source preserved, known failures recorded, host setup verified and no secrets committed |
| G1 Parallel readiness | Contracts frozen, ownership assigned, isolated environments and safe reset tests pass |
| G2 Functional integration | Every in-scope module works against real application APIs and migrated schema; no contract placeholders |
| G3 Provider readiness | Actual Meta connections/messages/comments, Razorpay test checkout and authorized existing-parcel tracking/update canaries pass for supported scope |
| G4 Product readiness | Full acceptance matrix passes on the integrated release candidate; all three themes and sales-assisted/self-service onboarding verified |
| G5 Pilot readiness | Pilot scope/limits documented; migration/restore rehearsed; alerts, usage limits, support runbooks and deployment rollback prepared |
| G6 Production cutover | Owner approval, provider production readiness, final backup and controlled rollout; production smoke checks and reconciliation pass |

No unresolved critical data-loss, cross-seller access, incorrect-payment, overselling or duplicate-send defect may pass a release gate. Lesser limitations require explicit documentation and an owner decision; they cannot silently remove an agreed V1 requirement.

Define analytics precisely: placed orders include unpaid orders; paid revenue requires authoritative payment; COD collection is separate; refunds/cancellations have explicit treatment; conversion denominator and attribution window are shown. Start with measurable source/referral data rather than claiming perfect cross-channel attribution.

Pilot in stages: internal synthetic seller → one consenting boutique → a small named seller cohort → broader sales-team onboarding. Each promotion depends on evidence, not a calendar date. Track import correction rate, onboarding completion/time, enquiry resolution, handoffs, order/payment accuracy, failed operations and support effort. Set expansion thresholds before the pilot; sample onboarding with a sales representative who did not build the software.

## 13. Migration and rollback

Add canonical tables and compatibility adapters. Preserve product IDs, source links, customer identity provenance, historic orders, payment evidence, credential snapshots, reservations, consents and pending/unknown sends.

Backfill and reconcile before changing readers. Switch one workflow at a time with a single authoritative writer and feature flags. Do not run two engines that independently send messages or reserve stock. Compare side-effect-free shadow results where useful; never shadow-send customer messages.

Inventory current storefront URLs and ownership before promising redirects. Preserve old links while new URLs become canonical. Verify redirect behavior with the actual domain owner/provider; a third-party subdomain may not be redirectable by Munimjee alone.

Rollback means a tested application switch or forward fix that preserves post-cutover transactions. Dropping new tables or restoring an old backup over new paid orders is not an acceptable routine rollback.

## 14. Initial execution status

Execution began on 17 October 2026. P00 preserved both dirty checkouts in private local snapshots and copied reviewed application changes into integration commit e7694ff. Original checkouts and running services remain unchanged. At initial execution the Mac mini had GitHub push access but unavailable Docker capacity; actual migrated database verification for this batch runs on this Mac. The current evidence does not certify a remote database environment.

The isolated integration branch now composes native onboarding, catalogue/order
operations, reviewed import allocation into private drafts, persisted public settings
for three designs, native payment settings and synthetic online-payment recovery,
channel review, ParcelDesk scan/link and reviewed association recovery, and the scoped
assistance board. Actual migrated PostgreSQL 16, mounted browser, failure-matrix and
runtime-image evidence are recorded in docs/v1-execution-status.md and
docs/v1-wave4-validation.md. No local proof is a release or deployment. The Wave5 extension adds bounded consented
read-only support, order-cohort analytics and explicit endpoint-control customer links.
Full activity analytics, remaining self-service/source acceptance and the complete
V1 matrix remain tracked scope. Unconsented global tenant discovery/write access
remains deliberately denied; explicit expiring owner grants provide bounded
read-only assistance without impersonation. Keep marketing claims aligned
with released features.
