# Public online checkout handoff — approved contract

Baseline `aa6ac940ef877a8a37baac39afec44268b49f84e`. This slice reuses `commerce_orders`, seller-owned encrypted `RazorpayAccount`, the durable `SKUPaymentAttempt` no-blind-retry boundary, and existing signed/captured payment authority. No migration is currently required. Live/test provider canaries remain external gates; an isolated provider/SDK stub is not a real payment test.

## Boundaries

Payment lane owns new `app/services/checkout_sessions.py`, `app/api/v1/checkout_sessions.py`, `app/schemas/checkout_sessions.py`, `frontend/storefront/src/payment-handoff.js`, owned tests and these contracts. Shared frontend composition, canonical DTO decoder/bootstrap, storefront provider and application registration remain with the integrator. Narrow existing service changes for online acceptance, credential readiness and payment races will be coordinated with that owner. No theme shell, import or Parcel Desk changes belong here.

The feature switch is `V1_PUBLIC_PAYMENTS_ENABLED`, default false. It gates new online order acceptance and advertisement together with implemented client handoff and a locally usable enabled seller gateway. This flag does not change legacy Product Razorpay checkout or its payment-options contract. Valid existing payment capabilities/webhooks can finish an already-created order after new-order acceptance is disabled. Disabling new checkout must not discard settled funds or prevent verification. Existing cancellation/expiry produces refund review for late captures.

## Customer API

No customer endpoint accepts seller/native cookies as order authority. Existing signed order bearer capabilities remain required for status and session creation; supplied cross-origin request origins must match the configured canonical public origin, never a request Host-derived origin. Explicit nonbrowser bearer requests may omit Origin. No payment/order capability is placed in a query string or provider redirect URL.

- `POST /api/v1/storefronts/{slug}/orders/{order_id}/checkout-session`: existing signed order Bearer. Validate tenant/order, exact immutable order amounts/currency, SKU inventory engine, pending state/reservation, then create/recover its single durable gateway-order attempt. Return `checkout-session.v1` only after a verified gateway order exists. Uncertain/requesting attempts never cause another provider POST. Ready results expose only the public key, provider order identity, server total/currency, merchant display/prefill, purpose-separated session capability, expiry and fixed same-origin status/verify paths.
- `GET` at the same path: existing signed order Bearer. Return side-effect-free `checkout-state.v1`; no gateway mutation or automatic order creation. This status distinguishes no attempt, requesting, unknown and ready, plus authoritative order payment/fulfillment state and whether the same order can resume.
- `POST .../checkout-session/verify`: session Bearer plus the existing strict Razorpay success triple. Validate signed capability scope/expiry and its exact seller/order/provider ID/amount/currency binding, then reuse server signature verification and captured-payment authority. SDK success alone never marks an order paid. Return `checkout-state.v1`.

The checkout-session capability is signed, purpose-separated from native/order tokens (`role=public_checkout_session`, `purpose=v1_public_checkout`, a dedicated audience), and lasts at most 15 minutes and never beyond the inventory reservation. Existing persisted order/attempt state is its revocation/eligibility authority; no extra persistence table is needed. The order-status bearer continues to support read-only status after payment session expiry and store unpublishing. A new session for a known ready gateway order reuses that provider order, never a second provider POST.

## Browser contract

`createPaymentHandoff({slug,origin,storage,fetchImpl,sdkLoader})` will expose:

- `prepare()`: load/validate the fixed official Checkout SDK, without creating an order or contacting the provider order API. The shared checkout shell calls this before posting a new online checkout, so a blocked SDK does not create an order that the browser cannot pay.
- `open(order, onState)`: explicit customer action on the existing server-confirmed order/capability. Obtain/recover the checkout session, open the SDK with only allowlisted server fields, verify a successful callback server-side, then check authoritative status. Never create a new commerce order or clear its durable checkout attempt on a modal dismissal, failed payment, timeout, unknown creation, invalid callback or expired session.
- `check(order)`: read-only server state/status recovery. It does not open a modal or create a payment order automatically.

The canonical confirmation/bootstrap must retain the server payment method so the existing order/status UI can offer online-payment resume. COD remains unchanged. The session token stays ephemeral in memory and is never stored, put in a URL, or passed in SDK notes/options. Public order creation already has its durable exact-key `CheckoutAttempt`; the payment module never replaces that intent. Only bounded callback evidence may be retained for explicit verification retry; the existing order bearer remains resume/status authority. Callback/verification uncertainty must retain enough evidence to check the same payment rather than silently starting a new payment.

## DTOs to freeze

`checkout-session.v1`: `contract_version`, `order_id`, `provider`, `provider_order_id`, `key_id`, `mode`, `amount_minor`, `currency`, `session_token`, `expires_at`, `merchant_name`, `prefill`, `verify_url`, `status_url`, `order_status_url`.

`checkout-state.v1`: `contract_version`, `order_id`, `amount_minor`, `currency`, `payment_status`, `fulfillment_status`, `attempt_state`, `expires_at`, `retry_allowed`.

Strict schemas and concrete examples are committed under `docs/contracts/checkout-session/`. Provider/transport errors expose no secrets. Unknown creation remains a seller reconciliation/handoff state until exact receipt/amount/currency reconciliation proves the existing gateway order.

## Primary protocol reference

[Razorpay Standard Checkout integration steps](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/) documents server order creation, public Checkout options, handler response fields, HMAC verification using the server order ID and captured payment states. This implementation keeps the existing stricter server capture/amount/currency check and does not copy demo success alerts or treat an authorization callback as settled funds.
