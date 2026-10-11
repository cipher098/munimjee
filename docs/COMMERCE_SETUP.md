# Storefront and commerce setup

This increment adds a working public catalogue, cart, COD checkout, Razorpay integration, seller order/customer screens, manual fulfilment and payment-evidence review. It does not yet complete every CatalogHub parity item.

## Deploy

1. Back up the database and uploads. Use the existing Python 3.11/FastAPI/PostgreSQL deployment and install `backend/requirements.txt`.
2. Run `python -m alembic upgrade head` from `backend/`. This adds migrations **0033–0035**. Existing Instagram orders and products are preserved; storefront orders use separate channel-independent tables.
3. Configure `PUBLIC_BASE_URL` with the HTTPS application origin. Keep `SECRET_KEY` stable and secret. Default/empty admin passwords can no longer log in; configure a nondefault admin password and allowed identifiers if admin login is needed.
4. Generate a Fernet key once and store it as `PAYMENT_ENCRYPTION_KEY` in the deployment's secret manager. For example, `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Do not commit it. Back it up securely: changing it without migrating ciphertext makes stored payment credentials unreadable.
5. Restart the web app, Celery workers and Celery beat. The new `app.workers.commerce.expire_reservations` task runs every minute. Expired online reservations are also reclaimed during catalogue/order access and checkout.
6. Log into `/dashboard/commerce`, save the store profile and policies, enable COD as appropriate, and publish. The customer address is `/shop/<store-slug>`.

Rollback to 0032 drops the new commerce, OAuth-state, payment-review and gateway tables. After accepting orders, restore a database backup or use a forward fix rather than treating schema downgrade as a data-preserving rollback.

## Razorpay

In the Payments tab of `/dashboard/commerce`, configure the seller's **test** key ID, key secret and a separate webhook secret (at least 16 characters). The server encrypts secrets and never returns them to the browser. Enabling payments validates the account with a read-only Razorpay API request.

Configure the exact webhook URL shown in that screen in the matching Razorpay account/mode. Subscribe to `payment.captured` and/or `order.paid`, and configure automatic capture. Test and live keys must match their selected mode. Online payment stays unavailable until enabled; COD can work independently.

The integration creates the Razorpay order server-side and passes only public checkout fields to Standard Checkout. The server verifies the checkout signature and fetches the payment; only an exact captured amount/currency/order match marks the order paid. Raw-body webhook signatures are checked separately, and duplicate delivery does not duplicate settlement. These follow Razorpay's [integration steps](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/) and [webhook validation](https://razorpay.com/docs/webhooks/validate-test/).

Online stock reservations last 20 minutes. A capture received after release/cancellation becomes `review_required`; it never silently reclaims stock or releases fulfilment. Sellers can use **Check payment status** to reconcile a missing callback. Captured cancelled orders require a real refund through Razorpay and operational review; this increment does not execute or automatically reconcile refunds.

Gateway credential snapshots are encrypted on each provider-backed order so delayed payment confirmations still verify after account credentials change. Do not remove the master encryption key or the old order snapshots. Pending online orders must be resolved before changing configured credentials.

Before production payment enablement, complete a sandbox transaction and webhook delivery test using the real seller account. Automated tests stub provider responses and are not proof of live account approval or settlement.

## Seller and customer workflow

- Storefront settings include the name, URL, contact details, delivery/return policies, flat shipping fee, COD availability and publication state. Store URLs cannot change after receiving orders.
- Products use the existing catalogue. Public responses omit floor prices, credentials, bot controls and internal tags. Unpublished/inactive sellers and inactive products are hidden. Variant labels are validated but inventory remains aggregate per product.
- Cart storage contains identifiers, selected variant and quantity. The server calculates prices and fees, takes database locks before reducing stock, and saves immutable item snapshots. Repeated checkout requests with the same key return the same order; a different payload with that key is rejected.
- Browser-tab session storage retains only a checkout retry key and a SHA-256 payload fingerprint. After a lost response and reload, re-enter the same checkout details to recover the existing result; changed details create a new attempt. Customer contact/address data is not persisted in browser storage.
- A customer's private order link holds its capability token in the URL fragment; API requests send it in an authorization header. Treat the link as private: it grants access to that order's contact/address details.
- The Orders tab supports confirm → pack → ship → deliver, manual tracking details and eligible cancellation. COD collection is an explicit action after delivery. Online orders require verified payment before fulfilment.
- Customers shows order history and collected/paid totals. Phone-based grouping is unverified contact grouping, not authenticated customer identity; new public orders cannot overwrite an existing customer's profile.
- Instagram payment screenshots now enter **Payment reviews**. A seller must check their bank records and enter the actual credited amount and transaction reference. Duplicate reference/review requests cannot credit twice. Approval resumes the address workflow on the customer's next inbound message; an immediate notification is not yet implemented.
- Payment-proof uploads require seller ownership; training screenshots require admin access. Existing static-upload fallbacks cannot bypass those checks.
- Instagram linking requires an active seller session. OAuth state lasts 10 minutes, is tied to that browser/login session and can be consumed once. Previously generated OAuth links must be restarted.

## Verification

- Full local suite: **359 passed, 5 skipped**. The five skips need recorded AI replay fixtures; live integrations were not exercised.
- Includes real PostgreSQL HTTP tests for seller isolation, immutable totals, invalid carts, concurrent retries/overselling, cancellation/expiry, payment signatures/replays, late captures and credential rotation, OAuth replay/session binding, manual payment review and private media.
- Migrations passed on an empty database and through `0032 → 0035 → 0032 → 0035` with a legacy product sentinel preserved.
- Browser QA: catalogue search, sold-out state, required variant, cart reload, COD placement, private status reload, every seller fulfilment step, COD collection and customer totals. Desktop and 360px mobile showed no page overflow. Razorpay's external checkout was not run with real credentials.
- GitHub Actions now runs migration, backend and JavaScript syntax checks against disposable PostgreSQL. Remote CI results are separate from the local result above.

For a complete local test run, create a dedicated disposable database named `commerce_test`, set `TEST_DATABASE_URL` to it and set `DATABASE_URL` to the same isolated PostgreSQL instance. From `backend/`, run `python -m pytest tests -q -ra`. The fixtures drop/recreate schemas: never use a shared database or production instance. The commerce tests intentionally skip unless the test database name ends in `commerce_test`.

## Remaining parity work

- SKU-level variant prices/stock, catalogue import/export and stronger order-abuse controls.
- Automated shipping/serviceability, returns/refunds and payment reconciliation beyond captured payments.
- Unified Instagram + storefront order/customer history and immediate transactional notifications.
- Instagram comment rules/comment-to-DM, WhatsApp per-seller onboarding/inbound/templates, shared inbox and cart recovery.
- Operational dashboards, retention/backup policy, rate limits and a deployment-wide security review before a broad public launch.

The Dharaa photos/content used for local browser QA are local fixtures only; they are not seeded into production or committed as real seller inventory.

## WhatsApp and comment automation

See [Social automation setup](SOCIAL_AUTOMATION_SETUP.md) for migrations 0036–0038, channel credentials, order-update opt-in, Meta prerequisites and live-test limitations.
