"""LLM cost reporting — per-conversation and overall, plus a recompute hook
to backfill cost_usd after editing pricing.yaml."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import verify_dashboard_cookie, require_admin
from app.database import get_db
from app.integrations.llm_pricing import compute_cost_usd, reload_pricing
from app.models.llm_call_log import LLMCallLog

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/llm-costs",
    tags=["llm-costs"],
    dependencies=[Depends(require_admin)],
)


def _f(value) -> Optional[float]:
    return float(value) if value is not None else None


@router.get("/conversation/{conversation_id}")
async def conversation_cost(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Total + per-(method,model) breakdown + per-call list for one conversation."""
    totals = (
        await db.execute(
            select(
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.cache_read_input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.cache_creation_input_tokens), 0),
            ).where(LLMCallLog.conversation_id == conversation_id)
        )
    ).one()

    breakdown_rows = (
        await db.execute(
            select(
                LLMCallLog.method,
                LLMCallLog.provider,
                LLMCallLog.model,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
            )
            .where(LLMCallLog.conversation_id == conversation_id)
            .group_by(LLMCallLog.method, LLMCallLog.provider, LLMCallLog.model)
            .order_by(func.sum(LLMCallLog.cost_usd).desc().nullslast())
        )
    ).all()

    # Per-message breakdown: group by the triggering Instagram message id.
    by_message_rows = (
        await db.execute(
            select(
                LLMCallLog.customer_message_mid,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.min(LLMCallLog.created_at),
            )
            .where(LLMCallLog.conversation_id == conversation_id)
            .group_by(LLMCallLog.customer_message_mid)
            .order_by(func.min(LLMCallLog.created_at).asc())
        )
    ).all()

    calls = (
        await db.execute(
            select(
                LLMCallLog.id,
                LLMCallLog.created_at,
                LLMCallLog.method,
                LLMCallLog.provider,
                LLMCallLog.model,
                LLMCallLog.status,
                LLMCallLog.customer_message_mid,
                LLMCallLog.input_tokens,
                LLMCallLog.output_tokens,
                LLMCallLog.cache_read_input_tokens,
                LLMCallLog.cache_creation_input_tokens,
                LLMCallLog.cost_usd,
            )
            .where(LLMCallLog.conversation_id == conversation_id)
            .order_by(LLMCallLog.created_at.asc())
        )
    ).all()

    if totals[0] == 0:
        raise HTTPException(status_code=404, detail="No LLM calls for this conversation")

    return {
        "conversation_id": conversation_id,
        "totals": {
            "calls": totals[0],
            "cost_usd": _f(totals[1]),
            "input_tokens": int(totals[2]),
            "output_tokens": int(totals[3]),
            "cache_read_input_tokens": int(totals[4]),
            "cache_creation_input_tokens": int(totals[5]),
        },
        "breakdown": [
            {
                "method": r[0], "provider": r[1], "model": r[2],
                "calls": r[3], "cost_usd": _f(r[4]),
                "input_tokens": int(r[5]), "output_tokens": int(r[6]),
            }
            for r in breakdown_rows
        ],
        "by_message": [
            {
                "customer_message_mid": r[0],
                "calls": r[1], "cost_usd": _f(r[2]),
                "input_tokens": int(r[3]), "output_tokens": int(r[4]),
                "first_at": r[5].isoformat() if r[5] else None,
            }
            for r in by_message_rows
        ],
        "calls": [
            {
                "id": str(r[0]),
                "created_at": r[1].isoformat() if r[1] else None,
                "method": r[2], "provider": r[3], "model": r[4], "status": r[5],
                "customer_message_mid": r[6],
                "input_tokens": r[7], "output_tokens": r[8],
                "cache_read_input_tokens": r[9], "cache_creation_input_tokens": r[10],
                "cost_usd": _f(r[11]),
            }
            for r in calls
        ],
    }


@router.get("/summary")
async def cost_summary(db: AsyncSession = Depends(get_db)):
    """Overall totals + per-(provider,model) breakdown across all conversations."""
    totals = (
        await db.execute(
            select(
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
            )
        )
    ).one()

    by_model = (
        await db.execute(
            select(
                LLMCallLog.provider,
                LLMCallLog.model,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
            )
            .group_by(LLMCallLog.provider, LLMCallLog.model)
            .order_by(func.sum(LLMCallLog.cost_usd).desc().nullslast())
        )
    ).all()

    # How many priced rows are still NULL (model unpriced in pricing.yaml).
    unpriced = (
        await db.execute(
            select(LLMCallLog.model, func.count(LLMCallLog.id))
            .where(LLMCallLog.cost_usd.is_(None))
            .group_by(LLMCallLog.model)
        )
    ).all()

    return {
        "totals": {
            "calls": totals[0],
            "cost_usd": _f(totals[1]),
            "input_tokens": int(totals[2]),
            "output_tokens": int(totals[3]),
        },
        "by_model": [
            {
                "provider": r[0], "model": r[1], "calls": r[2],
                "cost_usd": _f(r[3]), "input_tokens": int(r[4]), "output_tokens": int(r[5]),
            }
            for r in by_model
        ],
        "unpriced_models": [{"model": r[0], "calls": r[1]} for r in unpriced],
    }


@router.get("/by-seller")
async def cost_by_seller(db: AsyncSession = Depends(get_db)):
    """Total spend grouped by seller (joined to the seller name)."""
    from app.models.seller import Seller

    rows = (
        await db.execute(
            select(
                LLMCallLog.seller_id,
                Seller.business_name,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.count(func.distinct(LLMCallLog.conversation_id)),
            )
            .outerjoin(Seller, Seller.id == LLMCallLog.seller_id)
            .group_by(LLMCallLog.seller_id, Seller.business_name)
            .order_by(func.sum(LLMCallLog.cost_usd).desc().nullslast())
        )
    ).all()

    return {
        "sellers": [
            {
                "seller_id": str(r[0]) if r[0] else None,
                "seller_name": r[1],
                "calls": r[2],
                "cost_usd": _f(r[3]),
                "input_tokens": int(r[4]),
                "output_tokens": int(r[5]),
                "conversations": r[6],
            }
            for r in rows
        ]
    }


@router.get("/by-conversation")
async def cost_by_conversation(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Conversations ranked by total LLM spend (most expensive first)."""
    limit = max(1, min(limit, 500))
    rows = (
        await db.execute(
            select(
                LLMCallLog.conversation_id,
                LLMCallLog.seller_id,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.max(LLMCallLog.created_at),
            )
            .where(LLMCallLog.conversation_id.isnot(None))
            .group_by(LLMCallLog.conversation_id, LLMCallLog.seller_id)
            .order_by(func.sum(LLMCallLog.cost_usd).desc().nullslast())
            .limit(limit)
        )
    ).all()

    return {
        "conversations": [
            {
                "conversation_id": str(r[0]),
                "seller_id": str(r[1]) if r[1] else None,
                "calls": r[2],
                "cost_usd": _f(r[3]),
                "input_tokens": int(r[4]),
                "output_tokens": int(r[5]),
                "last_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    }


@router.post("/recompute")
async def recompute_costs(db: AsyncSession = Depends(get_db)):
    """Re-read pricing.yaml and recompute cost_usd for every stored row.

    Use after editing pricing.yaml (e.g. adding Sarvam rates) so historical
    rows get their cost backfilled."""
    reload_pricing()
    rows = (
        await db.execute(
            select(
                LLMCallLog.id,
                LLMCallLog.model,
                LLMCallLog.input_tokens,
                LLMCallLog.output_tokens,
                LLMCallLog.cache_read_input_tokens,
                LLMCallLog.cache_creation_input_tokens,
            )
        )
    ).all()

    updated = 0
    for r in rows:
        cost = compute_cost_usd(r[1], r[2], r[3], r[4], r[5])
        obj = await db.get(LLMCallLog, r[0])
        if obj is not None and obj.cost_usd != cost:
            obj.cost_usd = cost
            updated += 1
    await db.commit()
    logger.info("Recomputed LLM costs: %d/%d rows updated", updated, len(rows))
    return {"status": "ok", "rows": len(rows), "updated": updated}
