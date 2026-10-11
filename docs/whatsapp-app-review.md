# WhatsApp App Review preparation

The scope is WhatsApp messaging and template management. Business verification is approved per the operator. Meta accepted the webhook at https://app.vouchrs.in/webhooks/whatsapp. The dashboard still shows the WhatsApp permissions as Ready for testing, not Advanced Access approved.

## URLs and settings

- Reviewer login: https://app.vouchrs.in/dashboard-auth/login
- Seller inbox: https://app.vouchrs.in/dashboard/social#inbox
- Template creation: https://app.vouchrs.in/dashboard/social#templates
- Connection settings: https://app.vouchrs.in/dashboard/social#connections
- Canonical privacy policy: https://munimjee.in/privacy
- Data deletion instructions: https://app.vouchrs.in/data-deletion
- Public privacy contact: tech@munimjee.in
- App display name, icon and category: check the saved values in Meta App settings → Basic. Do not change an existing approved icon without need.
- Grant reviewers a seller-scoped account for the connected test seller, not the shared administrator account. Fill the actual credentials into Meta's private reviewer instructions before submission. Do not put credentials in this file, screenshots or Git.
- The current public app uses a tunnel to a Mac. Review access must remain available; deploy to an always-on host before submitting, or ensure uninterrupted availability for the whole review. Replace URLs if the host changes.

## Remaining prerequisites

1. Connect the Meta test/business number to the intended seller using its WABA ID, phone-number ID and valid token. The UI validates that the number belongs to that WABA and encrypts the token.
2. In Meta, subscribe the app to the messages webhook field AND the connected WABA (`POST /{WABA-ID}/subscribed_apps` with appropriate authorization). Verifying the callback alone does not subscribe an individual business account.
3. Turn on WhatsApp sending in Connections. Keep unrelated automation off for the recording.
4. Use a recipient you control. For a Meta test number, complete the allowed-recipient setup in Meta. Have that recipient send an inbound message to open the reply window.
5. Verify the inbound message is visible and a manually sent reply actually arrives. A queued or sent status alone is not evidence of delivery in the recipient's WhatsApp interface.
6. Update the canonical policy to explicitly cover WhatsApp and template processing; see the review pack's proposed addendum. Validate existing retention/encryption statements against actual operations before submission.
7. Record two distinct videos and check the current instructions in Meta's Show instructions panels. No synthetic inbox data or mocked responses should be presented as live proof.
8. Embedded Signup is not implemented by this change. Do not claim customer self-serve WhatsApp onboarding works yet. Complete and demonstrate it if Meta requires that onboarding flow for the use case submitted.

## Draft use-case text — whatsapp_business_messaging

Munimjee is a conversational commerce platform for sellers. With a seller's authorization, we use whatsapp_business_messaging to send replies from the seller's connected WhatsApp business number, receive incoming messages and delivery updates through webhooks, and send approved message templates for relevant updates where the customer has provided the required consent. Sellers manage conversations in our WhatsApp inbox. Free-form replies are restricted to the customer service window, and opt-outs block further sends. We request Advanced Access so these features can serve external seller businesses, including Dharaa.

## Draft use-case text — whatsapp_business_management

Munimjee uses whatsapp_business_management to validate access to a seller's WhatsApp Business Account and phone number, create text message templates in that account, and retrieve template content, language, category and review status. The seller can create a utility or marketing template, provide numbered variables and fictional sample values, submit it to Meta and refresh its status from our Templates tab. Only approved supported templates are offered for sending. We request Advanced Access to perform these operations for external sellers who authorize Munimjee. Self-serve Embedded Signup is planned and is not demonstrated by the current manual connection flow.

## Video 1 — messaging (separate file)

1. Show the connected business number in Munimjee; keep access tokens and credentials out of frame.
2. From your recipient's real WhatsApp interface, send: “Hi, can you confirm my demo order?” to the connected business number.
3. In Munimjee → Social → WhatsApp inbox, click Refresh, open that conversation and show the matching inbound message and open reply window.
4. Type: “Hello! We received your demo order enquiry. This is a test reply from Munimjee.” Click Send reply.
5. Wait for the worker to process it. Refresh the conversation to show the delivery status.
6. Switch to the recipient's WhatsApp interface and show that exact reply arriving from the same business number, including its time. Keep the send-to-receive sequence continuous.
7. Save as whatsapp-business-messaging.mp4. Do not claim a successful demo until actual receipt is visible.

## Video 2 — template creation (separate file)

1. Sign in to the same seller and open Social → Templates.
2. Enter a unique name such as munimjee_order_confirmation_20261011 (change the suffix if it already exists), category Utility and language English.
3. Body: “Hi {{1}}, your order {{2}} is confirmed. Your order total is {{3}}. Thank you for shopping with us.”
4. Samples, one per line: Ananya / DEMO-1042 / INR 999. Footer: “Reply STOP to opt out”.
5. Show the preview and click Submit to Meta; confirm the named template and connected business account.
6. Show the returned template and actual Meta status. PENDING means submitted for review, not approved. Sync from Meta to show the persisted template. Optionally show the same name in WhatsApp Manager.
7. Save as whatsapp-business-management.mp4. This operation creates a template; it does not send a customer message.

## Reviewer navigation draft

Log in using the seller test credentials supplied privately with this submission. Open Social. The Connections tab identifies the connected test business number. In WhatsApp inbox, open the test conversation shown in the messaging recording; after an inbound message opens the customer service window, type a reply and click Send reply. Use Refresh to update message status. In Templates, enter a unique template name, category, language and body, add samples for each numbered variable, and click Submit to Meta. The created template appears below with Meta's returned status. Sync from Meta refreshes review status. Contact tech@munimjee.in if access fails. The precise recipient/test-number instructions and seller credentials must be filled in before submitting.

## Evidence boundary

Automated tests use isolated PostgreSQL and stubbed Meta transport. They verify payloads, validation, tenant scoping, duplicate handling, uncertain responses and approval gating. They do not prove real messages were delivered or a template was created in Meta. Actual recordings are pending a connected account and real tests.

## Sources

- User's Meta App Review screen: separate messaging and template-creation videos, app icon, privacy URL and category.
- https://www.postman.com/meta/whatsapp-business-platform/request/uvx80vi/create-template-w-text-header-text-body-text-footer-and-2-quick-reply-buttons
- https://www.twilio.com/docs/whatsapp/isv/tech-provider-program/integration-guide#record-your-screen-for-app-review
- https://munimjee.in/privacy (inspected 11 October 2026; currently Instagram-focused).
