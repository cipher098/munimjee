# Independent0057 foundation security review

Reviewed source: exact immutable Git snapshot `944395c`, not a mutable service draft.
This branch owns review tests/docs only. No runtime/migration or shared hook edits,
DB/browser run, Meta request, message or provider capability validation occurred.

## Additional confirmed finding

`whatsapp_test_authority.intercept_reserved`, source lines91–111, accepts any
nonempty provider MID up to255 characters and stores it unchanged in both canonical
`provider_message_id` and `idempotency_key`. Its broad reserved-packet scan correctly
notices a challenge anywhere in signed metadata, but body redaction alone does not
remove the challenge when it is in that retained MID. This violates the helper's
no-raw-challenge retention contract even when tests are default-off.

The actual helper ran against a fake SQLAlchemy session and actual message models:
`test_reserved_secret_in_provider_mid_never_reaches_any_retained_message_scalar`
**fails at944395c** because reserved metadata was retained. The assertion/log only
shows a boolean failure; no challenge/packet is printed. This is synthetic signed-
packet metadata behavior, not evidence that a real Meta MID has this shape or an
actual database was written. Raw negative: `foundation-mid-negative.txt`.

Catalogue acknowledged the finding and reports an uncommitted fix that rejects
reserved/nonprintable MID before any contact/message insert. That fix is **not yet
independently executed**; recheck the next frozen SHA before calling this resolved.

## Bounded source verdict and coverage

No other substantive foundation blocker was identified in the fixed Graph
origin/path/method/query/body allowlist, pinned public DNS/TLS route, denial of
redirects/proxies/untrusted next URLs, bounded JSON/duplicate-field parsing,
required exact-app/granular-WABA grants, explicit complete phone-choice pages or
secret-free exception/repr surfaces. These are source properties and synthetic
compatibility assumptions, not actual Meta wire/permission proof.

An additional no-network adversarial regression confirms that cancelling four
Graph waiters does not free admission while their underlying jobs remain in flight:
the fifth request is denied, with exactly four bounded fake jobs. It **passes** at
944395c (`foundation-cancellation.txt`). The temporary executor is released in a
finally block. No DNS/socket/provider is used.

Already acknowledged findings were not duplicated: coherent final exact-test
session/role/tenant/account/provenance authority; unbound BEFORE DELETE returning
OLD; and durable pre-provider phone claim/partial uniqueness across setting_up and
setup_unknown. No final runtime/DDL authorization verdict is made while those
fixes and the native signup/service/queue hooks are not a frozen tested whole.

Pending follow-up: portable test recheck on the coherent new SHA, then actual
migrated concurrency/expiry/idempotency/unknown-effect tests only after explicit
serial lane allocation. Preserve canonical signer/outbox behavior and no blind
retry. Provider consent, real recipient delivery and external configuration remain
separate closed acceptance gates.
