# Independent mobile, accessibility and recovery QA ownership

18 October 2026. Frozen source: `abab30aaf1ab94052344b0ef21d05b3922f260dc`,
fetched from `codex/v1-integration`. Existing Instagram workers are complete and
are reused, retaining their explicit GPT-6.1 Sol/high settings. No duplicate QA
assignment is active in this agent tree. Production files are read-only.

| Reused worker | Current QA scope | Worktree/branch | Exclusive new writes |
| --- | --- | --- | --- |
| instagram_provider | Three public storefront themes: mobile, keyboard/accessibility, error states | munimjee-wave8-storefront-qa / codex/v1-storefront-mobile-qa | backend/tests/independent_storefront_experience_qa.*, docs/v1-independent-storefront-experience-qa.md, artifacts/v1/independent-storefront-experience/ |
| instagram_contract_qa | Seller onboarding: mobile, keyboard/accessibility, error and resumable/session states | munimjee-wave8-onboarding-qa / codex/v1-onboarding-experience-qa | backend/tests/independent_onboarding_experience_qa.*, docs/v1-independent-onboarding-experience-qa.md, artifacts/v1/independent-onboarding-experience/ |
| instagram_security | Bounded offline load/recovery and independent harness/effect review | munimjee-wave8-recovery-qa / codex/v1-offline-recovery-qa | backend/tests/test_v1_independent_offline_recovery*.py, backend/tests/independent_offline_recovery_qa.*, docs/v1-independent-offline-recovery-qa.md, artifacts/v1/independent-offline-recovery/ |
| root | Compose/review results, exact-source evidence and local fix handoff | munimjee / codex/v1-independent-experience-qa | This contract, docs/v1-independent-experience-qa-handoff.md, artifacts/v1/independent-experience-coordination/ |

Read the full current go-live-plan and relevant existing tests first. Reuse existing
fixture exporters/safety mechanisms rather than duplicating coverage. Each new test
must resolve an actual missing acceptance condition or adversarial failure. Test
actual application/rendered/module source with synthetic fixtures/HTTP wherever no
allocated DB exists. Record concrete failures; do not weaken assertions or modify
production merely to make this QA green. Mobile emulation is not physical-device
proof; keyboard/DOM checks are not screen-reader certification or a WCAG audit.
Finite fake-transport load is not production throughput/soak acceptance.

No changes to production app/frontend/static files, schemas, migrations, dependencies,
existing shared safety harness, analytics, Instagram integration, comments or local
onboarding/privacy fixes. No live provider/API/SDK calls, real credentials, customer
messages, charges, deploy, DNS/billing/hosted-CI changes, Docker probes/restarts,
new database allocation or existing user browser/service access. Browser API traffic
must be intercepted and unexpected origins denied. Synthetic browser-only fixtures
and isolated short-lived loopback static fixture servers are permitted; never attach
to ambient 127.0.0.1:4317. Actual DB checks use unchanged P01 only when separately
allocated; otherwise explicit skips. All work stays in owned paths. No new agents
or other-chat messages. Independently inspect peers' committed scripts read-only,
then push only owned tests/docs/evidence with exact source/runner hashes and limits.

## Later source comparison

Coordinator requested comparison against separately pushed onboarding follow-up
`8ae97c2d57c0efda5a03a41a469bf9447739ee72` (runtime `52fdda8`). Preserve all
`abab30a` evidence. The onboarding worker additionally owns the same new QA paths in
`munimjee-wave8-onboarding-followup-qa` / `codex/v1-onboarding-followup-independent-qa`,
`docs/v1-independent-onboarding-followup-comparison.md` and the comparison evidence
subfolder. Apply only owned tests/evidence there, never older production source.
Rebuild fixtures against that source and report fixed/remaining case IDs. Other
workers review only attribution/harness changes. Current local `789db95` /0056 is
reported context; fetched integration remained `abab30a` at this handoff request.
Neither older 1,950-test evidence nor new follow-up reports certify that local head.

The storefront worker also owns its same QA paths in
`munimjee-wave8-storefront-followup-qa` / `codex/v1-storefront-followup-independent-qa`
and `docs/v1-independent-storefront-followup-comparison.md`, to rerun the same 75
cases against fresh `8ae97c2` source. Preserve the original branch/evidence. No
additional activity acceptance or new production ownership is implied.
