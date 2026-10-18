# Wave 4 local integration evidence

Application source: `dd36b0dab568684d6c8ee6c66d47e27a76b9fca4`, from
verified `a2ea26d`. Date: 18 October 2026. All implementation/review workers retain
GPT-6.1 Sol/high. This is bounded local acceptance, not full V1 or a release.

Actual database chain now ends in `0049_v1_storefront_settings` →
`0050_v1_assistance`. Every local reset uses P01's exact allocated loopback URL,
one held advisory lease and real Alembic migrations. Central owns only
`wave3_integration`; settings and parcel/recovery owners use their own lanes.
Provider sockets remain blocked. Original running projects and ParcelDesk are
unchanged. No deployment, live payment, carrier lookup or customer send occurred.

## Integrated checks

- Full actual PostgreSQL 16/Alembic gate: **1,417 passed, 8 skipped, 0 failed**
  in **541.55 seconds** at backend source `257b273`. The eight skips are five
  missing historical scenario cassettes and three Redis cases blocked by P01.
  The subsequent `dd36b0d` changes only importer recovery presentation and
  browser tests; its backend and migration diff from `257b273` is empty.
- Central assistance: **37 actual mounted Chromium checks**, including existing
  memberships, assignment/clear, lost response, unclassified 409 and wrong-key 200
  exact recovery, correct one/two-business profile selection, unknown-ID explicit
  selection, known revocation and older session-response fences. Its earlier
  focused gate passed **36** (17 migrated/API and 19 pure contracts).
- Native import/persisted themes/customer COD: **29 actual mounted Chromium
  checks** at `dd36b0d`, with actual review/allocation/receipt/theme/catalogue APIs,
  actual PG16, all three published SSR+JS presentations, desktop/mobile/tablet
  missing-media contrast and three real local COD orders/status journeys.
  Literal synthetic source insertion is a disclosed fixture, not provider proof.
- Independent central payment settings: **36 actual mounted Chromium checks** at
  `257b273`, using the owner's exclusive PG16 lane. Import of actual `app.main`
  verified exactly one payment page route from `app.api.v1.payment_settings`;
  the fixture's optional fallback was not used. Owner backend evidence is
  **61 focused PG + 1 pending-order rotation + 14 incumbent Razorpay checks**.
- Parcel owner: **42 actual PG16/two-service checks**, **20 mounted review
  Chromium + 18 incumbent parcel Chromium**. Worker.fetch/HMAC/SQLite is real
  and local; carrier/cache source and customer-send transports are synthetic.
- Native recovery owner: **3 actual HTTP + 30 mounted Chromium**. Baseline old-200
  and queued JSON/upload-after-fence failures were reproduced before the fixes.
  Theme 6 and importer 164 HTTP-mock checks are kept separate from native proof.
- Central **77 Node checks** passed without skips. The focused runtime/startup
  gate passed **19**. Full raw XML/logs, independent source/mount manifests and
  final browser records are under `artifacts/v1/integration/wave4/`.

Final mounted composition also passed **47 native import checks** and **20 parcel
review checks** on the central actual 0050 chain. The independent central recovery
rerun passed **30/30**, with a direct read of `0050_v1_assistance`, unchanged source
hashes and no provider sockets. Its legacy printed “0049” runner label is corrected
by `native-recovery-mounted-source.json`; no old schema was substituted. Central
parcel composition includes the real local Worker/HMAC/SQLite service; courier and
sender transports remain synthetic. Native mobile import capture is a painted
viewport of the reviewed private-draft result, not a full-page visual acceptance
claim. Counts overlap and are never summed.

The first central combined gate found invalid synthetic native signup domains:
**105 passed, 23 failed, 28 setup errors**. After fixing the two test-only email
domains, **57 passed, 17 failed**; the remaining fixture used a reserved source
URL rejected by the actual source validator. Correcting that test-only URL made
all **17/17** native import cases pass. Product validation was preserved. Both
failed runs and corrected results remain under `artifacts/v1/integration/wave4/`.

## Failure matrix

| Failure or transition | Required result | Evidence |
| --- | --- | --- |
| Unknown source stock/options, incomplete Cartesian allocation or invalid sum | No private product/approval/stock inference | Actual native import API/domain cases |
| Committed import draft response lost | Same body/key returns one immutable tenant receipt/product | Actual native browser and recovery owner matrix |
| Generic409/422 or malformed successful acknowledgement | Retain exact pending action; no silently fresh command | Actual recovery matrix; console actual wrong-key200/unclassified409 |
| Explicit typed stale version after serialized receipt absence | No writes; reset review only for that narrow rejection | Actual typed-error HTTP cases |
| Private design save or design publication | Does not activate product, publish store or enable checkout | Actual PG/native/browser boundaries |
| Published design differs from latest draft | SSR and browser use published allowlist only; query cannot substitute draft/theme | All-three actual API/SSR/browser checks |
| Lost credential save | Clear secret/body, retain only nonsecret marker; GET cannot confirm secret replacement | Mounted settings browser and conditional API checks |
| Competing same-revision credential replacements | One wins; late prior request cannot overwrite newer secret ciphertext | Actual PG contention/CAS |
| Old valid200 for secret-bearing save | Unknown marker remains unless opaque revision changes | Actual settings browser |
| Revocation after staged native writes | Roll back assignment/settings/design/import/review facts and receipts before acknowledgement | Actual PG transaction-final guards and post-audit parcel regressions |
| Resume/close/replace parcel after a contradictory/unknown outcome | Explicit selected-order review; preserved old association/history/audit; same-key recovery | Actual PG/two-service/mounted parcel review |
| Old worker lease returns after reviewed replacement | Cannot revive closed association or overwrite successor | Actual parcel concurrency cases |
| Review resumes tracking while old messages are queued | Review itself queues nothing; earlier outbox IDs/time baseline stay withheld | Existing sender helper + actual synthetic transport tests |
| Known nonselected membership revoke or newer role projection | Remove private row/member labels/actions; delayed older session cannot restore them | Actual console external revoke/browser + independent negative/fixed VM reproduction |
| Unknown business query with one or several memberships | Hide private content; explicit authorized choice, never first-business fallback | Actual console/profile browser |
| Incomplete packaged private pages/theme module or forbidden files | Builder fails closed; no test/env/upload/key/development files | Runtime allowlist tests and image smoke |

Independent peer source/render review found and rechecked pre-commit parcel
authority, credential acknowledgement, revoked console rows and stale session
authority. Final source/UI verdicts are bounded to the reviewed slices. The
additional fresh-reviewer spawn was capacity-blocked; no such review is claimed.
The console detector reported one inherited linked commerce.css 11px-text warning;
its main body is 14px. Missing-image video contrast was found in the actual render
and corrected using the existing panel/ink colors, without fabricated media.

Open gates: real Meta/WhatsApp permission and authorized delivery canaries,
Razorpay SDK/domain/CSP/capture canary, private ParcelDesk provisioning/D1/TLS,
physical phone camera/touch flows, owner-approved import sources, backup/restore/
rollback and CI/multi-architecture release rehearsal. Analytics, explicit expiring
support grants, global sales access, verified customer links and the remaining
complete onboarding matrix remain tracked V1 scope; none is simulated by normal
membership assignment. Flags remain default off.

## Packaged source

The final application image is `munimjee-v1-runtime:local-20261018-wave4-dd36b0d`, ID `sha256:f37e01ecaf9294b20f83b186945a5f79b90a6dbfb67ce7b024900becefe01fb0`, Docker-reported
**130,173,942 bytes**, arm64, UID/GID `10001:10001`. Its **286 allowlisted files** include
51 explicit static files and 13 storefront modules. All three offline modes
(default-off, enabled, missing-assets refusal), context/image/per-file hash checks,
zero DNS/network/database attempts and CID-only verified cleanup passed. Source is
`dd36b0d`; exact manifests are `artifacts/v1/runtime-package/wave4-final-*`.
The earlier `257b273` image/log is preserved as an intermediate checkpoint.
No container was deployed and no existing image/service was removed.

Docker build stdout keeps its content with terminal carriage returns removed.
