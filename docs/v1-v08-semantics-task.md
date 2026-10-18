# V08 independent conversation acceptance task

18 October 2026. Base: `d4026b1ebf8e9e11865ccf2172ded41bcdc0ac22` from
`origin/codex/v1-integration`. Application and existing test bytes are identical
to the reported complete `eeb94a1` actual0056 checkpoint; that historical
2425-pass/8-skip mounted gate is not rerun or certified by this packet.

The task follows `go-live-plan.md` V08, catalogue rules 1/2/4/8/9/10/11,
execution protocol and AI regression hard gates, plus acceptance matrix V08,
A13/A14/A15/A19 and X01. Historical matrix wording is preserved; current source
is audited directly. No roadmap expansion or arbitrary answer-quality score.

## Scope and ownership

Reuse the named GPT-6.1 Sol/high workers in isolated worktrees from the exact
base. Workers first audit existing coverage, then propose a finite scenario
matrix before writing missing tests. No runtime or schema changes are owned.

| Worker | Worktree / branch | Allowed writes |
| --- | --- | --- |
| `instagram_provider` | `munimjee-wave10-v08-semantics` / `codex/v1-v08-semantics-tests` | `backend/tests/test_v08_semantics_acceptance.py`, `docs/v1-v08-semantics-tests.md`, `artifacts/v1/v08-semantics/` |
| `instagram_contract_qa` | `munimjee-wave10-v08-context` / `codex/v1-v08-context-tests` | `backend/tests/test_v08_context_acceptance.py`, `docs/v1-v08-context-tests.md`, `artifacts/v1/v08-context/` |
| `instagram_security` | `munimjee-wave10-v08-review` / `codex/v1-v08-independent-review` | `docs/v1-v08-independent-review.md`, `artifacts/v1/v08-review/`; runtime and tests read-only |
| Root | `munimjee` / `codex/v1-v08-semantics-coordination` | This task, final handoff, `artifacts/v1/v08-semantics-coordination/`, reviewed test/docs composition |

The semantic lane targets meaningful gaps in English/Hindi/Hinglish product
price/size/stock questions, missing approved facts and buyer instructions that
attempt to override catalogue or system policy. The context lane targets
explicit reel switches, ambiguous/multiple references and stale source after
pause/reconnect. Existing coverage is credited rather than duplicated.

## Acceptance and evidence

Exercise actual parser, context and reply-assembly functions where practical.
Expected facts must be independently specified; injecting an expected answer is
not proof of application reasoning. Preserve exact approved SKU facts, unknown
availability and clarification/handoff. Safe handoff for unsupported language
or intent is recorded as such, not full multilingual answer quality.

Synthetic provider/LLM transport and raw repository rows may replace external
boundaries. Record each seam, which functions actually ran and which outputs
were injected. No fake repository is database persistence, isolation, locking,
SQL-predicate evaluation or restart proof. No real model/provider request,
credential access, outbound send, DB/server allocation, Docker, ambient4317,
release or production action. The existing pre-import test safety gate remains
mandatory. There is no remote mounted DB slot.

Hard gates within declared scenarios: no cross-tenant facts, invented
price/stock, unauthorized financial action or policy bypass. No arbitrary soft
quality score is introduced. Missing facts must remain unknown or hand off;
stale and ambiguous context cannot silently answer about an unrelated product.

Retain reproducible failures and push exact assertion/source evidence promptly
for the local runtime owner. Do not repair runtime or weaken assertions to make
the packet green. Independent review checks scope, safety, assertion validity
and exact hashes. Focused checks suffice; broader release, live-provider,
physical-device and mounted acceptance remain separate.

Root baseline: existing `test_sku_fact_replies.py`, `test_intent_classifier.py`
and `test_prompt_builders.py` pass44 checks, with one existing Pydantic
deprecation warning. Logs/XML are under the root-owned artifact directory.
Finite worker matrices and final results will be recorded in the handoff.
