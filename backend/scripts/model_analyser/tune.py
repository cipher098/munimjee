"""Replay golden conversations against the candidate agents.yaml, judge each
turn with opus-4.8, and auto-tune the prompts until every turn scores >= 9/10
(or N iterations).

Scope: decide + generate_reply are fully replayed/judged/tuned (they take a
structured `context`, so they are re-invokable under a tweaked prompt). Subagent
calls were captured for the golden record but are not yet auto-tuned — that
needs function-level structured-input capture (documented follow-up in
DESIGN.md).

On finish, accepted prompt rewrites are written back into app/prompts.py and
git-committed on the current branch (git = rollback).
"""
from __future__ import annotations

import json
import pathlib
import re
import string
import subprocess

from anthropic import AsyncAnthropic

from app.config import settings
from app.integrations.llm_provider import resolve_and_call

from .runtime import OPUS_MODEL, override_prompts
from .schema import GoldenConversation, TuneIteration, TurnScore

HERE = pathlib.Path(__file__).parent
GOLDEN_DIR = HERE / "golden"
REPORT = HERE / "tune_report.json"
PROMPTS_PY = pathlib.Path(__file__).parent.parent.parent / "app" / "prompts.py"

TUNABLE_METHODS = {"decide", "generate_reply"}
# method -> (prompt_store name, prompts.py constant) for write-back.
CONST_FOR_METHOD = {"decide": "DECISION_PROMPT", "generate_reply": "REPLY_PROMPT"}
PROMPT_NAME = {"decide": "decide", "generate_reply": "generate_reply"}


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

async def _replay(method: str, context: dict, prompts: dict[str, str]):
    """Run the candidate (agents.yaml) model/prompt on the same context. The
    in-memory `prompts` override supplies any tuned prompt; production prompts
    otherwise. NOT force_opus — this is the model we're trying to lift."""
    with override_prompts(prompts):
        return await resolve_and_call(method, None, context)


# ---------------------------------------------------------------------------
# judge (opus-4.8)
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are a strict evaluator of an Indian Instagram seller-bot. You are given, "
    "for one turn, the REFERENCE output (produced by a gold-standard model) and a "
    "CANDIDATE output (produced by a cheaper model). Score how well the candidate "
    "matches the reference in correctness and quality for this exact situation, "
    "1-10 (10 = as good as or better than reference; <9 = a meaningful gap). "
    "For 'decide' compare the chosen action/price/intent semantics; for "
    "'generate_reply' compare faithfulness, tone, Hinglish, and that no constraint "
    "is violated. Return ONLY JSON: {\"score\": <int 1-10>, \"rationale\": \"<one sentence>\"}."
)


async def _judge(client: AsyncAnthropic, method: str, context: dict,
                 golden, candidate) -> tuple[int, str]:
    user = (
        f"METHOD: {method}\n"
        f"CUSTOMER MESSAGE: {context.get('customer_message')!r}\n"
        f"REFERENCE OUTPUT:\n{json.dumps(golden, ensure_ascii=False, default=str)}\n\n"
        f"CANDIDATE OUTPUT:\n{json.dumps(candidate, ensure_ascii=False, default=str)}"
    )
    resp = await client.messages.create(
        model=OPUS_MODEL, max_tokens=200, system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group(0)) if m else {"score": 1, "rationale": "unparseable judge output"}
    return int(data.get("score", 1)), str(data.get("rationale", ""))


# ---------------------------------------------------------------------------
# tuner (opus-4.8)
# ---------------------------------------------------------------------------

_TUNER_SYSTEM = (
    "You improve a production prompt for a cheaper LLM so its outputs match a "
    "gold-standard model. You are given the CURRENT prompt and failing examples "
    "(situation, reference output, candidate output, why it fell short). Rewrite "
    "the prompt to close the gap.\n"
    "HARD RULES:\n"
    "- Preserve EVERY {placeholder} and {{escaped-brace}} exactly as-is.\n"
    "- BRACES: a single {name} is a format placeholder; any LITERAL brace in "
    "examples/JSON MUST be doubled ({{ and }}). Every { needs a matching }. Never "
    "emit an unbalanced or single literal brace — it breaks str.format.\n"
    "- Preserve all section markers verbatim (e.g. '--- CONTEXT ---', "
    "'--- NEGOTIATION STRATEGY (follow strictly) ---', '--- DYNAMIC CONTEXT ---').\n"
    "- Keep it a drop-in replacement: same inputs, same output format.\n"
    "Return ONLY the full rewritten prompt text — no commentary, no code fences."
)


async def _tune_prompt(client: AsyncAnthropic, name: str, current: str,
                       failures: list[dict]) -> str:
    ex = "\n\n".join(
        f"- situation: {f['situation']!r}\n  reference: {json.dumps(f['golden'], ensure_ascii=False, default=str)}\n"
        f"  candidate: {json.dumps(f['candidate'], ensure_ascii=False, default=str)}\n  gap: {f['rationale']}"
        for f in failures[:8]
    )
    resp = await client.messages.create(
        model=OPUS_MODEL, max_tokens=8000, system=_TUNER_SYSTEM,
        messages=[{"role": "user", "content":
                   f"PROMPT NAME: {name}\n\nCURRENT PROMPT:\n{current}\n\nFAILING EXAMPLES:\n{ex}"}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


# ---------------------------------------------------------------------------
# validation + write-back
# ---------------------------------------------------------------------------

_MARKERS = {
    "decide": ["--- CONTEXT ---", "--- NEGOTIATION STRATEGY"],
    "generate_reply": ["--- DYNAMIC CONTEXT ---"],
}


def _placeholders(text: str) -> set[str]:
    """The set of real {format} field names (ignores {{escaped}} braces)."""
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


async def _valid_prompt(method: str, new_text: str, original_text: str) -> bool:
    """A tuned prompt is valid only if it (a) still renders via the real builder,
    (b) keeps every {placeholder} the original had — a dropped one renders fine
    but silently loses dynamic data — and (c) preserves the section markers the
    splitters rely on."""
    try:
        new_placeholders = _placeholders(new_text)
    except ValueError as exc:
        # string.Formatter().parse raises on an unbalanced/single literal brace —
        # a malformed rewrite is rejected, not fatal to the run.
        print(f"    ✗ tuned {method} prompt rejected (malformed format braces: {exc})")
        return False
    missing = _placeholders(original_text) - new_placeholders
    if missing:
        print(f"    ✗ tuned {method} prompt rejected (dropped placeholders: {sorted(missing)})")
        return False
    if any(mk not in new_text for mk in _MARKERS.get(method, [])):
        print(f"    ✗ tuned {method} prompt rejected (missing section marker)")
        return False
    from app.bot.prompt_builders import build_decide_prompt, build_reply_prompt
    ctx = {
        "state": "negotiating", "customer_message": "x", "listed_price": 200000,
        "floor_price": 150000, "negotiation_round": 1, "message_history": [],
        "available_products": [{"id": "a", "name": "led clock"}], "other_inquiry_products": [],
        "bundle_pitched": False, "seller_channels": [], "product_variants": [],
        "active_variant_label": None, "decision": {"action": "counter", "price": 180000},
        "warranty_months": 6, "stock_quantity": 5, "policies": {}, "product_name": "Clock",
        "product_description": "x", "display_price_rupees": 2000, "customer_intent": "warm",
        "address_term": "madam", "total_photos": 1,
    }
    try:
        with override_prompts({PROMPT_NAME[method]: new_text}):
            if method == "decide":
                await build_decide_prompt(ctx)
            else:
                await build_reply_prompt(ctx)
        return True
    except Exception as exc:
        print(f"    ✗ tuned {method} prompt rejected (render failed: {exc})")
        return False


def _write_back(method: str, new_text: str) -> None:
    const = CONST_FOR_METHOD[method]
    src = PROMPTS_PY.read_text()
    # Replace the body of  NAME = """ ... """  (bodies contain no triple quotes).
    pattern = re.compile(rf'({const} = """).*?(""")', re.DOTALL)
    if not pattern.search(src):
        raise RuntimeError(f"could not locate {const} in {PROMPTS_PY}")
    new_src = pattern.sub(lambda m: m.group(1) + new_text + m.group(2), src, count=1)
    PROMPTS_PY.write_text(new_src)


def _git_commit(methods: list[str]) -> None:
    subprocess.run(["git", "add", str(PROMPTS_PY)], check=True, cwd=PROMPTS_PY.parent.parent.parent)
    subprocess.run(
        ["git", "commit", "-q", "-m",
         f"model-analyser: auto-tuned prompts ({', '.join(methods)}) to opus 9/10 parity"],
        check=True, cwd=PROMPTS_PY.parent.parent.parent,
    )


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

def _load_golden(approved_only: bool) -> list[GoldenConversation]:
    convs = []
    for p in sorted(GOLDEN_DIR.glob("conv_*.json")):
        gc = GoldenConversation.from_dict(json.loads(p.read_text()))
        if approved_only and not gc.approved:
            continue
        convs.append(gc)
    return convs


async def run(threshold: int = 9, max_iters: int = 5, approved_only: bool = False,
              commit: bool = True) -> None:
    convs = _load_golden(approved_only)
    if not convs:
        print("No golden conversations found (run `generate` first, "
              f"or drop --approved-only). Looked in {GOLDEN_DIR}/")
        return

    # Flatten the tunable (decide/reply) calls across all conversations.
    units = []  # (conv_id, turn_index, method, context, golden_output)
    for gc in convs:
        for turn in gc.turns:
            for call in turn.calls:
                if call.method in TUNABLE_METHODS and isinstance(call.context, dict):
                    units.append((gc.conv_id, turn.index, call.method, call.context, call.golden_output))
    print(f"Loaded {len(convs)} golden conversations, {len(units)} tunable turns "
          f"(threshold {threshold}/10, max {max_iters} iters).\n")

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    prompts: dict[str, str] = {}          # in-memory tuned overrides
    iterations: list[TuneIteration] = []
    tuned_methods: set[str] = set()

    for it in range(1, max_iters + 1):
        scores: list[TurnScore] = []
        fails_by_method: dict[str, list[dict]] = {}
        for (conv_id, turn_index, method, context, golden) in units:
            try:
                candidate = await _replay(method, context, prompts)
            except Exception as exc:
                candidate = {"_error": str(exc)}
            score, rationale = await _judge(client, method, context, golden, candidate)
            scores.append(TurnScore(conv_id, turn_index, method, score, rationale, candidate))
            if score < threshold:
                fails_by_method.setdefault(method, []).append({
                    "situation": context.get("customer_message"),
                    "golden": golden, "candidate": candidate, "rationale": rationale,
                })

        vals = [s.score for s in scores]
        below = sum(1 for v in vals if v < threshold)
        mean = round(sum(vals) / len(vals), 2) if vals else 0.0
        iterations.append(TuneIteration(
            iteration=it, min_score=min(vals) if vals else 0, mean_score=mean,
            n_below_threshold=below, scores=scores,
            prompt_edits={m: "rewritten" for m in fails_by_method},
        ))
        print(f"iter {it}: mean={mean} min={min(vals) if vals else 0} "
              f"below_{threshold}={below}/{len(vals)}")

        if below == 0:
            print("\n✓ All turns reached the threshold.")
            break
        if it == max_iters:
            print("\n• Max iterations reached.")
            break

        # Tune each prompt that produced failures (one retry on a rejected
        # rewrite — wholesale rewrites of the big prompts occasionally mangle a
        # brace, so give opus a second shot before keeping the baseline).
        from app.bot import prompt_store
        for method, fails in fails_by_method.items():
            name = PROMPT_NAME[method]
            current = prompts.get(name) or await prompt_store.get(name)
            baseline = await prompt_store.get(name)
            for attempt in range(2):
                new_text = await _tune_prompt(client, name, current, fails)
                if await _valid_prompt(method, new_text, baseline):
                    prompts[name] = new_text
                    tuned_methods.add(method)
                    print(f"    ↻ rewrote {method} prompt ({len(fails)} failing turns)")
                    break
            else:
                print(f"    – kept baseline {method} prompt (no valid rewrite in 2 tries)")

    # Persist accepted prompts → files + git commit.
    written = []
    for method in tuned_methods:
        name = PROMPT_NAME[method]
        if name in prompts:
            _write_back(method, prompts[name])
            written.append(method)
    if written:
        # compile-check before committing
        import py_compile
        try:
            py_compile.compile(str(PROMPTS_PY), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"✗ write-back produced invalid prompts.py ({exc}); NOT committing. "
                  "Review the file.")
        else:
            if commit:
                _git_commit(written)
                print(f"\n✓ Wrote + committed tuned prompts: {', '.join(written)}")
            else:
                print(f"\n✓ Wrote tuned prompts (not committed): {', '.join(written)}")

    REPORT.write_text(json.dumps(
        [{"iteration": i.iteration, "min": i.min_score, "mean": i.mean_score,
          "below": i.n_below_threshold,
          "scores": [vars(s) for s in i.scores]} for i in iterations],
        indent=2, ensure_ascii=False, default=str))
    print(f"Report → {REPORT}")
