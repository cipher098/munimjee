# WhatsApp App Review preparation

The scope is WhatsApp messaging and template management. Business verification is approved per the operator. Meta accepted the webhook at https://app.vouchrs.in/webhooks/whatsapp. The last inspected Meta screen showed the WhatsApp permissions as Ready for testing. Advanced Access approval has not been verified.

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

## Verified setup — 11 October 2026

- The Munimjee demo seller has an enabled WhatsApp test-number connection and receives real inbound messages and signed delivery callbacks.
- The allowed test recipient confirmed receiving a reply. Later, reel-linked product replies and a separate price follow-up both reached delivered status through Meta callbacks.
- Instagram keyword automation was also exercised on the demo reel: a fresh matching comment produced successful private and public reply IDs. This is separate from WhatsApp review evidence.
- The unresolved-reel queue was exercised live: the operator linked reel DeWwqDbMSuq to Emerald Roman-Numeral Wall Clock, the resumed reply reached delivered status, and the recipient confirmed receipt. This was not recorded as a review video.

## Remaining prerequisites

1. Use the connected Munimjee test seller and a controlled recipient for recordings. For a Meta test number, the recipient must be allowed in Meta; an inbound message opens the free-form reply window.
2. Grant reviewers a dedicated seller-scoped login, and confirm app icon, category, policy and deletion URLs in Meta.
3. Update the canonical policy to explicitly cover WhatsApp and template processing; see the review pack's proposed addendum. Validate existing retention/encryption statements against actual operations before submission.
4. Record two distinct videos and check the current instructions in Meta's Show instructions panels. Show the recipient's WhatsApp interface receiving the exact sent message. Template syncing alone does not demonstrate template creation; record an actual creation and the returned status.
5. Ensure uninterrupted public availability throughout review. The current Mac tunnel is a development deployment.
6. Embedded Signup is not implemented. Do not claim customer self-serve WhatsApp onboarding works yet. Complete and demonstrate it if Meta requires that onboarding flow for the submitted use case.

## Submission preparation — 12 October 2026

- Meta draft: https://developers.facebook.com/apps/1235769858762998/app-review/submissions/?submission_id=1401103108896338&business_id=876283322108187
- New requests: whatsapp_business_messaging and whatsapp_business_management.
- Meta shows Verification and App settings as complete. Permission evidence, renewal declarations and Data handling remain incomplete; the draft is not submitted.
- Business descriptions and detailed permission explanations have been saved for both WhatsApp permissions, accurately describing the current manual connection flow. Meta marks both required API tests Completed. No video has been uploaded and the allowed-usage agreement boxes remain unchecked.
- The template form is prepared with fictional examples; wait for recording before submitting it to Meta. Creating a template through the actual dashboard, not an API-only script, demonstrates the user flow.
- The operator will record two separate videos. Show the real returned template status; do not imply PENDING is approval. For messaging, show the exact reply in both Munimjee and the recipient's WhatsApp interface.
- Public privacy policy fetched today still describes Instagram only. Add WhatsApp processing disclosures and verify the existing retention and hosting claims before final submission.
- Test seller login exists (munimjee-demo@example.test), but a reviewer login has not yet been tested in this preparation. Never share the administrator login or tokens with reviewers.
- Data handling was inspected without changing answers: only munimjee is currently listed as a processor; audit external processors before submission. Controller is prefilled as Archon Tech, India. The operator must confirm the prefilled national-security disclosure history and authority-request procedures; these cannot be inferred from code.
- Renewal includes eight existing permissions and requires allowed-use certifications. These and the two new-permission agreement boxes remain unchecked pending review; no agreement has been accepted automatically.

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
2. Enter a unique name such as munimjee_order_confirmation_20261012 (change the suffix if it already exists), category Utility and language English.
3. Body: “Hi {{1}}, your order {{2}} is confirmed. Your order total is {{3}}. Thank you for shopping with us.”
4. Samples, one per line: Ananya / DEMO-1042 / INR 999. Footer: “Reply STOP to opt out”.
5. Show the preview and click Submit to Meta; confirm the named template and connected business account.
6. Show the returned template and actual Meta status. PENDING means submitted for review, not approved. Sync from Meta to show the persisted template. Optionally show the same name in WhatsApp Manager.
7. Save as whatsapp-business-management.mp4. This operation creates a template; it does not send a customer message.

## Reviewer navigation draft

Log in using the seller test credentials supplied privately with this submission. Open Social. The Connections tab identifies the connected test business number. In WhatsApp inbox, open the test conversation shown in the messaging recording; after an inbound message opens the customer service window, type a reply and click Send reply. Use Refresh to update message status. In Templates, enter a unique template name, category, language and body, add samples for each numbered variable, and click Submit to Meta. The created template appears below with Meta's returned status. Sync from Meta refreshes review status. Contact tech@munimjee.in if access fails. The precise recipient/test-number instructions and seller credentials must be filled in before submitting.

## Evidence boundary

Automated tests use isolated PostgreSQL and stubbed Meta transport. They verify payloads, validation, tenant scoping, duplicate handling, uncertain responses and approval gating. They do not prove real messages were delivered or a template was created in Meta. The account is connected, and live messaging has been tested separately as described above. The two review recordings and a demonstrated live template creation are still pending; automated test results are not a substitute for those recordings.

## Sources

- User's Meta App Review screen: separate messaging and template-creation videos, app icon, privacy URL and category.
- https://www.postman.com/meta/whatsapp-business-platform/request/uvx80vi/create-template-w-text-header-text-body-text-footer-and-2-quick-reply-buttons
- https://www.twilio.com/docs/whatsapp/isv/tech-provider-program/integration-guide#record-your-screen-for-app-review
- https://munimjee.in/privacy (inspected 11 October 2026; currently Instagram-focused).
