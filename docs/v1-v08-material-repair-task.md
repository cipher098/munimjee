# V08 missing-material repair contract

18 October 2026. Exact base `e7edea1613b9902c726ce571e3d16c169c8cf190`
contains application source `d4026b1` and the independently reviewed21-case V08
packet. The accepted red is missing approved material receiving a generic
catalogue summary without material-specific uncertainty or handoff.

## Approved runtime seam

Only `backend/app/services/sku_fact_replies.py` is transferred for the fix.
Approved minimal change: remove `material`/`materials` from both `_FACT_WORDS`
and `factual_request`'s requested categories. This rejects material intent
generally, including requests mixed with otherwise supported price/size/stock,
through the existing human handoff. It does not assert material is unavailable,
infer garment facts or introduce a language/model capability.

`read_facts`, `render`, `HANDOFF`, public fact schemas, current price/stock
semantics and both existing callers remain unchanged. No edit to
`whatsapp_context.py` is needed. Any caller seam change must be reported before
editing because local ingress/outbox activity ownership remains elsewhere.
No sender, schema, provider, authentication or other runtime ownership is granted.

## Workers and exclusive writes

Reuse existing named GPT-6.1 Sol/high workers, each from the exact base.

| Worker | Worktree / branch | Allowed writes |
| --- | --- | --- |
| `instagram_provider` | `munimjee-wave11-v08-material` / `codex/v1-v08-material-repair` | Only approved runtime file; `docs/v1-v08-material-repair.md`, `artifacts/v1/v08-material-repair/` |
| `instagram_contract_qa` | `munimjee-wave11-v08-material-qa` / `codex/v1-v08-material-qa` | `backend/tests/test_v08_material_reply_regression.py`, `docs/v1-v08-material-qa.md`, `artifacts/v1/v08-material-qa/`; runtime read-only except reviewed composition |
| `instagram_security` | `munimjee-wave11-v08-material-review` / `codex/v1-v08-material-review` | `docs/v1-v08-material-review.md`, `artifacts/v1/v08-material-review/`; runtime and tests read-only |
| Root | `munimjee` / `codex/v1-v08-material-coordination` | This task, final handoff, `artifacts/v1/v08-material-coordination/`, reviewed composition |

QA first proposes a finite matrix grounded in the supported vocabulary. Material
singular/plural and mixed questions must hand off; ordinary supported and mixed
price/size/stock requests retain exact independent approved facts. Existing21
assertions and prior red artifacts are byte-preserved. Unsupported Devanagari
questions remain safe handoff, not answered Hindi questions. No arbitrary answer
quality score or scope expansion.

## Verification and limits

Exercise real parser/context/reply assembly with strict scripted raw projections,
independent literal expected facts and unchanged pre-import safety policy. No
classifier, decision, renderer or model answer injection. Credit previous
coverage rather than duplicating all scenarios. Run focused regression against
the exact candidate, independently review source/test/evidence hashes, preserve
historical red results and push clean checkpoints.

Remote evidence is deterministic source/synthetic-row proof only. No SQL
predicate, current approval, persistence, send-time policy, DB/mounted,
reconnect, provider or live-model acceptance is inferred. Local integrated
migrated/mounted validation follows. No DB/server allocation, external
provider/model call, credential access, customer send, Docker, ambient4317,
production or release action is part of this task.
