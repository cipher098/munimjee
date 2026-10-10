# CatalogHub parity: baseline and delivery plan

Audited 10 October 2026 against `v0.1` at `a2222be4a9c1aac607e668b5df93cc603f37c589`.

## Product target

A seller should be able to publish a mobile storefront, sell from a product link or Instagram conversation, accept a real order, confirm payment, fulfil it, and keep the customer informed from one dashboard. That is the baseline before adding differentiating features.

CatalogHub's documentation is evidence of its advertised workflows, not independent verification of its production behavior. Its [homepage](https://www.cataloghub.in/) advertises storefronts, catalogue management and CRM; it labels some marketing and reporting features as coming soon. Those planned features are outside the first parity milestone.

Its [WhatsApp order-management page](https://www.cataloghub.in/whatsapp-order-management) describes checkout, payment providers, COD/partial COD, shipping integrations, order updates, cart recovery and campaigns. Its [Instagram automation page](https://www.cataloghub.in/instagram-auto-reply) describes product/reel mapping, comment-to-DM automation, keyword rules and product recognition. These provide the comparison baseline below.

## What the code actually supports

“Partial” means useful implementation exists, but the complete seller/customer workflow was not established by this audit. Repository product notes and `plan.md` are not treated as proof of working features.

| Capability | Munimjee on the audited branch | Work needed for baseline |
| --- | --- | --- |
| Seller onboarding and account access | Signup, login, Instagram OAuth and seller/admin dashboards exist | Complete account-linking authorization review, OAuth state lifecycle and tenant isolation across all routes and workers |
| Product catalogue | Products, categories, photos, prices, tags and active status exist | Seller isolation fixes in this change; pagination/search, import/export, richer product information and inventory controls still needed |
| Variants and stock | Variant labels/photos are JSON; stock is aggregate per product | SKU-level options, price, stock and inventory reservation; zero-stock fix in this change |
| Customer storefront | No public storefront/catalogue route or customer cart found | Store profile, publication controls, product pages, navigation/search, shareable URLs and mobile cart |
| Checkout and orders | Order models exist but require Instagram conversation/customer identifiers | Channel-independent checkout; address, delivery rules, totals, immutable order-item snapshots and seller order management |
| Payments and COD | Payment methods, screenshot analysis and payment/order state exist | Gateway-confirmed payments, idempotent callbacks, explicit manual-review state, COD rules, refunds and reconciliation |
| Shipping | Delivery models and dispatch-notification worker exist | Seller fulfilment UI, shipment creation, labels/tracking, status reconciliation and failure handling |
| Instagram selling | DM webhook, product/reel matching, negotiation and seller takeover exist | Comment event ingestion and keyword-to-DM workflow; end-to-end verification on a connected professional account |
| WhatsApp and CRM | Outbound WhatsApp helper exists; no complete inbound/customer support workflow found | Per-seller connection, inbound webhook, consent/templates, shared inbox, customer history and order notifications |
| Recovery and analytics | Conversation nudge worker and LLM cost reporting exist | Commerce events, conversion/revenue reporting, cart recovery and campaign controls |

Code entry points: `backend/app/main.py`, `backend/app/api/routes/`, `backend/app/models/product.py`, `backend/app/models/order.py`, `backend/app/bot/conversation.py`, `backend/app/api/webhooks/`, and `backend/app/workers/`.

## First implementation: catalogue foundations

This change is a foundation increment, not a parity release:

- Scope product edits, category-tag operations and product-tag reads/writes to the authenticated seller. Admin access follows the existing selected-seller behavior.
- Reject categories owned by another seller before uploads or AI calls. Validate complete tag batches against the product's category before saving or delivering answers.
- Preserve stock `0` as sold out. Omitted stock stays unchanged; `clear_stock_tracking=true` explicitly restores untracked stock. The product editor uses the new field when the stock input is blank.
- Reject negative prices and stock quantities below the legacy unchanged sentinel `-1` on updates.
- Resolve static/upload paths relative to the backend directory so the application can run and be tested outside its Docker `/app` layout. Docker paths remain equivalent.
- Add 23 HTTP regression tests using two sellers, real signed sessions and isolated PostgreSQL. External AI is stubbed.

No schema migration is required. API consumers that previously sent `stock_quantity=0` to disable tracking must now send `clear_stock_tracking=true` instead.

## Delivery sequence and acceptance gates

### 0. Finish commerce safety foundations

The catalogue changes above are complete on this branch. Remaining work:

- Review seller ownership across onboarding/account linking, media, conversations, payments and background jobs. Catalogue tests do not certify all tenant boundaries.
- Bind Instagram account linking to the authenticated seller and use expiring, single-use OAuth state tied to the initiating session.
- Prevent screenshot OCR alone from marking an order as financially paid. The current conversation flow records `ocr_auto` and can move an order to `payment_confirmed`; bank/gateway confirmation or an explicit seller review must be authoritative.
- Reconcile the six existing model-provider test failures with the intended provider configuration. Record the missing replay fixtures before relying on the five skipped conversation tests.

Gate: seller A cannot read/change/link seller B's resources; a plausible payment screenshot cannot release an order for fulfilment by itself.

### 1. Publish a real storefront and catalogue

- Add per-seller store name/slug, logo, contact details, policies, currency and publish state. Keep unpublished stores private.
- Expose an explicit public product response that excludes floor prices, internal tags, seller credentials and bot controls.
- Add category/search navigation, product details, option selection and mobile cart. Reuse the Dharaa demo's visual direction once it is backed by these APIs.
- Model sellable SKUs/options with independent price/stock where applicable. Decide clearly which legacy label-only variants can migrate automatically.

Gate: two sellers can publish distinct stores; inactive/out-of-stock items behave correctly; private negotiation data is absent from every public response.

### 2. Checkout, payment and order management

- Add channel-independent customers and orders; do not manufacture Instagram conversations for web purchases. Preserve existing DM orders during migration.
- Calculate all prices, discounts, delivery charges and totals on the server, using integer paise. Store immutable item/option/price snapshots.
- Separate payment state from fulfilment state. Reserve inventory transactionally, expire unpaid reservations, and prevent duplicate orders under retries.
- Implement one selected payment provider and COD first, with signed webhook verification, amount/currency/order checks, replay protection and reconciliation. Partial COD follows once the payment model supports balances correctly.
- Give sellers an order list/detail view with filters, payment review, cancellation/refund workflow and customer-visible confirmation/status.

Gate: price tampering fails; duplicate webhooks do not duplicate payments; simultaneous orders cannot oversell; cancelled/expired orders release stock; customer and seller see consistent status.

Provider selection remains open: Razorpay + COD, Cashfree + COD, or explicit manual payment review + COD. Production setup needs the seller/provider account and webhook credentials; test mode must be visibly distinct.

### 3. Fulfilment and customer support

- Add one shipping provider, delivery/serviceability rules, shipment creation, tracking and retryable status synchronization.
- Add customer profiles with channel identities, order history, notes and a seller inbox linked to orders. Merge identities only with a verified basis.
- Send transactional order messages through the customer's available, permitted channel. Handle delivery failures and opt-outs.

Gate: a seller can move an order from placement through delivery and handle a cancellation/return without database edits.

### 4. Social automation and retention parity

- Add Instagram comment ingestion, keyword rules and comment-to-DM product links with event deduplication and human handoff.
- Complete per-seller WhatsApp onboarding, inbound messaging, templates, consent and a usable shared inbox.
- Add abandoned-cart recovery and basic sales/conversion reporting backed by real commerce events.

Gate: demonstrate the complete Instagram/WhatsApp-to-order journey using connected test accounts, including opt-out, duplicate events, account disconnection and failed message delivery.

### After the baseline

Differentiate with the guided clothing customization journey, measurement reuse, occasion/date-aware ordering and seller-assisted recommendations. These should use the same catalogue, order and fulfilment models rather than create a second checkout path.

## Validation for this increment

- New catalogue suite: **23 passed**. Before the fixes, **18 failed and 5 passed**.
- Full existing + new suite: **285 passed, 6 failed, 5 skipped**. The suite is not fully green.
- The same six failures reproduced on an untouched export of the audited commit: tests expect Gemini, while the shipped `agents.yaml` selects Anthropic. This change does not alter model selection or those assertions.
- The five skipped tests lack recorded API replay fixtures. No live Meta, payment, shipping or AI integration was verified.
- Tests used an isolated local PostgreSQL cluster and placeholder credentials; no production database was used.

To run the focused suite, install `backend/requirements.txt`, provide the usual app settings with `DATABASE_URL` pointing to a **dedicated disposable PostgreSQL instance**, then run `python -m pytest tests/test_catalogue_boundaries.py -q` from `backend/`. The repository's database fixture creates and resets a sibling test database; do not point it at shared or production infrastructure.
