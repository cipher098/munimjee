# Mono → Sellerbot: agent-harnessing pattern adoption

Reference doc cataloging which patterns from `~/mono` (Emergent monorepo:
cortex / emergent / harness / eval-app) have been pulled into sellerbot,
which remain as gaps, and rough priority for closing them.

Generated 2026-06-03. Re-verify file paths before relying on a specific
ref — both repos move.

---

## 1. Adopted patterns

| Pattern | Mono source | Sellerbot location | Status |
|---|---|---|---|
| **Agent spec as YAML** (model, max_tokens, fallback, thinking config per method) | `cortex/resources/.../agents.yaml`, `cortex/resources/testing/agents.yaml` | `backend/app/agents.yaml` + `backend/app/bot/agent_spec.py` | Full |
| **Two-stage prompt split** — static cacheable rules / dynamic per-call context | `emergent/agents/core/llm.py:77-200` | `_split_decision_prompt`, `_split_reply_prompt` in `backend/app/integrations/claude.py:127-153` | Full |
| **Anthropic prompt caching with `cache_control: ephemeral`** | `emergent/agents/core/llm.py` (CACHE_PROMPT_SUPPORTED_MODELS gate) | `backend/app/integrations/claude.py:268` system message; cache hit/miss logged | Full |
| **DB-backed prompt store with module-constant fallback** | mono prompt registry | `backend/app/bot/prompt_store.py` — 60s TTL cache, falls back to `app/prompts.py` constants | Full |
| **Parallel intent classifier** (cheap haiku call, structured output) | `emergent/agents/service/intent_classifier_v3.py` | `backend/app/bot/intent_classifier.py` launched via `asyncio.create_task` in `responder.py:65-68`; returns `Classification` dataclass with sentiment / intent_label / confidence | Full |
| **YAML-declared intervention rules → `<system_reminder>` injection** | `cortex/resources/intervention_rules.yaml` | `backend/app/intervention_rules.yaml` + `backend/app/bot/interventions.py`. Simpler than mono (no template expansion, no `min_turn_gap`) but same shape. | Full |
| **VCR cassette scenario harness** | `cortex/AGENTS.md:295-330` (`agentlooptest.VCRRecorder`, `testdata/fixtures/`) | `backend/tests/conftest_db.py:135-150` `scenario_cassette` fixture, `backend/tests/test_scenarios.py` runner, cassettes under `backend/tests/cassettes/scenarios/<id>/`. Record with `VCR_RECORD=1`. | Full |
| **Constructor DI of service clients** | cortex Workflow struct takes agentService / llmProxySvc / envCoreSvc | `responder.py` instantiates `ClaudeClient()`, `SarvamClient()` inline; tests monkeypatch in `conftest_db.py:125-132` | Partial — works, just not idiomatic |

---

## 2. Gaps (NOT adopted), prioritized

### High value if/when traffic grows

1. **Message-history compaction / summarization.** Mono declares
   `context.management.strategy: squash` with token-percentage thresholds in
   agents.yaml (e.g. compact at 60%, fork at 90%); summarizer is a named
   agent (`use: summarizer@1`). Sellerbot just caps at `[-200]` raw turns in
   `_build_decision_messages` (`claude.py:48-107`) and never summarizes.
   Long negotiations (50+ turns) risk prompt bloat → cache misses and cost
   spikes. **Cheap to add:** when conversation.messages exceeds N tokens,
   call a haiku summarizer agent to fold the oldest M turns into a single
   system-level digest stored alongside the conversation.

2. **Structured output validation / guardrails.** Mono has YAML-declared
   input + output guardrails (regex, LLM safety checks, function
   entrypoint hooks). Sellerbot's `_parse_json` (`claude.py:156-168`)
   strips code fences and extracts the first `{...}` block, then trusts
   it. On a refusal or malformed JSON the decision becomes the fallback
   action, which can drop correct intent. **Cheap insurance:** validate
   decision dict against an expected schema (Pydantic model) and re-prompt
   once on schema mismatch before falling back.

### Medium value, only if business need shows up

3. **A/B testing / per-seller experiments.** Mono routes config through
   `pkg/experiments` (`ExperimentContext`, `get_openfeature_resolver`) so
   per-user model/prompt/strategy overrides are first-class. Sellerbot has
   no feature flag or per-seller override layer. Worth building if you ever
   want to A/B-test personas, models, or pricing strategies across seller
   cohorts.

4. **Per-method latency + error metrics.** Mono uses `@log_latency` and a
   Metrics recorder interface. Sellerbot logs cache hits only — no
   per-method (decide / reply / intent / classify_image) timing or error
   rate export. Add Prometheus / OTLP when you start caring about p99
   latency or failure SLOs.

### Low value at current scale

5. **Prompt template versioning leveraged.** `Prompt.version` is incremented
   on upsert in `prompt_store.py` but never queried for rollback or A/B
   comparisons. Hooks exist; no caller uses them. Worth wiring only when
   running prompt experiments.

6. **Tool-use loop / subagent handoff.** Mono spawns subagents via
   `action: handoff` (e.g. `handoff: analyst@1`) with their own model and
   policy. Sellerbot keeps it as sequential helper calls
   (feature_query, intent_classifier, catalog_match). Fine for 5-10 turn
   IG DM flows; would matter only if multi-step planning becomes a
   requirement.

---

## 3. Read

For an IG DM negotiation bot with short (5-10 turn) conversations,
sellerbot has hit the right level of mono-pattern adoption. The shortlist
of work that's actually worth queuing:

1. **Message summarization** — prevents a real future failure mode (long
   conversations bloating prompts and busting cache).
2. **Schema-validated decision output + one re-prompt on failure** — cheap
   robustness against Claude refusals.

Everything else stays in this doc as a "consider when traffic justifies"
backlog rather than active work.

---

## Quick refs

- Mono root: `/Users/gothi/mono/`
- Sellerbot root: `/Users/gothi/sellerbot/backend/`
- This doc generated from a side-by-side scan of both trees; spot-check
  paths before quoting in code reviews.
