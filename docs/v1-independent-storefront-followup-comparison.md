# Fresh storefront comparison against fetched 8ae97c2

Actual application source: `8ae97c2d57c0efda5a03a41a469bf9447739ee72` (storefront
runtime `52fdda8d84f261841a44ef6a84e38e78cd93f237`). The original independent QA
commit `faec01614c27578afd38bef750b9dc2205ee7c98` was cherry-picked alone onto this
source as `52cb7137cc1904f78ff0678f2e7ed96fafe204ad`; no old application source was
brought across. Only a trusted owned-directory output option was added to the
exporter/runner, in separate commit `51f24801a5beb7f39ee57f8739301c633b056272`.
The same 75 scenario names and assertions remain unchanged.

Fresh actual SSR fixtures were rebuilt and the actual newer live modules loaded
in isolated Chromium. The result is **69 passed / 6 failed**, matching the original
UI outcomes. The missing-photo title/price overlap is now freshly observed in all
three themes at both 320px and 390px; its spatial assertions remain red. In addition,
**153 same-origin activity-context POST attempts were denied as unhandled** by the
unchanged network fixture. Overall execution exits **1**. This is not an all-green
newer-runtime acceptance report.

| Evidence | Original abab30a run | Fresh 8ae97c2 run |
| --- | --- | --- |
| UI scenarios | 69 pass / 6 cart-overlap red | 69 pass / 6 same cart-overlap red |
| Page errors | 0 | 0 |
| Unexpected external origins | 0 | 0 |
| Unhandled same-origin routes | 0 | 153 denied activity-context POST attempts |
| Application hashes unchanged during run | yes | yes |

The 153 attempts target only
`POST /api/v1/storefronts/experience/activity/contexts`. They were aborted before
any server/provider; none were allowed, continued or fetched. No activity success,
disabled-state or event response was synthesized, and no DNT/GPC/tracking override
was introduced. These attempts are a **harness coverage boundary**, not successful
activity collection and not a standalone product defect. Activity contract coverage
remains **MISSING** under the separately owned local activity work. This sweep proves
shopping UI behavior under denied optional activity requests; it does not prove
ready-context/event/proof behavior.

## Exact source and evidence attribution

Fresh results are confined to:
`artifacts/v1/independent-storefront-experience/comparison-8ae97c2/`.
The original artifact folder files and original QA document were preserved; all
29 original evidence/document files still match their original Git blob OIDs. The
original worktree and `codex/v1-storefront-mobile-qa` branch were untouched.

The comparison directory contains nine freshly rendered SSR fixture files,
`fixtures/metadata.json`, `result.json`, `comparison-summary.json`,
`runner-output.txt` and newly captured screenshots. All 20 application source hashes
were verified against exact `8ae97c2` Git blobs, as well as before/after the run.
The recorded QA HEAD is `52cb713` because this run preceded committing the trusted
output adaptation; the exact executed harness content is identified by the SHA256
values below and is now committed in `51f2480`.

- Runner SHA256: `6c90c4262f9b5373c29d5dd80e30df5269c8a08d774d2c63db408e95a75769b1`.
- Exporter SHA256: `688efd87f171344b413d2a092cac76383f725ec85792eaf51e1f73e18a0f3c64`.
- Browser: cached Chromium `153.0.8010.12`; no installation or shared user profile.
- Python: `/tmp/munimjee-release-ci-py311/bin/python` (3.11).

`comparison-summary.json` records the exact commands, preservation checks and
byte-identical scenario/assertion runner tail after the output-configuration prefix.
`result.json` records every scenario, actual painted-text rectangles, source/fixture
hashes, representative contrast observations and all 153 denied attempts. Syntax
and Python compilation checks pass. No application files differ from `8ae97c2`.

To reproduce, use the original commands with these trusted output arguments:

```sh
PYTHONPATH=backend /tmp/munimjee-release-ci-py311/bin/python backend/tests/independent_storefront_experience_qa.py --output artifacts/v1/independent-storefront-experience/comparison-8ae97c2/fixtures
MUNIMJEE_STOREFRONT_QA_OUTPUT=/Users/user/Documents/ChatGPT/munimjee-wave8-storefront-followup-qa/artifacts/v1/independent-storefront-experience/comparison-8ae97c2 MUNIMJEE_PLAYWRIGHT_MODULE=/Users/user/Documents/ChatGPT/munimjee-wave3-qa/frontend/storefront/node_modules/@playwright/test/index.mjs PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Users/user/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' node backend/tests/independent_storefront_experience_qa.mjs
```

## Remaining boundaries

The local implementation owner still needs to fix and freshly verify the six
missing-photo cart assertions. New activity context/event routes, refused/ready/
malformed states, optional proof headers and context renewal during financial replay
remain separately owned cases; this follow-up adds no activity scenario expansion.
The old source-only attribution report stays historical rather than being rewritten.
No claim covers the coordinator-reported unpushed 0056 source, physical devices,
assistive technology, real media/CDN, migrated persistence, providers or production.
No actual credential, DB, provider, message, charge, server or production operation
occurred. Only fresh SSR generation and isolated intercepted browser execution ran.
