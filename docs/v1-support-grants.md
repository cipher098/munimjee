# Explicit read-only assisted access

Base3082f1a; schema0051 follows actual0050. Normal assignments and business
membership checks are unchanged. Default-off feature and empty explicit native
operator UUID allowlist deny access until provisioned outside the browser.

A current native owner resolves an exact provisioned operator email, selects an
explicit5–60minute expiry and consents to scope readiness.summary. Owner alone
can revoke. Consent fields are immutable; only one irreversible revocation update
is accepted. Renewal is a new consent, never extension/reactivation. Both users'
auth versions and current consenting-owner role/activity are checked for access.

Operator board lists only currently consented business names/scope/expiry. Detail
is an explicit audited POST/open returning safe counts/local statuses, never
member-workspace links, credentials, customer/order/inbox/media/provider facts or
write capability. Normal endpoints still require actual membership. There is no
impersonation, new token role or automatic global seller access.

Native session/CSRF and owner/grant authority run after lock waits and at final
transaction boundary after audit/receipt staging. No writer commits internally.
Business NO KEY locks serialize concurrent create/revoke/open and remain compatible
with FK checks. Expiry uses PostgreSQL wall clock, including long transactions.
Immutable commands bind actor/tenant/operation/exact body/key. Open receipt replay
requires currently valid consent; an expired/revoked grant returns no old snapshot.

The private native UI inherits commerce.css. Its exact-action journal is bound to
native user/session and owner business or operator board. No automatic replay;
unknown/malformed acknowledgement stays pending. Confirmed session replacement,
logout and401 physically clear private facts and journals. Consent is separate
from responsibility assignment; configured/local readiness never becomes provider
approval. New UI/API/browser evidence will be recorded when verified.

Broader discovery, incident access and support writes remain denied. Before that
scope can expand, the owner must define trusted operator provisioning, capabilities,
consent/escalation/renewal and emergency access policy. No real operator was
provisioned and no production permission was granted by local tests.
