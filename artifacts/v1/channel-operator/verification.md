# Local verification, 18 October 2026

Worktree: `munimjee-v1-channel-operator`; branch: `codex/v1-channel-operator`.

Dependencies consumed: auth migration 87cc13f, auth helpers 6314f29, native auth HTTP/UI 6b883f3, checkout domain ed86ff9 and final 0044 follow-up 7736c44. Actual P01 PostgreSQL 16 migration rebuilds reach 0045; no create_all or native auth bypass.

- Broad backend run: 850 passed, 8 skipped; one shared integration-owned startup assertion still expects migration0042 instead of0045. Reported to integrator; this feature does not edit shared main/model registration or startup assertions. The broad run preceded the final resume cutoff and account-binding regressions; targeted checks below cover those additions.
- Final database/API suite: 30 passed. Real native sessions, CSRF/Origin, current membership/revocation, tenant pagination, audited optimistic/idempotent/concurrent review, replay eligibility, synthetic provider connection/OAuth, encrypted WhatsApp credentials, preserved inbox identity after disconnect, authority handoff, unknown text/media/QR sends, signed-time worker gating, once-only eligible retry, and no autonomous reply after close without retry.
- Related ingress/takeover/nudge/credential + pure contracts: 85 passed, 3 explicitly skipped Redis-dependent checks. No real Redis/network provider fallback.
- Real Chromium: 16 checks passed using real signup, invitation, session, API and persisted migrated PostgreSQL rows. Desktop and390px mobile captures are in this folder. Covers pagination, explicit confirmation/disabled action state, closure with no-delivery claim, connection check/enable, encrypted WhatsApp form save and local disconnect, eligible durable retry, expired-time block, empty list, viewer restrictions and session-expired error. Browser queue dispatch is suppressed; provider GETs use a synthetic transport. Customer sends remain untested externally.
- JS syntax, Python compilation and diff whitespace checks passed.
- Impeccable detector ran once for the new HTML/CSS/JS. Its10px table-heading findings were fixed by an11px local override. The table-wrap inset warning is a false positive: the table's cells provide14px horizontal/17px vertical content padding. Rendered desktop/mobile views were inspected directly; modal action area scrolls within the viewport and Escape closes the dialog.

No live provider consent, permission mutation, message send, production data access or deployment occurred. Provider approval and end-to-end messaging remain pending. Independent API/UX and catalogue authority review are coordinated by identity_onboarding; this evidence is not a self-certified launch approval.
