# V08 material repair: independent regression QA

The reviewed repair passes **48 checks, 0 failures/errors/skips**, exit 0, in 0.24s: original 21 episodes, six new regressions, and 21 existing pure SKU checks. Material questions use the existing handoff; supported mixed questions still return exact known facts, including zero approved price and zero/null stock. Missing fact authority still withholds. This is independent synthetic-row composition proof, not database/provider or full V08 acceptance.

Frozen baseline `e7edea1613b9902c726ce571e3d16c169c8cf190` contains the reviewed original 21 episodes. Runtime owner `3b91a3a96a6c3f104e0666bb19dfbd97d1bc96e9` was composed after coordinator review as `fb8e927`. Its only runtime diff removes `material`/`materials` from both bounded vocabulary sets in `sku_fact_replies.py`; no caller, schema or other runtime change. Current runtime bytes match the owner's commit exactly. This lane authored no runtime.

The coordinator approved exactly six incremental M01–M06 cases before writes. All **219 existing tracked test files** remain byte-identical to the frozen base, including original 21 assertions and the reused adapter. The new harness is also byte-identical between baseline and repaired runs. All **16 prior V08 artifact files** and the new baseline red artifacts remain unchanged; exact hashes are in the final verification manifest.

The additional baseline ran once: **3 failed, 3 passed, 0 errors, 0 skipped**, exit 1, in 0.18s. M01–M03 reproduce the same P2 response/actionability gap as the preserved original singular-material red: generic catalogue facts do not identify missing material uncertainty. No invented material, price, stock or financial action is observed. Unchanged raw text and xunit1 XML are in `artifacts/v1/v08-material-qa/baseline/`.

| ID | Frozen additional composition gap | Baseline | Repaired |
| --- | --- | --- | --- |
| M01 | Plural “What materials are available?” with otherwise valid synthetic observations requires handoff or material-specific uncertainty. | Fail: generic facts only. | Pass: existing handoff. |
| M02 | Mixed singular “What price and material is this?” has the same missing-material requirement. | Fail: generic facts only. | Pass: existing handoff. |
| M03 | Mixed plural “What sizes stock and materials are available?” has the same missing-material requirement. | Fail: generic facts only. | Pass: existing handoff. |
| M04 | Supported mixed “What prices sizes and stock are available?” preserves an independent full literal reply, including approved price 0, recorded zero stock and unknown stock. | Pass: exact facts, no blanket handoff. | Pass: identical exact facts. |
| M05 | Material query with an empty SKU projection still withholds fact authority before unsupported-intent handling. | Pass: `None`, no reply. | Pass: `None`. |
| M06 | Mixed price/material query with null required price still withholds invalid fact authority. | Pass: `None`, no reply. | Pass: `None`. |

The unchanged original 21 cover the original singular material question, ordinary English/Hinglish price/size/stock, unsupported Devanagari handoff, buyer policy overrides, missing SKU/price, and context conflicts. All 21 pass in the single repaired run. Unsupported Hindi remains a safe handoff; it is not evidence of Hindi answer support.

The new module reuses only `ReadOnlyProjection` from the unchanged semantic suite. Its independent literal fixture identifiers match the adapter's declared fixture. New raw observations, actual invocation and expected reply/oracle are owned in the new file. The actual chain is `whatsapp_context.inbound_context` / `instagram_references` → `sku_fact_replies.exact_reel_products` / `reel_candidates` → `whatsapp_context.reel_reply_decision` → `is_activated` / `read_facts` / `SKUFact` and `ProductFacts` validation → `reel_question` / `factual_request` / `render` or existing human handoff. No classifier, selection, decision, validation or render function is monkeypatched. Only trusted synthetic rollout and the raw repository-return boundary are injected.

The adapter rejects undeclared projections, tenant/product/reel bindings and call shapes, while the new tests require the exact five-call composition. It is not a SQL engine: raw rows assume the repository result, without proving PostgreSQL tenant/activation/publication predicates, joins, locks, persistence or current-state authority. M01–M03 permit an explicit truthful material-unknown answer as well as the existing handoff; a generic preferred-option confirmation does not satisfy the criterion. M05–M06 prove withholding only, not queue/notification/resume.

Baseline command from `backend`:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest tests/test_v08_material_reply_regression.py -q -o junit_family=xunit1 --junitxml=../artifacts/v1/v08-material-qa/baseline/results.xml > ../artifacts/v1/v08-material-qa/baseline/run.txt 2>&1
```

Repaired command from `backend`, run once after exact reviewed runtime composition:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest tests/test_v08_semantics_acceptance.py tests/test_v08_context_acceptance.py tests/test_v08_material_reply_regression.py tests/test_sku_fact_replies.py -q -o junit_family=xunit1 --junitxml=../artifacts/v1/v08-material-qa/repaired/results.xml > ../artifacts/v1/v08-material-qa/repaired/run.txt 2>&1
```

One existing Pydantic class-config deprecation warning is retained. No failing assertion was weakened or skipped. QA baseline checkpoint `68441dd` was pushed before runtime composition for read-only owner/reviewer inspection. Final raw text/XML, actual new-case replies, owner/source mapping and source/test/artifact hashes are in `artifacts/v1/v08-material-qa/verification.json`. Source verification compares frozen Git and exact owner bytes with the current checkout, rather than claiming DB snapshot execution.

The existing pre-import safety gate is explicitly installed before application imports. No DB/server/provider/LLM, credentials, sends, Docker or ambient 4317 is involved. Actual database/mounted acceptance, durable queue/handoff/resume, live provider policy/delivery, broader language quality and full V08/X01 acceptance remain separate gates.
