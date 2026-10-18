# V08 material repair: independent regression QA

Frozen baseline source `e7edea1613b9902c726ce571e3d16c169c8cf190` contains the reviewed original 21 episodes. The coordinator approved exactly six incremental M01–M06 cases before writes. Existing tests, including all original 21 assertions and the strict reused adapter, remain read-only. This lane authors QA only.

The additional baseline ran once: **3 failed, 3 passed, 0 errors, 0 skipped**, exit 1, in 0.18s. M01–M03 reproduce the same P2 response/actionability gap as the preserved original singular-material red: generic catalogue facts do not identify missing material uncertainty. No invented material, price, stock or financial action is observed. Unchanged raw text and xunit1 XML are in `artifacts/v1/v08-material-qa/baseline/`.

| ID | Frozen additional composition gap | Baseline |
| --- | --- | --- |
| M01 | Plural “What materials are available?” with otherwise valid synthetic observations requires handoff or material-specific uncertainty. | Fail: generic facts only. |
| M02 | Mixed singular “What price and material is this?” has the same missing-material requirement. | Fail: generic facts only. |
| M03 | Mixed plural “What sizes stock and materials are available?” has the same missing-material requirement. | Fail: generic facts only. |
| M04 | Supported mixed “What prices sizes and stock are available?” preserves an independent full literal reply, including approved price 0, recorded zero stock and unknown stock. | Pass: exact facts, no blanket handoff. |
| M05 | Material query with an empty SKU projection still withholds fact authority before unsupported-intent handling. | Pass: `None`, no reply. |
| M06 | Mixed price/material query with null required price still withholds invalid fact authority. | Pass: `None`, no reply. |

The unchanged original 21 already cover the original singular material question, ordinary English/Hinglish price/size/stock, unsupported Devanagari handoff, buyer policy overrides, missing SKU/price, and context conflicts. They will be rerun with the candidate rather than duplicated in new tests. Unsupported Hindi remains a safe handoff; it is not evidence of Hindi answer support.

The new module reuses only `ReadOnlyProjection` from the unchanged semantic suite. Its independent literal fixture identifiers match the adapter's declared fixture. New raw observations, actual invocation and expected reply/oracle are owned in the new file. The actual chain is `whatsapp_context.inbound_context` / `instagram_references` → `sku_fact_replies.exact_reel_products` / `reel_candidates` → `whatsapp_context.reel_reply_decision` → `is_activated` / `read_facts` / `SKUFact` and `ProductFacts` validation → `reel_question` / `factual_request` / `render` or existing human handoff. No classifier, selection, decision, validation or render function is monkeypatched. Only trusted synthetic rollout and the raw repository-return boundary are injected.

The adapter rejects undeclared projections, tenant/product/reel bindings and call shapes, while the new tests require the exact five-call composition. It is not a SQL engine: raw rows assume the repository result, without proving PostgreSQL tenant/activation/publication predicates, joins, locks, persistence or current-state authority. M01–M03 permit an explicit truthful material-unknown answer as well as the existing handoff; a generic preferred-option confirmation does not satisfy the criterion. M05–M06 prove withholding only, not queue/notification/resume.

Baseline command from `backend`:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest tests/test_v08_material_reply_regression.py -q -o junit_family=xunit1 --junitxml=../artifacts/v1/v08-material-qa/baseline/results.xml > ../artifacts/v1/v08-material-qa/baseline/run.txt 2>&1
```

The existing pre-import safety gate is explicitly installed before application imports. No DB/server/provider/LLM, credentials, sends, Docker or ambient 4317 is involved. Actual database/mounted acceptance, durable queue/handoff/resume, live provider policy/delivery, broader language quality and full V08/X01 acceptance remain separate gates. Runtime candidate composition and final verification are pending this preparation checkpoint.
