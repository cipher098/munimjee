# V08 bounded semantics acceptance tests

Frozen application base `d4026b1ebf8e9e11865ccf2172ded41bcdc0ac22`, documenting the
separately tested integration runtime `eeb94a1`/0056. This lane adds tests/docs only;
it allocates no DB and makes no runtime or schema change.

**Frozen 15 scenarios: 14 passed, 1 failed, 0 skipped; exit 1.** The raw log/XML
remain in `artifacts/v1/v08-semantics/first-run.{txt,xml}`. No xfail, assertion
weakening or runtime fix is included.

## Reproduced P2: missing approved material gets no specific uncertainty

The actual message parser/context/reply path receives an explicit mapped reel and
“What material is this?”. The synthetic public projection contains approved size,
color, price and stock facts, with no material/composition fact. Actual response:

```text
Current catalogue: Semantic kurta.
• Color: Indigo; Size: M — ₹123.45; recorded available: 2.
• Color: Indigo; Size: L — ₹145.67; recorded out of stock.
• Color: Indigo; Size: XL — ₹167.89; availability untracked; please confirm with our team.
Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.
```

The customer receives neither a human handoff nor material-specific unknown/
confirmation language. The red assertion allows either correct behavior; it does
not require a particular phrase when explicit material uncertainty is present.
This is a semantic/actionability gap. The reply does **not** invent material, price
or stock, and this test does not establish a financial/safety hard-gate violation.

Relevant source: `sku_fact_replies.factual_request` accepts material/materials;
`whatsapp_context.reel_reply_decision` routes accepted factual requests to the
renderer; the current `ProductFacts`/renderer contains only product name and SKU
options/price/stock. The final generic preferred-option confirmation does not
identify the missing material fact. Exact function lines/hashes and full assertion
are retained in `verification.json` and the raw red log for the runtime owner.

## Prior coverage and frozen additions

Audited existing `test_sku_fact_replies.py`, `_db.py`, intent-classifier,
prompt-builder and relevant conversation/responder/context code before proposing
this plan to the coordinator. Existing coverage already checks the small classifier
vocabulary, handoff categories, rendering, strict public facts, migrated freshness,
current sender/reference gates, model-JSON parsing and legacy prompt formatting.
The gap is a bounded current-SKU question matrix through actual parsing/context/
reply assembly, rather than another renderer-only or fabricated-model-answer test.

| Fixed group | Cases | Expected/observed boundary |
| --- | --- | --- |
| English price/size/stock | 3 | Exact independently written public SKU reply; all pass |
| Hinglish price/size/stock | 3 | Supported bounded vocabulary yields the same exact facts; all pass |
| Hindi Devanagari price/size/stock | 3 | Unsupported vocabulary safely yields human HANDOFF; all pass |
| English/Hindi/Hinglish buyer policy overrides | 3 | Buyer instructions remain data and retain HANDOFF; all pass |
| Missing approved SKU rows | 1 | No automatic reply; pass |
| Missing approved price | 1 | Strict real fact decoding withholds reply; pass |
| Missing approved material | 1 | Specific uncertainty/handoff required; **fail** |

The six factual-answer cases compare the entire reply against literal expected
lines, never `render(expected) == render(actual)`. Exact minor-unit prices are
preserved, zero means recorded out of stock, and null stock remains untracked with
team confirmation. The three Hindi passes are **safe handoff evidence**, not three
successful Hindi product answers or proof of multilingual model quality. A withheld
`None` reply proves no automatic answer at this seam, not a persisted human queue.

## Actual functions and injected seam

Tests execute real `instagram_references` → `inbound_context` →
`reel_reply_decision` → `exact_reel_products` / `is_activated` / `read_facts` →
`reel_question` / `factual_request` / `render`. The existing test safety policy runs
before application imports. The rollout flag is explicitly enabled only inside the
synthetic test fixture. The activated-SKU route is deterministic; no intent-model,
LLM/provider output, classifier JSON or reply text is injected.

The sole adapter supplies declared **read-only synthetic projections**: exact URL
registry, product-name row, activation identity, and three raw approved public SKU
rows. It rejects unexpected query shapes/tenant/product/reel bindings. Real source
constructs its SQL and validates/decodes the rows. The adapter executes no SQL and
is not a SQL engine, authority check, PostgreSQL or persistence proof. In particular,
this does not re-verify real seller/publication/mapping/current delivery gates.
No provider or sender is called at this decision boundary.

The other lane owns explicit switching, ambiguity, stale context and pause/reconnect.
No scenarios were added after the 15-case plan was approved. V08/X01/A11/A13/A14/A15
remain incomplete; legacy release-matrix rows and actual-provider gates are not
silently marked complete by these focused tests. No answer-quality score is assigned.

## Reproduce and evidence

```sh
PYTHONPATH=backend /tmp/munimjee-release-ci-py311/bin/python -m pytest backend/tests/test_v08_semantics_acceptance.py -q -o junit_family=xunit1 --junitxml=artifacts/v1/v08-semantics/first-run.xml
```

Python 3.11 completed in 0.19s, with one existing Pydantic config deprecation warning.
`verification.json` records exact test/source/function/artifact hashes, declared
projection rows, source-base equality, function lines, expected/actual red behavior
and limits. No actual DB/server/provider/credential/send/LLM/Docker/ambient4317 or
production operation occurred. This red checkpoint is for independent review and
local runtime repair; full semantics, delivery and V1 acceptance remain open.
