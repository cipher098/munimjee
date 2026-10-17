# Channel operations and saved Instagram message review

This local V1 slice provides a native seller workspace at `/v1/businesses/{business_id}/channels`. It uses the persistent V1 session and current business membership. Inbox readers can inspect minimal saved messages; owners and managers can record reviews; only owners can connect, check or disconnect channel accounts. Admin impersonation and support grants are not accepted.

An error item records its status, plain reason, component progress, saved customer text and an account-local customer reference. Media links and credentials are not returned. Listing uses bounded, tenant/filter-bound signed cursor pagination. Customer and audit text render through `textContent`.

A review requires explicit confirmation, a reason, a current item version and an idempotency key. Row locks serialize concurrent decisions, with an actor-linked audit and the original outcome returned for repeated identical requests. Closing without retry does not send a message, alter the transcript or claim delivery. A reviewed retry remains durable when the broker is unavailable; recovery uses the existing worker and conversation writer.

## Retry eligibility

Both the API and worker check the connected account, active membership/capability, credentials and a recent local account-access check. A signed provider timestamp must establish a current conservative 24-hour automation window; old receipts are not backfilled with their receipt time. Missing or expired timestamps are retained for review without automated replay. Other unknown-effect items, takeover, disengagement and open manual actions hold the conversation. A close-without-retry decision also fences older autonomous resume and nudge triggers without changing the transcript; a later customer turn can resume normal processing. Reviewer revocation between queueing and processing withholds the retry. Ordinary durable processing also checks the signed timestamp before entering the conversation writer.

A prior reply can have reached Instagram before the local transaction failed. Operators must inspect the original Instagram conversation before choosing another attempt. A resolved item is never a historical delivery confirmation. Text, product-image and payment-QR send exceptions or missing message IDs now propagate to the existing durable unknown-effect quarantine rather than completing a receipt or retrying automatically. Existing standalone follow-up/manual-send paths are not a new durable outbound outbox in this slice.

## Channel lifecycle

Instagram start/callback is bound to the current owner, current native browser credential, a short-lived signed state and an HttpOnly browser nonce. An attempt is durably consumed before token exchange; exchange uncertainty requires a new authorization attempt, not a blind retry. Owner membership and disconnect generation are checked again after the network gap. Disconnect cancels in-flight attempts and pauses local sending. Saved inbox account binding survives disconnect; connecting a different Instagram account to the same inbox is withheld until an explicit migration exists.

WhatsApp setup uses the existing Cloud API adapter to verify that the number belongs to the supplied Business Account, then stores the token encrypted using `CHANNEL_ENCRYPTION_KEY`. A different number cannot inherit an existing inbox. Token values and provider error bodies never appear in status DTOs or audits. Instagram uses the incumbent Seller token storage contract; this change does not migrate that legacy field to encrypted storage.

Newly connected accounts stay paused. Connection checks read provider account access and send no customer messages. Local configuration, current access checks, provider approval and end-to-end delivery are separate statuses. This interface reports `readiness_scope=local_account_access`, `provider_approval=not_evaluated` and `end_to_end_tested=false`. It does not subscribe accounts, mutate provider permissions or claim P03 Meta consent/review completion. Local disconnect is separate from revoking the app in Meta.

## Catalogue authority

Once `is_product_activated` returns true, legacy product price/stock facts are frozen. Instagram focused turns, reply-to switches, reel/image resolution, dynamic price lines, order assembly, resume and nudges check authority. Shared Product reader locks serialize these reads/sends with activation while allowing concurrent chats. Missing or foreign product context fails closed before legacy facts can be read. The durable item becomes a human-review handoff; it does not invent a SKU answer. WhatsApp reel context gives a deterministic human handoff without legacy price/stock. Deactivating checkout policy does not restore legacy authority.

## Integration

Migration `0045_v1_channel_operator` follows `0044_v1_checkout`. The integrator must register `ChannelOperation`, `ChannelConnectionState`, `ChannelOAuthAttempt` from `app.models.channel_operator` in shared model imports, and mount `app.api.v1.channel_operator.router` in the main app. Native auth and catalogue helper dependencies must precede the feature commit. No second sending writer is added. The native onboarding checklist should link the per-business route only once the router is mounted.

## Isolated verification

Use a dedicated P01 lane, never runtime environment files. The lane validator requires literal loopback PostgreSQL, `TEST_LANE`, `TEST_DB_RESET=1`, an exact `munimjee_test_<lane>` name and a held reset lease. Tests rebuild the actual complete Alembic chain. Outbound sockets are blocked except that database; provider tests use `httpx.MockTransport`.

Run `PYTHONPATH=backend python -m pytest backend/tests/test_channel_operator.py backend/tests/test_channel_operator_db.py` with the guarded test variables. Database tests exercise real native sessions, CSRF/Origin, current roles and revocation, tenant pagination, audit/idempotency/concurrency, signed-time eligibility, activated-product handoff, unknown text/media/QR outcomes, encrypted WhatsApp setup and synthetic Instagram OAuth.

After installing the storefront's locked Playwright dependencies, run `PYTHONPATH=backend python -m tests.run_channel_operator_browser` with the same guarded variables. It owns loopback port 8145 and the database lease for its lifetime. Its test-only server mounts the feature router, seeds synthetic receipts only after real native signup and owner authorization, permits synthetic provider GETs and suppresses worker dispatch. Never expose that fixture server externally or mount its seed route in the application. The browser proves persisted review/queue state; provider delivery remains untested.
