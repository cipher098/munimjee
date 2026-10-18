# V08 conversation semantics: independent acceptance handoff

18 October 2026. The bounded tests/docs packet is complete on exact integration
base `d4026b1ebf8e9e11865ccf2172ded41bcdc0ac22`. The frozen21 new cases produce
**20 passed, 1 failed, 0 skipped**. The failure is a reproduced P2 response gap:
missing approved material receives neither explicit uncertainty nor human
handoff. The packet deliberately remains red for the local runtime owner.
No application, schema, static asset or existing test is changed.

## Reproduced finding for the runtime owner

With a uniquely mapped explicit reel, ask **“What material is this?”**. Supply
approved public rows for Size M/L/XL, Color Indigo, INR12345/14567/16789 minor
units and stock2/0/null, with no material/composition fact. The actual reply is:

```text
Current catalogue: Semantic kurta.
• Color: Indigo; Size: M — ₹123.45; recorded available: 2.
• Color: Indigo; Size: L — ₹145.67; recorded out of stock.
• Color: Indigo; Size: XL — ₹167.89; availability untracked; please confirm with our team.
Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.
```

This omits the requested material fact without identifying its uncertainty.
Generic preferred-option confirmation does not tell the buyer material is
unrecorded. The assertion accepts human handoff or material-specific uncertainty;
it does not require a single exact phrasing for the latter.

Exact failed node:
`backend/tests/test_v08_semantics_acceptance.py::test_missing_approved_fact_withholds_or_identifies_uncertainty[missing-approved-material]`.
Source `backend/app/services/sku_fact_replies.py:108` accepts `material` in the
factual vocabulary, while `backend/app/services/whatsapp_context.py:154` routes
the request to `facts.render`; the renderer at
`backend/app/services/sku_fact_replies.py:92` returns the available catalogue
summary. Source hashes and function spans are recorded in the semantic manifest.

Disposition: P2 semantic/actionability gap under V08's uncertainty requirement.
This reply does **not** invent material, price or stock and does not demonstrate
an unauthorized financial action. Runtime remediation belongs to the local
channel/catalogue owner; no fix, xfail, skip or assertion weakening is included.
After repair, rerun the preserved cases against the composed runtime and complete
the relevant actual migrated/mounted gate.

## Frozen scenario results

The go-live plan and acceptance matrix were read before auditing current source
and existing cases. The21-case plan was approved before test writes; it did not
grow after results. Historical acceptance-matrix wording remains unchanged.
Current source already implements a deterministic SKU fact lane.

| New group | Count | Result |
| --- | --- | --- |
| English price/size/stock | 3 | Exact independently specified approved SKU reply |
| Supported Hinglish price/size/stock | 3 | Exact independently specified approved SKU reply |
| Hindi Devanagari price/size/stock | 3 | Safe human handoff; no Hindi answer-quality claim |
| English/Hindi/Hinglish buyer policy overrides | 3 | Human handoff; buyer text cannot substitute the requested false facts in this bounded lane |
| Missing approved SKU rows / required price | 2 | Reply withheld; no queue/operator-review proof |
| Missing approved material | 1 | **P2 failure**, as above |
| C01 explicit A then B, despite old quote A | 1 | Exact B reply, no A name/price |
| C02 distinct A+B / C03 one reel mapped to two / C04 new unknown reel | 3 | Withheld; no unrelated first/last/prior-product reply |
| C05 one normalized IG text: new B URL + reply-to A | 1 | Clarification handoff exception before selection effects |
| C06 unsupported new share URL + old reply-to A | 1 | Clarification handoff exception; no prior A fallback |

Ambiguous/unknown WA results are `reply=None, review_reason=None`. This is
withholding only, not seller-visible clarification, persistence or eligible
resume. IG exceptions similarly do not prove durable handoff. The dedicated
same-account reconnect → queued activated-SKU WhatsApp delivery journey was not
found in audited tests and remains an **unverified coverage gap**, not a
reproduced runtime defect. Existing actual-DB tests for final pause/token/account
changes, all-reference revalidation, queued comment reconnect generation and
current WA intent gates are credited by exact reference in the context report;
they were not rerun without a DB slot.

## Actual functions and injected boundaries

| Actually exercised | Boundary supplied by the tests |
| --- | --- |
| `instagram_references`, `inbound_context`, `reel_reply_decision`; `exact_reel_products`/`reel_candidates`, `is_activated`, `read_facts`; strict `SKUFact`/`ProductFacts` decoding; `reel_question`, `factual_request`, `render` | Trusted synthetic rollout setting and declared raw scalar/name/activation/SKU rows. Query shapes, tenant/product bindings, exact reel binding and expected consumption are checked. SQL is constructed but never executed. |
| `normalize_message`/`validate_message_shape`, `instagram_batch_context`, `freeze_instagram_batch` | Synthetic raw ingress envelopes and raw repository results; actual context selection and exception logic run unchanged. |
| Existing intent parser, prompt builders and basic SKU tests | Root's focused existing44-check baseline; not a live model evaluation. |

No context, classifier, selection, decision or render function is replaced in the
new tests. No LLM output, provider response or desired reply is injected. The six
successful fact replies compare all text to independent literal expected lines.
No model/provider transport is needed by this deterministic current-SKU route.
The legacy model responder and its prompt-injection resistance are not certified.

Scripted raw rows do not establish PostgreSQL tenant/publication/current-state
predicate evaluation, approval authority, transaction isolation, locks,
uniqueness, persistence or restart behavior. No cross-tenant SQL-enforcement
claim follows from checking query bindings. The shared pre-import safety policy
blocks outbound networking and dotenv/provider settings. No DB/server slot,
Docker, ambient4317, credential access, provider/model call, real send, release
or production operation occurred.

## Checkpoints and reproduction

| Lane | Exact submitted checkpoint | Coordinator composition |
| --- | --- | --- |
| Semantic15 test/docs/evidence | `98fe4bb61c37875fd3fa7f82dad3f0d8037ced25` on `codex/v1-v08-semantics-tests` | `c9fc6f9` |
| Context6 test/docs/evidence | `8a1860dd592ebe865f28c1d069fa1b0d83622ea3` on `codex/v1-v08-context-tests` | `61646c1` |
| Independent initial source review | `b4f6d1534cafc2978003d8bd704b6ee784f601f9` on `codex/v1-v08-independent-review` | `8743967` |
| Independent final assertion/evidence review | `5a552079a917343c26153679b0b592f18f5bb1d7` on `codex/v1-v08-independent-review` | `84744f5` |

Existing named GPT-6.1 Sol/high workers were reused. Semantic raw evidence reports
14pass/1fail, context raw evidence6pass. Root independently ran the three existing
focused files plus both new files after composition: **64pass/1samefail/0skip**
in0.35s, exit1. The44-check existing baseline separately passes. Root's composed
command omitted `junit_family=xunit1`, producing15 record-property compatibility
warnings plus the existing Pydantic warning; raw output is retained and no test
outcome is inferred from warnings. No additional scenarios or repeat green run
was used to replace this result.

Independent review found no scoped harness/assertion-fidelity blocker and
separately reproduced the same21 cases as20pass/1materialfail/0errors/0skips.
It verified all peer source, safety, test, raw-evidence and nine semantic
function-span hashes. Its initial cross-worktree invocation failed during
collection before tests ran; the retained successful invocation explicitly
loaded one unchanged safety conftest. That supplemental reproduction is distinct
from root's canonical composed-checkout run. The material regex is a bounded
English clarity criterion, not a complete language or hallucination oracle.

To reproduce the21 new cases from repository root:

```sh
/tmp/munimjee-release-ci-py311/bin/python -m pytest backend/tests/test_v08_semantics_acceptance.py backend/tests/test_v08_context_acceptance.py -q -o junit_family=xunit1
```

Expected current result:20pass/1materialfail, exit1. Both new test files and all
runtime/source/evidence hashes are recorded in lane manifests and the root final
verification artifact. Source/docs whitespace checks pass; raw red text/XML
retain pytest's original trailing whitespace and are intentionally not normalized.

See [semantic report](v1-v08-semantics-tests.md),
[context report](v1-v08-context-tests.md),
[independent review](v1-v08-independent-review.md), and
`artifacts/v1/v08-semantics-coordination/` for root logs and exact verification.
The coordinator branch is `codex/v1-v08-semantics-coordination`; this is a
tests/docs handoff, not a green runtime acceptance checkpoint.

## Remaining acceptance

The runtime/test bytes of base match the separately reported `eeb94a1`
actual0056 checkpoint; its2425pass/8skips are historical context only. This
packet does not allocate or certify that DB, current migrated/mounted
pause/reconnect/context/unknown-to-link/resume journeys, provider/account policy,
real model quality, authorized live delivery, physical devices or full V08/X01.
No central roadmap, release status, cart or native onboarding file is modified.
