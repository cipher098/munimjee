# V08 missing-material repair handoff

18 October 2026. The reproduced material response gap is repaired in the bounded
current-SKU classifier. All original21 acceptance cases remain unchanged and now
pass; six added material/mixed-question regressions pass. Independent QA's
focused gate is **48 passed, 0 failed/errors/skipped**. Local integrated
migrated/mounted validation remains the next gate.

## Change and integration

Runtime-only commit: `3b91a3a96a6c3f104e0666bb19dfbd97d1bc96e9`.
Only `backend/app/services/sku_fact_replies.py` changes, by removing `material`
and `materials` from both the supported-word allowlist and requested-topic set.
The file equals its base with precisely those two substitutions. Source SHA-256:
`884bdbdd3df66658a9c1f295494931c87fed17a2777c65757642e5140cb8b953`.

“What material is this?”, plural material questions and questions mixing
material with price/size/stock now retain the existing response:

> Our team will confirm the current options, price and availability for this product.

The classifier conservatively hands material intent to team confirmation. It
does not infer garment facts or assert whether a seller has approved material.
Supported price/size/stock questions retain exact facts. Both token locations
must change: leaving material in the allowlist would still admit mixed questions
through another supported topic.

No caller change was needed. `whatsapp_context.py`, the Instagram caller,
`read_facts`, `render`, `HANDOFF`, schemas, sender, provider, authentication,
activity/ingress/outbox and all other runtime remain unchanged. There is no
collision with local ingress/outbox ownership. No automatic reply gains
authority when the SKU observation is empty or required price is invalid.

The exact base is `e7edea1613b9902c726ce571e3d16c169c8cf190`, which contains
`d4026b1` application source plus the reviewed21-case packet. The runtime commit
is composed on `codex/v1-v08-material-coordination` as `d3aacd9`; apply either
the original or its composition, not both. The original runtime commit can be
used separately from the test/docs packet. Original21 test bodies and all prior
red evidence are byte-preserved as historical observations of their pinned base.

## Focused evidence

Existing named GPT-6.1 Sol/high workers were reused for implementation,
independent QA and independent review. Completed checkpoints:

| Lane | Exact pushed head | Coordinator composition |
| --- | --- | --- |
| Implementation / evidence | `aea4effd148810f63f079369adcf2dc87822290d` on `codex/v1-v08-material-repair` | Runtime `d3aacd9`, evidence `1557a2c` |
| Independent QA | `5faa15255c085a16f50954ec2ae5ca7baa78a569` on `codex/v1-v08-material-qa` | Baseline/test `02d0fe3`, final evidence `9d6e9ed` |
| Independent review | `d8885432143922afa881f326249f8f26bbe5b5e1` on `codex/v1-v08-material-review` | `f416327` |

Independent review found no scoped source, harness or assertion blocker. It
verified the exact two-line transform, all219 unchanged existing test files,
all16 prior V08 evidence files, the unchanged six-case harness and raw red
baseline, all owner/QA source/artifact hashes and11 service-function hashes.
Actual XML properties confirm original singular material and M01–M03 return
the existing handoff, while M04–M06 preserve facts and authority withholding.
The review did not rerun the already passing tests.

| Gate | Base observation | Repaired observation |
| --- | --- | --- |
| Original21 accepted cases | 20pass/1materialfail in the preserved prior packet | 21pass, unchanged assertions |
| New M01 plural / M02 price+material / M03 size-stock+materials | 3 reproduced failures in one frozen baseline run | Existing handoff for all3 |
| M04 supported mixed facts | Pass | Exact literal reply preserves approved zero price and zero/null stock |
| M05 empty observation / M06 null required price | Pass | Remain withheld before intent handling |
| Independent QA: original21 + new6 + existing pure SKU21 | Separate pinned baselines above | 48pass, exit0 |
| Implementation: original21 + existing44 focused checks | Prior65-check packet had one material failure | 65pass, exit0 |

The gates overlap and must not be added as unique test counts. All27 acceptance
cases pass. Both current runs retain only the existing Pydantic config
deprecation warning. No assertions changed after the new baseline failures;
no skip, xfail or original-case replacement was introduced.

The new six-case file reuses only the unchanged strict raw-projection adapter.
It independently specifies fixture rows, literal expected supported replies,
material uncertainty criteria and the real parser/context/decision invocation.
The actual path runs `instagram_references`, `inbound_context`,
`reel_reply_decision`, exact reel resolution/activation, `read_facts` and strict
public-fact validation, then real classification and rendering where eligible.
The IG normalization/freeze path remains covered by the unchanged context cases.
Only synthetic rollout settings and raw repository rows are supplied; no model
answer, provider result, domain decision or renderer is injected.

The original Hindi Devanagari checks still establish safe handoff. They are not
answered Hindi product questions or proof of multilingual model quality. A
withheld reply is not a durable handoff/queue/resume result. Material handoff
passes the bounded response criterion without creating a material-answering
capability.

## Reproduction and limits

From repository root, using the existing cached Python runtime:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest backend/tests/test_v08_semantics_acceptance.py backend/tests/test_v08_context_acceptance.py backend/tests/test_v08_material_reply_regression.py backend/tests/test_sku_fact_replies.py -q -o junit_family=xunit1
```

Expected repaired result:48pass, exit0. Source, original-test, new-test,
baseline/current artifact hashes and exact branch/composition mappings are in
the new manifests. Earlier raw red text/XML is not overwritten. Root composition
verification checks exact equality to the independently tested bytes rather than
repeating the already passing runs without source changes.

See [implementation](v1-v08-material-repair.md),
[independent QA](v1-v08-material-qa.md),
[independent review](v1-v08-material-review.md) and
`artifacts/v1/v08-material-coordination/final-verification.json`.

This is source/synthetic-row evidence. SQL is constructed but never executed;
it does not certify PostgreSQL current authority, persistence, transaction or
locking behavior. No DB/server slot, provider/model call, credential access,
customer send, Docker, ambient4317 or production/release action occurred.
Local integrated migrated/mounted validation, same-account reconnect followed
by queued WhatsApp SKU delivery, seller-visible unknown/link/resume, authorized
provider delivery and full V08/X01/V1 acceptance remain separate gates.
