"""Test-run a candidate model against the golden set (replay + judge, NO tuning)
and save a run artifact the UI can visualize.

Each run records, per turn, the golden output, the candidate output, opus-4.8's
score (1-10) and rationale — so the dashboard can show golden vs candidate
side-by-side for any model we trial.
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import re

from anthropic import AsyncAnthropic

from app.config import settings

from .runtime import force_model
from .tune import TUNABLE_METHODS, _judge, _load_golden, _replay

HERE = pathlib.Path(__file__).parent
RUNS_DIR = HERE / "runs"


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", s).strip("_")


async def run(label: str | None = None, model: str | None = None,
              provider: str | None = None, threshold: int = 9,
              approved_only: bool = False) -> None:
    convs = _load_golden(approved_only)
    if not convs:
        print(f"No golden conversations found in {HERE / 'golden'}/ "
              "(run `generate` first, or drop --approved-only).")
        return

    label = label or model or "candidate"
    RUNS_DIR.mkdir(exist_ok=True)
    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    ctx = force_model(model, provider) if model else contextlib.nullcontext()

    conversations = []
    all_scores: list[int] = []
    print(f"Test run '{label}' ({model or 'agents.yaml candidate'}) over "
          f"{len(convs)} golden conversations…")
    with ctx:
        for gc in convs:
            turns_out = []
            for turn in gc.turns:
                for call in turn.calls:
                    if call.method not in TUNABLE_METHODS or not isinstance(call.context, dict):
                        continue
                    try:
                        candidate = await _replay(call.method, call.context, {})
                    except Exception as exc:
                        candidate = {"_error": str(exc)}
                    score, rationale = await _judge(
                        client, call.method, call.context, call.golden_output, candidate)
                    all_scores.append(score)
                    turns_out.append({
                        "turn_index": turn.index,
                        "method": call.method,
                        "customer_message": call.context.get("customer_message"),
                        "golden": call.golden_output,
                        "candidate": candidate,
                        "score": score,
                        "rationale": rationale,
                    })
            conversations.append({"conv_id": gc.conv_id, "persona": gc.persona, "turns": turns_out})
            cscores = [t["score"] for t in turns_out]
            print(f"  {gc.conv_id:<18} {len(turns_out):>2} turns  "
                  f"mean={round(sum(cscores)/len(cscores),2) if cscores else 0}")

    summary = {
        "n_turns": len(all_scores),
        "mean": round(sum(all_scores) / len(all_scores), 2) if all_scores else 0,
        "min": min(all_scores) if all_scores else 0,
        "n_below_threshold": sum(1 for s in all_scores if s < threshold),
        "threshold": threshold,
    }
    artifact = {
        "label": label,
        "model": model or "agents.yaml candidate",
        "provider": provider,
        "summary": summary,
        "conversations": conversations,
    }
    out = RUNS_DIR / f"{_slug(label)}.json"
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str))
    print(f"\nmean={summary['mean']} min={summary['min']} "
          f"below_{threshold}={summary['n_below_threshold']}/{summary['n_turns']} → {out}")
