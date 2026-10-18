# Parcel review verification

Application source: `a9d190097ff420c589679756fbdcc797bb2ac958`, based on
`a2ea26d7420e87697ef69b8c427a3f5a5ec61bf7`.
Feature commits: `915b2b7`, pre-commit authority correction `7406bf3`, strict
acknowledgement/recovery regression `a9d1900`. Evidence-only followups do not
change runtime source. The final backend files are byte-identical between
7406bf3 and a9d1900; the latter changes only the native acknowledgement guard and
its browser case.

## Actual database and two-service checks

`backend.txt` / `backend.xml`: **42 passed**, no skips, 86.92 seconds.
The existing class-based Pydantic configuration emits one deprecation warning.

From the repository root, using the shared Python 3.11 venv and only the approved
`TEST_DATABASE_URL`, `TEST_LANE=parcel_w3`, `TEST_DB_RESET=1`:

```
PYTHONPATH=backend python -m pytest \
  backend/tests/test_parcel_reviews.py backend/tests/test_parcel_tracking.py \
  -q --junitxml=artifacts/v1/parcel-review/backend.xml
```

P01 verifies the exact disposable lane before reset, holds its reset lease and
builds the actual Alembic chain through 0048. Production HTTP/Redis/provider
connections stay blocked. The explicitly approved Node bridge reaches only the
hardcoded 127.0.0.1:8155 integration fixture, exercising the real separate
Worker.fetch/HMAC/nonce/SQLite implementation. No other DB or original Parcel
Desk service is used.

The 22 new tests cover: explicit contradictory-status resume with append-only
history; current order truth unchanged; immutable audit, exact body/key receipt
matching and replay before candidate expiry; close then explicit replacement;
ordinary relink bypass denied; in-flight enrollment after close/replacement;
two competing replacements; stale lease fingerprint; native SID/role/order
waits; connector changes; SID/role/config/status/order changes during read;
manual unknown/unowned/not-found and same-parcel denial; no notification from
review/replacement baseline; old queued updates withheld before and after
resume through the actual sender (zero synthetic provider sends); future new
milestone queue dedup; CSRF and foreign tenant scope; and close/resume/replacement
revocation after staging the real audit, with rollback before commit. Twenty
incumbent parcel checks remain included.

## Mounted browser checks

**20 passed** in `browser.txt` on the final application source. The incumbent
flow also passes **18 checks**, recorded in `incumbent-browser.txt`, using
`python -m tests.run_parcel_browser` on the same lane after the review harness
releases its lease.

Command (same exclusive P01 lane, after the backend suite releases its lease):

```
PYTHONPATH=backend python -m tests.run_parcel_review_browser
```

The harness imports actual `app.main`; no manual product router/static mounting.
Synthetic native signup → reviewed SKU/activation/policy → COD order → open-order
parcel page → actual scoped connector/SQLite enrollment precedes review.
External browser requests are denied. Native 8156 and connector 8155 are child
fixtures and are stopped in `finally`; existing previews/services stay untouched.

The browser matrix covers real ZXing with synthetic camera frames, explicit
courier/recipient check, Delivered→In transit contradiction, required review
reason/two acknowledgements, dropped accepted native response→reload→same
body/key, wrong-command accepted response→reload→same body/key, explicit new
label replacement with delayed-preview/form/focus race, close and retained
history, unchanged fulfillment/payment/tracking-number fields, mobile/tablet
no overflow, and held old session response after same-user login replacement
clearing all private review/order/label/history with zero later private GET.

Captures:
- `desktop-confirm-label.png`: incumbent explicit initial association.
- `desktop-reviewed-resume.png`: 1365px review context and separate checks.
- `mobile-confirm-replacement.png`: 390px exact old/new label and confirmation.
- `tablet-preserved-history.png`: 768px closed successor plus retained old history.
- `mobile-session-ended.png`: 390px privacy fence with no private order facts.

## Independent review and design scope

Integrator identity_onboarding independently inspected desktop/mobile renders and
source. One substantive finding—authority needed rechecking after the final
audit flush and before commit—was fixed in 7406bf3 and covered by the three
actual rollback regressions. Integrator independently rechecked 7406bf3 +
a9d1900 and accepted the bounded domain and desktop/mobile renders, conditioned
on the final incumbent regression; that 18-check run now passes. Central
composition against the later 0050 migration chain remains the integrator’s gate;
this branch reports its actual 0048-chain scope only.
A fresh additional Sol/high reviewer spawn failed once with `agent thread limit
reached`; no repeated retry or fabricated independent-agent review is claimed.

This is an ordinary Operate extension of the incumbent native commerce world.
Impeccable documenter pass used the degraded in-thread workflow because fresh
agent capacity was unavailable. **No changes** to system files; checked
commerce.css, v1_app.css, parcel_tracking.css and final native captures.

Palette: existing ink #27302d, green #2e5141 and paper #f6f7f3.
Type: incumbent system UI body 14px/1.6, 34px heading and 21px section headings.
Layout: existing constrained container and panel; wrapping controls on mobile.
Forms: existing bordered inputs, 44px actions, native labelled checkboxes.
States: explicit confirmation, saved uncertain intent, policy-withheld updates
and native session fence; order history remains separate from reviewed facts.

No new system, fonts or decorative assets were introduced. Pre-existing missing
DESIGN.md was not repaired without authorization. `design-detect.txt` records
one detector invocation: regex-only CSS/JS scan, with parsed-element checks not
run; it is not a complete accessibility certification. Keyboard-labelled controls,
responsive screenshots and actual browser overflow checks provide bounded UI
evidence, not a physical-device certification.

## Remaining gates

This is local operator resolution and replacement, not remote deployment.
Unknown/unowned/multiple/not-found tracker ownership still requires separate
manual tracker review; no silent claim, transfer or ensure occurs on resume.
Old remote requests/messages cannot be recalled; review does not mark them
cancelled or delivered. Overview retains its existing 50-link bound; history
APIs paginate and the page shows the latest 25 entries per displayed link.
Private connector provisioning/deployment/D1/TLS, physical phone camera testing,
carrier refresh reliability, provider template acceptance, real customer sends,
and production deploy/restore remain pending. No payment/fulfillment/stock
mutation, new sender, production provider call, original Parcel Desk edit,
production deployment, push to main or PR was performed by this feature.


Bounded review record:
- Persistence: pass; lost/incorrect acknowledgement recovery reuses the saved command.
- Fidelity: incumbent native green/type/container/panels and responsive controls retained.
- Ceiling: restrained Operate extension; no visual redesign or new system.
- Material fixes: final pre-commit authority and strict acknowledgement correlation resolved.
- Keep: exact order/recipient/label context, two acknowledgements, retained history,
  cannot-recall warning, and separation from order/payment/customer-send authority.

Final cleanup: both browser harnesses stop their own 8155/8156 fixture children.
The temporary node_modules symlink was removed; no shared dependencies were changed.
Regenerated incumbent screenshots were restored to their pre-run tracked contents;
new review captures and raw incumbent output remain in this feature packet.
