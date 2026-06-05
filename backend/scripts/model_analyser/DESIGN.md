# Model Analyser — prompt/model optimization harness

Goal: drive a candidate model (whatever `agents.yaml` points to, e.g.
gemini-2.5-flash-lite) toward the quality of a gold-standard model
(**claude-opus-4-8**) on this bot, by auto-tuning the prompts until opus rates
every turn ≥ 9/10.

## Pipeline

### 1. `generate` — build 10 golden conversations
- Opus-4.8 **self-plays the customer**: given a persona + goal (`personas.yaml`)
  and the conversation so far, it produces the next customer message.
- The **bot** side runs the real pipeline with **every method routed to
  claude-opus-4-8** (`agents.opus.yaml`).
- A recording wrapper captures **every** LLM method call the bot makes for each
  turn — `decide`, `generate_reply`, and all subagents (`intent_classifier`,
  `extract_feature_query`, …) — as `{method, context_in, golden_output}`.
- Each conversation is saved to `golden/conv_NN.json`.

### 2. verify (manual)
You read/edit/approve the `golden/conv_NN.json` files. Only approved ones are
used for tuning.

### 3. `tune` — replay → score → auto-tune loop
For the candidate `agents.yaml` and the current (in-memory) prompt set:
1. **Replay (teacher-forced):** re-invoke the candidate model/prompt on each
   captured `context_in` — identical inputs to the golden run, so per-turn
   outputs are directly comparable (no trajectory drift).
2. **Score:** opus-4.8 judges each candidate output against the golden output,
   **per turn**, 1–10, with a rationale.
3. **Stop?** If every scored turn ≥ 9 → done. Else continue.
4. **Tune:** opus-4.8, shown the low-scoring turns (candidate out, golden out,
   judge rationale, current prompt), rewrites the offending prompt(s)
   (decide / reply / subagent). Applied to the in-memory prompt set.
5. Re-replay + re-score. Loop until all turns ≥ 9 **or** N iterations.
6. On accept/stop: write tuned prompts to `app/prompts.py` /
   `app/subagent_prompts.py` and **git-commit on this branch** (git is rollback).

## Key design decisions
- **Teacher-forcing** (re-invoke on saved context) — chosen because scoring is
  **per turn**; a free-running replay would diverge and make per-turn scores
  meaningless. ← confirm this is what you want.
- **Generator + judge + tuner** all = `claude-opus-4-8`.
- **Tune everything**: decide, generate_reply, and all subagent prompts.
- **Customer = opus self-play** from `personas.yaml`.
- Golden data + score reports persisted as **JSON files** here (eyeballable).
- Prompt tweaks go to the **real prompt files, committed on this branch**;
  the loop itself uses in-memory overrides via `prompt_store`'s cache so replay
  picks up tweaks without writing/reloading until accepted.
- A fixed **test seller + products** must be seeded so generate and replay share
  the same catalog/state the contexts reference.

## Layout
```
scripts/model_analyser/
  DESIGN.md          ← this file
  personas.yaml      ← customer personas/goals for self-play
  schema.py          ← golden-conversation / score dataclasses (JSON (de)serial.)
  runtime.py         ← force_opus() + override_prompts() context managers ✓
  recorder.py        ← provider wrapper capturing {context, output} ✓
  generate.py        ← self-play generation → golden/conv_NN.json ✓
  tune.py            ← replay + judge + tuner loop + prompt write-back ✓
  cli.py             ← `generate` / `tune` entrypoints ✓
  golden/            ← generated golden conversations (JSON)
```
Opus routing is done via a `force_opus()` monkeypatch of `agent_spec.get`
(keeps per-method max_tokens) — no separate agents.opus.yaml needed.

## Resolved decisions
- **Teacher-forcing**: yes (replay re-invokes the candidate on each saved context).
- **Customer**: opus-4.8 self-play (a) from `personas.yaml`.
- **Test seller**: existing `ac2303e0-…`; generation runs in a rolled-back txn
  (no DB pollution) with Instagram sends stubbed.
- **End condition**: stop on decide action `accept`/`not_interested`/
  `acknowledge_and_close`, conversation close, or 12 turns.
- **Tuning target**: opus rewrites prompts → written to `app/prompts.py` +
  git-committed on this branch; validated (renders, no dropped placeholders,
  markers intact) before write.

## Known scope limit (follow-up)
decide + generate_reply are fully replayed/judged/tuned (structured context →
re-invokable under a tweaked prompt). **Subagents** (intent_classifier,
extract_feature_query, …) are captured into the golden record but not yet
auto-tuned — that needs function-level structured-input capture so they can be
re-rendered with a tweaked prompt. The harness is structured to extend there.
