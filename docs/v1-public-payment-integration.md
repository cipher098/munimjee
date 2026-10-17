# Public online payment composition

The reviewed payment source `04de4b3` is composed with the actual public
storefront and private order-status shell. `V1_PUBLIC_PAYMENTS_ENABLED` stays
false by default. The versioned API/SSR projector advertises Razorpay only when
that flag and an active Business/Seller have locally usable enabled encrypted
credentials. Legacy Product payment options and settlement are preserved.
Configuring credentials locally does not verify a real provider connection.

Canonical order decoding retains the server's payment method across checkout,
status reads and session recovery. An online buyer loads the SDK before sending
a new order command; unavailable SDK/recovery storage prevents that new POST.
After the server acknowledges the order, the shared handoff opens the exact
provider order. Only the existing server signature/captured-amount verifier can
produce paid status. COD remains unchanged. Successful order acknowledgement
clears the bag and removes customer/address details from the stored intent.

The private status page uses the same session-held order bearer in Authorization,
never in URL query strings. Pending online orders can explicitly continue payment
or check status. Lost order acknowledgement keeps the original checkout key/body.
Lost verification keeps its exact bounded callback evidence for retry; a server
commit followed by response loss is recovered by reading the same order. An
interrupted SDK window or uncertain provider creation cannot silently open a new
order/payment attempt. Seller reconciliation uses an exact provider order ID and
validated provider receipt/amount/currency; browser success is never sufficient.
The checkout-session JWT stays in memory and never enters SDK options/storage.

Razorpay's [Standard Checkout integration documentation](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/)
and its maintained [Magento CSP allowlist](https://github.com/razorpay/razorpay-magento/blob/master-2.x/etc/csp_whitelist.xml)
were checked when composing the fixed SDK/script/frame/telemetry origins. The
public pages allow those exact origins without script wildcards or unsafe-inline.
The package explicitly includes the handoff module. A real SDK/provider canary,
provider account/domain configuration and payment-mode approval remain external
release gates; no real gateway request/payment was made during these checks.

Evidence lives under `artifacts/v1/public-payment/` and the integration browser
log: **29 actual Chromium checks passed**, with **61 Node checks** and **19
actual migrated projection/publication/bootstrap checks** passing separately. It uses actual app.main bootstrap, full PostgreSQL16 migrations, native
signup/configuration and a separate guest browser. Only the SDK/provider are
synthetic. Cases cover pre-order SDK failure with zero orders, server-verified
paid state, capability-only private status, committed/lost verification,
callback retry without reopening, interrupted-window lockout and unknown
provider creation without another POST. A held older pending-status response cannot replace a newer server-verified
paid result in either the UI or persisted confirmation. Screenshots cover
desktop/mobile and pending recovery states. The runtime image and full wave3 regression gate are
separate checks; earlier wave2 image evidence does not certify these new files.

Independent existing-worker source and render review accepted this bounded local
shell after reproducing and rerunning the delayed-status race. Five desktop/mobile
captures were inspected; the fixed UI and stored confirmation both remain paid.
An additional fresh agent could not start because of the existing thread limit;
this is an integrator plus independent existing-worker review. No real SDK/CSP
or payment outcome is inferred from the synthetic checkout proof. The same
composition passed **25 actual COD browser checks** and **22 incumbent
HTTP-mock/theme browser checks**.
