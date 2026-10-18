# V08 conservative material-intent repair

Runtime candidate `3b91a3a96a6c3f104e0666bb19dfbd97d1bc96e9` changes only
`backend/app/services/sku_fact_replies.py` on base
`e7edea1613b9902c726ce571e3d16c169c8cf190`. **Focused verification: 65 passed,
0 failed, 0 skipped**, including the unchanged original 15 semantics and 6 context
cases. The prior material red evidence remains intact.

## Behavior and minimal change

The bounded factual classifier previously admitted `material` and `materials`,
although its fact decoder and renderer have no material/composition contract.
A buyer asking “What material is this?” received a generic options/price/stock
summary without material-specific uncertainty. This was a P2 response/actionability
gap; the prior test did not demonstrate an invented material or financial fact.

Remove these two words from both `_FACT_WORDS` and the requested-topic set. The
whole-input allowlist now rejects those unsupported tokens, including mixed
questions containing material plus supported price/stock/options topics. Existing
callers retain their existing `HANDOFF` response:

> Our team will confirm the current options, price and availability for this product.

This is conservative handling of an unsupported intent. It does not assert that
material is unavailable, absent from seller approval, or known to the application.
No sentence-specific exception, caller change, new schema field, inferred fact,
model output or altered reply text is introduced. Source checks prove the entire
file equals its baseline with only the two approved substitutions. All ten other
function bodies, including `read_facts` and `render`, and the `HANDOFF` assignment
remain byte-identical. Independent QA owns supplemental ordinary/mixed-question
coverage; this implementation lane edits no tests.

## Evidence and boundary

`artifacts/v1/v08-material-repair/focused-65.txt` and `focused-65.xml` retain the
raw successful run. `verification.json` records exact source/function hashes, test
counts and 18 unchanged baseline-file hashes: both original acceptance test files
and 16 prior evidence files. Source SHA-256 is
`884bdbdd3df66658a9c1f295494931c87fed17a2777c65757642e5140cb8b953`.

| Unchanged selected test file | Passed |
| --- | ---: |
| `test_sku_fact_replies.py` | 21 |
| `test_intent_classifier.py` | 8 |
| `test_prompt_builders.py` | 15 |
| `test_v08_semantics_acceptance.py` | 15 |
| `test_v08_context_acceptance.py` | 6 |

The original semantic tests execute real reference parsing, inbound context,
reply decision, factual classification, approved-row decoding and reply rendering
where their scenarios reach those functions. They inject strict read-only synthetic
projections through `scalar`/`scalars`/`execute`; no SQL is executed and no LLM reply
or provider result is injected. Material requests now branch to HANDOFF before
fact rendering. Exact approved price/options/stock responses remain independently
asserted by literal expectations. The three Hindi Devanagari passes establish safe
handoff, not three successful Hindi answers or multilingual quality.

Reproduce from this worktree:

```sh
PYTHONPATH=backend /tmp/munimjee-release-ci-py311/bin/python -m pytest backend/tests/test_sku_fact_replies.py backend/tests/test_intent_classifier.py backend/tests/test_prompt_builders.py backend/tests/test_v08_semantics_acceptance.py backend/tests/test_v08_context_acceptance.py -q -o junit_family=xunit1 --junitxml=artifacts/v1/v08-material-repair/focused-65.xml
```

Python 3.11 completed in 0.32s with one existing Pydantic config deprecation
warning. This run allocates no database or server, calls no provider/model/sender,
reads no credentials, and performs no Docker or production operation. It does not
prove PostgreSQL authority gates, persisted handoff/queue, actual delivery, broad
language quality, or full V08/V1 acceptance. The mounted local gate and independent
QA/review remain separate coordinator-owned evidence.
