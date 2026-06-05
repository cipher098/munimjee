"""Model analyser CLI.

    python -m scripts.model_analyser.cli generate [--n N] [--max-turns 12]
    python -m scripts.model_analyser.cli tune [--threshold 9] [--max-iters 5]
                                              [--approved-only] [--no-commit]

`generate` builds golden conversations via opus-4.8 self-play; `tune` replays
them against the candidate agents.yaml, scores each turn with opus-4.8, and
auto-tunes prompts until every turn >= threshold (or max iters).
"""
from __future__ import annotations

import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(prog="model_analyser")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="opus-4.8 self-play -> golden/conv_*.json")
    g.add_argument("--n", type=int, default=None, help="only the first N personas")
    g.add_argument("--max-turns", type=int, default=12)

    t = sub.add_parser("tune", help="replay + judge + auto-tune until >= threshold")
    t.add_argument("--threshold", type=int, default=9)
    t.add_argument("--max-iters", type=int, default=5)
    t.add_argument("--approved-only", action="store_true",
                   help="use only golden conversations with approved=true")
    t.add_argument("--no-commit", action="store_true",
                   help="write tuned prompts but do not git-commit")

    r = sub.add_parser("test", help="replay+judge a candidate model -> runs/<label>.json (no tuning)")
    r.add_argument("--label", default=None, help="name for this run (defaults to model)")
    r.add_argument("--model", default=None, help="candidate model id (default: agents.yaml)")
    r.add_argument("--provider", default=None, help="candidate provider (with --model)")
    r.add_argument("--threshold", type=int, default=9)
    r.add_argument("--approved-only", action="store_true")

    args = parser.parse_args()
    if args.cmd == "generate":
        from . import generate
        asyncio.run(generate.run(n=args.n, max_turns=args.max_turns))
    elif args.cmd == "tune":
        from . import tune
        asyncio.run(tune.run(
            threshold=args.threshold, max_iters=args.max_iters,
            approved_only=args.approved_only, commit=not args.no_commit,
        ))
    elif args.cmd == "test":
        from . import test
        asyncio.run(test.run(
            label=args.label, model=args.model, provider=args.provider,
            threshold=args.threshold, approved_only=args.approved_only,
        ))


if __name__ == "__main__":
    main()
