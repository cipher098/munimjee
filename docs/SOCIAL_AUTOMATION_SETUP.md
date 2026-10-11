# WhatsApp and Instagram comment automation

This increment adds `/dashboard/social` on top of the commerce foundations. It does not connect a real Meta account automatically. Provider requests are mocked in regression tests; no live outbound messages have been sent during development.

## Included

- WhatsApp: per-store encrypted connection, inbox, manual text replies, approved text templates, explicit category consent, STOP/UNSUBSCRIBE and START, exact keyword replies, first-contact welcome, product/store links, delivery history.
- Instagram: seller-owned rules for a post/reel or all media, any matching keyword/phrase, one private product reply and an optional public reply, no-send preview, delivery history. Rules start disabled. First matching rule wins; matching is Unicode case-insensitive with whole-word boundaries.
- Order updates: an unchecked checkout opt-in; utility templates for placed, confirmed, shipped and delivered. Each order and event queues at most once. Checkout and fulfillment transactions never call Meta.
- Durable outboxes and signed webhooks. Unknown outbound outcomes require review; the system does not blindly resend a possibly delivered message.

## Server setup

Apply `alembic upgrade head` (0036–0038), deploy API and Instagram Lambda/SQS consumer changes together, and restart Celery workers and Beat. Beat scans each outbox every 30 seconds. Redis remains necessary for Celery and Instagram echo recognition.

Configure through the deployment secret manager, never through chat or a committed file:

| Setting | Purpose |
| --- | --- |
| `CHANNEL_ENCRYPTION_KEY` | Fernet key for per-store WhatsApp tokens. Keep it stable and backed up; changing it without re-encryption requires reconnecting accounts. |
| `WHATSAPP_APP_SECRET` | App secret for verifying raw WhatsApp webhook signatures. |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Independent callback handshake token. |
| `WHATSAPP_GRAPH_VERSION` | Pinned Cloud API version, default `v23.0`; verify support for the deployed Meta app before activation. This is not a claim that v23 is latest. |
| `PUBLIC_BASE_URL` | Public HTTPS origin for storefront/product links and callbacks. |
| `META_WEBHOOK_SECRET` | Matching Instagram app secret in API and deployed Lambda. Missing secret rejects ingress. |
| `META_VERIFY_TOKEN` | Instagram callback handshake token. |

Legacy `WHATSAPP_API_*` variables still serve existing owner pings; they do not connect customer inboxes. Debug seller forwarding now defaults to an empty list and must remain disabled in production.

## Connect WhatsApp

This version uses manual Cloud API setup, not Embedded Signup. In Meta, configure the WhatsApp Business Account (WABA), register the Cloud API phone number, and assign access to a suitable system-user token. Messaging and management operations use `whatsapp_business_messaging` and `whatsapp_business_management`; onboarding businesses you do not own may require additional Meta business verification, Advanced Access and review. Instagram approvals do not confer WhatsApp access.

In Social → Connections, supply WABA ID, phone-number ID and token. Saving verifies that the phone belongs to that WABA and stores the token encrypted; tokens are never returned. A saved connection starts with sending disabled. A blank token retains the existing token only for the same account/phone. A store cannot switch numbers while retaining its old inbox.

Configure Meta's callback to `https://YOUR_ORIGIN/webhooks/whatsapp`, subscribe to `messages`, and subscribe the app to the WABA. The dashboard's webhook readiness indicator checks server configuration only: it does not prove Meta subscription or successful live delivery. After those steps, deliberately enable sending, sync templates, configure automations and run an authorized test with your own test recipient.

Free-form replies are limited to 24 hours after the actual inbound timestamp. Outside that window, use an approved template with documented recipient consent. Marketing and utility consent are separate. STOP/UNSUBSCRIBE block queued and future sends; START permits replying again but does not grant marketing or utility consent. Checkout cannot override STOP. Include a clear human support contact or handoff instruction in automated copy and maintain a monitored inbox.

Only numbered text BODY templates, with an optional footer, are supported. Headers, buttons, media and authentication templates are not supported in this increment. Approval and category are rechecked immediately before sending.

## Order templates

Map approved **UTILITY** templates with exactly three numbered body parameters:

| Parameter | Value |
| --- | --- |
| `{{1}}` | Customer name from the order |
| `{{2}}` | The same `MJ-…` order reference shown at checkout and in the seller dashboard |
| `{{3}}` | Currency and total for placed/confirmed/delivered; tracking URL, tracking number or “Tracking will follow” for shipped |

The checkout checkbox appears only when sending is enabled and a compatible approved placed template is configured. Opt-in applies to that order; an unchecked later checkout does not inherit it. Placed means the order was saved, including an unpaid online order, so the template must not claim payment was collected. Confirmed/shipped/delivered describe fulfillment events, not payment settlement. Missing or invalid mappings skip notifications without blocking commerce.

## Instagram setup

Reconnect existing sellers so OAuth requests the three existing approved permissions: `instagram_business_basic`, `instagram_business_manage_comments`, `instagram_business_manage_messages`. OAuth now subscribes `messages,comments`; also enable the comments field in the Meta app configuration. No publishing scope is needed for these replies.

Publish the store and configure a public HTTPS base URL before saving a product rule. Live/nested/self comments are skipped. Creation time is verified from comment metadata when absent from the webhook; webhook delivery time never creates a fresh private-reply window. One private reply is attempted per comment within seven days. Any later DM conversation uses the existing messaging flow after the recipient responds. The dashboard reports permission status as unverified until a real-account check is performed; saving a rule does not prove app approval.

The public reply and private reply are separate durable actions: one failing cannot resend the other. Rules disabled or materially changed before dispatch cancel their queued actions. A conservative per-seller dispatch cap is applied; actual Meta limits still govern delivery.

## Operations and limits

- WhatsApp `accepted` means Meta returned a message ID, not that the recipient received it; signed callbacks advance sent/delivered/read status.
- If a worker loses a response or dies after claiming a send, the action becomes `unknown`/review-required. Check provider evidence before initiating another message. There is intentionally no automatic retry button for uncertain sends.
- Preserve both the application database and encryption key. Database rollback below 0036 drops messaging history/configuration; back it up first.
- Inbox lists show the newest 200 contacts/messages and comment activity shows 100 events. Pagination, attachments, campaigns, Embedded Signup and a dedicated human-assignment workflow are not included.
- Existing Instagram token storage and legacy owner notifications predate this increment. Comment automation uses that existing connected account.
- Credential-like strings were removed from old commented code. Rotate any real historical token through Meta; deleting current source does not remove Git history.
- Review published privacy/support details before production use. The included privacy page remains a starter policy.

## Validation

PostgreSQL-backed tests cover seller isolation, checkout consent, idempotent delivery, signed webhook rejection, template policy, opt-out handling, duplicate/reordered events, send uncertainty, worker recovery, comment matching and production Lambda/SQS routing. Migration upgrade/downgrade/upgrade was exercised on a disposable database with an existing commerce order retained. Browser scripts pass syntax checks. See the PR for the final full-suite and browser results.

A live Meta canary remains required before enabling production automations. Official private-reply documentation returned HTTP 429 during implementation; the SDK and indexed Meta collection supported the API shape, but mocked tests cannot establish current account permissions or provider acceptance.

## Primary references

- [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/) — opt-in, template/window rules and human escalation.
- [Meta WhatsApp Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api).
- [Meta Instagram API collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).
- [Meta SDK IGComment source](https://github.com/facebook/facebook-nodejs-business-sdk/blob/main/src/objects/ig-comment.js) — timestamp, parent and replies fields.
- [Instagram private replies documentation](https://developers.facebook.com/docs/instagram-platform/private-replies/) — recheck on the deployment account; unavailable to the research client during this increment.
