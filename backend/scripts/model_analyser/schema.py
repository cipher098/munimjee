"""Golden-conversation and scoring data model for the model analyser.

A golden conversation is NOT a free chat transcript — it is an ordered list of
the bot's LLM *method invocations* (decide / generate_reply / subagents), each
with the exact structured `context` that was fed in and opus-4.8's reference
output. Replay re-invokes the candidate model/prompt on the same `context` and
scores its output against `golden_output`, per turn. This teacher-forcing keeps
per-turn scores comparable (no trajectory drift).

All dataclasses are plain JSON-(de)serializable via `to_dict` / `from_dict`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MethodCall:
    """One captured LLM method invocation within a turn."""
    method: str               # decide | generate_reply | intent_classifier | extract_feature_query | ...
    context: dict             # exact structured input passed to the provider method
    golden_output: Any        # opus-4.8 reference output (dict for decide, str for reply, …)
    golden_model: str = "claude-opus-4-8"


@dataclass
class GoldenTurn:
    """A single customer turn and every bot method call it triggered."""
    index: int
    customer_message: str
    calls: list[MethodCall] = field(default_factory=list)


@dataclass
class GoldenConversation:
    """One self-played reference conversation (10 of these per run)."""
    conv_id: str
    persona: dict                      # from personas.yaml (id, goal, style, product)
    seller_id: str
    product_ids: list[str] = field(default_factory=list)
    turns: list[GoldenTurn] = field(default_factory=list)
    approved: bool = False             # flipped to true after manual verify

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GoldenConversation":
        turns = [
            GoldenTurn(
                index=t["index"],
                customer_message=t["customer_message"],
                calls=[MethodCall(**c) for c in t.get("calls", [])],
            )
            for t in d.get("turns", [])
        ]
        return cls(
            conv_id=d["conv_id"], persona=d.get("persona", {}),
            seller_id=d["seller_id"], product_ids=d.get("product_ids", []),
            turns=turns, approved=d.get("approved", False),
        )


@dataclass
class TurnScore:
    """opus-4.8's judgement of one replayed method call vs its golden output."""
    conv_id: str
    turn_index: int
    method: str
    score: int                # 1..10
    rationale: str
    candidate_output: Any = None


@dataclass
class TuneIteration:
    """One pass of the replay → score → tune loop, for the report."""
    iteration: int
    min_score: int
    mean_score: float
    n_below_threshold: int
    scores: list[TurnScore] = field(default_factory=list)
    prompt_edits: dict = field(default_factory=dict)   # {prompt_name: new_content} applied this iter
