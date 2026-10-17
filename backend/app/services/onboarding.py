"""Derived onboarding status: saved profile is never proof of provider readiness."""
from sqlalchemy import func, select
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.services.identity import require_business_access


def profile_view(business):
    return {"business_id": business.id, "name": business.name, "profile": business.profile,
            "version": business.profile_version, "confirmed": business.profile_confirmed_at is not None}


async def onboarding_view(db, actor, business_id, *, available_actions=frozenset()):
    access = await require_business_access(db, actor, business_id, "readiness.read")
    count = await db.scalar(select(func.count()).select_from(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id == business_id, CatalogueProductMapping.state == "reviewed"))
    sku_count = await db.scalar(select(func.count()).select_from(CatalogueSKU).where(
        CatalogueSKU.business_id == business_id, CatalogueSKU.active.is_(True)))
    # Catalogue facts require separate freshness/activation validation in B20.
    profile_ready = access.business.profile_confirmed_at is not None
    steps = [
        {"id": "identity", "label": "Account and access", "status": "ready", "reason": "Your active membership is confirmed.", "action_url": None},
        {"id": "business_profile", "label": "Business details", "status": "ready" if profile_ready else "action_required",
         "reason": "Business details saved." if profile_ready else "Confirm the boutique details used by your team.", "action_url": "#profile"},
        {"id": "catalogue", "label": "Reviewed catalogue", "status": "action_required",
         "reason": f"{count} reviewed product snapshots and {sku_count} active SKUs. Current allocation and activation must be checked." if count else "Add and review your products before activating selling.",
         "action_url": f"/v1/businesses/{business_id}/catalogue"},
        {"id": "channels", "label": "Instagram and WhatsApp", "status": "pending_external",
         "reason": "Connect owned accounts and complete an authorized messaging test. Provider approval is not inferred from saved credentials.", "action_url": f"/v1/businesses/{business_id}/channels"},
        {"id": "storefront", "label": "Storefront and checkout", "status": "action_required",
         "reason": "Configure the storefront, reconcile stock and enable checkout through the reviewed activation flow.", "action_url": f"/v1/businesses/{business_id}/catalogue"},
    ]
    for step in steps:
        if step["action_url"] and step["action_url"].startswith("/") and step["action_url"] not in available_actions:
            step["action_url"] = None
            step["action_unavailable_reason"] = "This workspace is not available in the current preview."
    return {"business_id": business_id, "onboarding_complete": False,
            "completed_steps": sum(step["status"] == "ready" for step in steps), "total_steps": len(steps),
            "steps": steps, "profile": profile_view(access.business)}
