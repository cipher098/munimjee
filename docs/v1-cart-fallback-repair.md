# Missing-photo bag repair

Status: CSS source candidate; browser/migrated proof pending the integrator's serial slot.

Approved base `eeb94a119736cae816af782f2af5e04cb877e616`. The only runtime change is
`frontend/storefront/src/styles.css` in `4eed8af`. The original independent QA commit
`faec01614c27578afd38bef750b9dc2205ee7c98` and trusted output adaptation
`51f24801a5beb7f39ee57f8739301c633b056272` were cherry-picked alone as `f0f8bab` and
`e8c663c`; their production ancestors were not imported. The six painted-text
intersection assertions and all provider/network denials remain unchanged.

The global `.empty-state` selector spans a grid row. Missing-image `art()` uses it
inside a three-column bag line, so details and price move to later rows and the
name can paint over the amount. The fix scopes that fallback to the image cell,
matching the existing image dimensions (85×114 desktop,65×95 mobile), with compact
padding. The details column can shrink and the title wraps inside it. No renderer,
JavaScript/component, price, payment, activity, publication or API behavior changes.
The pre-repair CSS is byte-identical to the independently reproduced8ae97c2 source
(SHA256 `3b3d44107e53dc66a26154c96060852282db80d565ba4b0b32ce995217829e10`).

The original QA uses actual exported SSR and actual live modules with **synthetic,
intercepted HTTP**; it is not an actual mounted application or database proof. The
optional activity-context requests remain denied as unhandled and make that runner
exit1 independently of the75 UI outcomes. A UI pass must not be called a clean
whole-run exit or activity-contract acceptance.

Prepared mounted proof uses production `app.main`, native owner/session/CSRF,
actual catalogue SKU review/activation, theme save/publication, public SSR/assets,
and the same painted-text predicate at320/390 across editorial/catalogue/video.
It uses only the explicitly allocated P01 lane and8156 after serial release.
No manual router, synthetic product DTO or provider success is substituted there.
External requests and financial POSTs are denied. Ephemeral self-signed loopback
TLS is a test envelope, not public/providerTLS or physical-device acceptance.
