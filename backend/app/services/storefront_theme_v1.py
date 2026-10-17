"""Persistent tenant-scoped theme settings; design publication has no commerce effects."""
from datetime import datetime, timezone
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.models.identity import Business
from app.models.storefront_theme_v1 import StorefrontThemeCommand, StorefrontThemeSettings
from app.schemas.storefront_theme_v1 import ThemeConfig
from app.services.identity import require_business_access


async def authorize(db, actor, business_id, *, write=False):
    if actor.auth_method != "v1_user":
        raise HTTPException(403, "Sign in with your own V1 account to manage storefront design")
    return await require_business_access(db, actor, business_id, "business.write" if write else "catalogue.read")


def view(row):
    return {"version": row.version if row else 0,
        "draft": ThemeConfig.model_validate(row.draft_config).model_dump() if row else ThemeConfig().model_dump(),
        "published": ThemeConfig.model_validate(row.published_config).model_dump() if row and row.published_config is not None else None,
        "published_revision": row.published_revision if row else 0,
        "published_at": row.published_at.isoformat() if row and row.published_at else None}


async def read_settings(db, actor, business_id):
    await authorize(db, actor, business_id)
    row = await db.scalar(select(StorefrontThemeSettings).where(StorefrontThemeSettings.business_id == business_id)
        .execution_options(populate_existing=True))
    return view(row)


async def published_theme(db, business_id):
    """Public provider hook: only the published allowlist; never returns draft state.

    The caller must separately enforce Storefront.published, tenant activity,
    activated SKU visibility and checkout authority. No row means catalogue.
    """
    config = await db.scalar(select(StorefrontThemeSettings.published_config).where(
        StorefrontThemeSettings.business_id == business_id))
    return ThemeConfig.model_validate(config).model_dump() if config is not None else ThemeConfig().model_dump()


async def apply_command(db, actor, business_id, body, operation):
    if operation not in {"save", "publish"}:
        raise ValueError("Unsupported theme command")
    await authorize(db, actor, business_id, write=True)
    # The Business row exists even before first design save. It serializes first
    # insert and later writes without an ORM get/create race or global lock.
    await db.scalar(select(Business.id).where(Business.id == business_id).with_for_update())
    # Recheck current role/activity after waiting for a concurrent writer.
    await authorize(db, actor, business_id, write=True)
    fingerprint = sha256(json.dumps({"operation": operation, "body": body.model_dump(mode="json")},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = await db.get(StorefrontThemeCommand, (business_id, body.idempotency_key), populate_existing=True)
    if receipt:
        if receipt.request_hash != fingerprint or receipt.actor_id != actor.user_id:
            raise HTTPException(409, "This design command key was already used; reload the saved design")
        return receipt.result
    row = await db.get(StorefrontThemeSettings, business_id, populate_existing=True)
    version = row.version if row else 0
    if body.expected_version != version:
        raise HTTPException(409, "The design changed in another window. Reload the saved design before editing")
    if version >= 2_000_000_000:
        raise HTTPException(409, "Design version limit reached; contact support")
    if operation == "save":
        if row is None:
            row = StorefrontThemeSettings(business_id=business_id, version=0,
                draft_config=body.config.model_dump(), published_revision=0, updated_by=actor.user_id)
            db.add(row)
        row.draft_config = body.config.model_dump()
    elif row is None:
        raise HTTPException(409, "Save a design draft before publishing")
    else:
        row.published_config = ThemeConfig.model_validate(row.draft_config).model_dump()
        row.published_revision = version + 1
        row.published_at = datetime.now(timezone.utc)
    row.version = version + 1
    row.updated_by = actor.user_id
    await db.flush()
    result = view(row)
    db.add(StorefrontThemeCommand(business_id=business_id, idempotency_key=body.idempotency_key,
        operation=operation, request_hash=fingerprint, result=result, actor_id=actor.user_id))
    await db.flush()
    return result
