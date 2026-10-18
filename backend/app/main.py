from app.paths import STATIC_DIR as _STATIC_DIR, UPLOAD_DIR as _UPLOAD_ROOT
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.webhooks.instagram import router as instagram_webhook_router
from app.api.routes.auth import router as auth_router
from app.api.dashboard_auth import (
    router as dashboard_auth_router,
    verify_dashboard_cookie,
    require_admin,
    DashCtx,
)
from app.api.routes.products import router as products_router
from app.api.routes.settings import router as settings_router
from app.api.routes.training import router as training_router
from app.api.routes.categories import router as categories_router
from app.api.routes.llm_costs import router as llm_costs_router
from app.api.routes.manual_actions import router as manual_actions_router
from app.api.routes.admin import router as admin_router
from app.api.routes.commerce import seller_router as commerce_router, public_router as shop_router
from app.api.routes.razorpay import router as razorpay_router
from app.api.routes.private_media import router as private_media_router, PublicUploads

from app.api.routes.whatsapp import router as whatsapp_router
from app.api.webhooks.whatsapp import router as whatsapp_webhook_router
from app.api.routes.comment_automation import router as comment_automation_router
from app.api.v1.identity import router as v1_identity_router
from app.api.v1.auth import router as v1_auth_router
from app.api.v1.catalogue import router as v1_catalogue_router
from app.api.v1.catalogue_workspace import router as v1_catalogue_workspace_router
from app.api.v1.channel_operator import router as v1_channel_router
from app.api.v1.imports import create_router as create_v1_import_router
from app.api.v1.import_catalogue import router as v1_import_catalogue_router
from app.api.v1.import_workspace import router as v1_import_workspace_router
from app.api.v1.theme_settings import router as v1_theme_settings_router
from app.api.v1.checkout_sessions import router as v1_checkout_sessions_router, configuration_router as v1_payment_configuration_router
from app.api.v1.parcel_tracking import router as v1_parcel_router
from app.api.v1.assistance import router as v1_assistance_router
from app.api.v1.support_grants import router as v1_support_grants_router
from app.api.v1.analytics_v1 import router as v1_analytics_router
from app.api.v1.payment_settings import router as v1_payment_settings_router
from app.api.v1.session import business_mutation
from app.api.v1.storefront_bootstrap import install_storefront

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SellerBot API",
    description="AI-powered Instagram seller automation — Hinglish negotiation + UPI verification",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files — uploaded product images + dashboard
upload_dir = _UPLOAD_ROOT
upload_dir.mkdir(parents=True, exist_ok=True)
app.include_router(private_media_router)
app.mount("/uploads", PublicUploads(directory=str(upload_dir)), name="uploads")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Phase 1 routes
app.include_router(instagram_webhook_router)
app.include_router(auth_router)
app.include_router(dashboard_auth_router)
app.include_router(products_router)
app.include_router(settings_router)
app.include_router(training_router)
app.include_router(categories_router)
app.include_router(llm_costs_router)
app.include_router(manual_actions_router)
app.include_router(admin_router)
app.include_router(commerce_router)
app.include_router(shop_router)
app.include_router(razorpay_router)
app.include_router(whatsapp_router)
app.include_router(whatsapp_webhook_router)
app.include_router(comment_automation_router)
app.include_router(v1_identity_router)
app.include_router(v1_auth_router)
app.include_router(v1_catalogue_router)
app.include_router(v1_catalogue_workspace_router)
app.include_router(v1_channel_router)
app.include_router(create_v1_import_router(business_mutation("catalogue.write")))
app.include_router(v1_import_catalogue_router)
app.include_router(v1_import_workspace_router)
app.include_router(v1_theme_settings_router)
app.include_router(v1_checkout_sessions_router)
app.include_router(v1_payment_configuration_router)
app.include_router(v1_parcel_router)
app.include_router(v1_assistance_router)
app.include_router(v1_support_grants_router)
app.include_router(v1_analytics_router)
app.include_router(v1_payment_settings_router)
install_storefront(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root():
    """Public root. Meta probes this when verifying App Domains; it sometimes
    uses HEAD, which FastAPI does NOT auto-register for GET routes. Without
    HEAD support Meta gets 405 and silently drops the App Domain on save.
    Serve onboarding.html directly so the same URL works for real sellers too."""
    return FileResponse(_STATIC_DIR / "onboarding.html")


@app.api_route("/privacy", methods=["GET", "HEAD"], include_in_schema=False)
async def privacy():
    """Use the operator's canonical policy instead of a second placeholder policy."""
    return RedirectResponse(url="https://munimjee.in/privacy", status_code=307)


@app.api_route("/data-deletion", methods=["GET", "HEAD"], include_in_schema=False)
async def data_deletion():
    return FileResponse(_STATIC_DIR / "data_deletion.html")


@app.api_route("/terms", methods=["GET", "HEAD"], include_in_schema=False)
async def terms():
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>SellerBot — Terms of Service</title>"
        "<style>body{font-family:system-ui;max-width:680px;margin:60px auto;padding:0 20px;line-height:1.6;color:#222}</style>"
        "<h1>Terms of Service</h1>"
        "<p>By connecting your Instagram account to SellerBot, you grant SellerBot permission to receive and reply to direct messages "
        "on your behalf using the configured persona, pricing, and policies. You retain full ownership of your Instagram account and may "
        "disconnect at any time from your Instagram account settings or the SellerBot dashboard.</p>"
        "<p>SellerBot is provided as-is. We do not guarantee specific sales outcomes. You are responsible for honoring deals the bot accepts on your behalf.</p>"
    )


@app.api_route("/onboarding", methods=["GET", "HEAD"], include_in_schema=False)
async def onboarding_page():
    """Self-serve seller signup + Instagram connect wizard. Public route."""
    return FileResponse(_STATIC_DIR / "onboarding.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/dashboard")
async def dashboard(ctx: DashCtx = Depends(verify_dashboard_cookie)):
    # An admin who hasn't picked a seller to view lands on the admin home.
    if ctx.role == "admin" and not ctx.view_seller_id:
        return RedirectResponse(url="/dashboard/admin", status_code=303)
    return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/dashboard/admin")
async def admin_dashboard(ctx: DashCtx = Depends(require_admin)):
    return FileResponse(_STATIC_DIR / "admin.html")


@app.get("/dashboard/products")
async def products_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "products.html")


@app.get("/dashboard/settings")
async def settings_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "settings.html")


@app.get("/dashboard/categories")
async def categories_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "categories.html")


@app.get("/dashboard/llm-costs")
async def llm_costs_dashboard(ctx: DashCtx = Depends(require_admin)):
    return FileResponse(_STATIC_DIR / "llm_costs.html")


@app.get("/dashboard/manual-actions")
async def manual_actions_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "manual_actions.html")


@app.get("/shop/{slug}", include_in_schema=False)
async def storefront_page(slug: str):
    return FileResponse(_STATIC_DIR / "storefront.html", headers={"Referrer-Policy": "no-referrer"})


@app.get("/dashboard/commerce", include_in_schema=False)
async def commerce_dashboard(ctx: DashCtx = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "commerce.html")


@app.get("/dashboard/social", include_in_schema=False)
async def social_dashboard(ctx: DashCtx = Depends(verify_dashboard_cookie)):
    return FileResponse(_STATIC_DIR / "social.html")


@app.get("/v1", include_in_schema=False)
async def v1_workspace():
    from app.api.v1.auth import enabled
    enabled()
    return FileResponse(_STATIC_DIR / "v1_app.html", headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def private_v1_cache_policy(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (path == "/v1" or path.startswith("/v1/businesses/") or path == "/api/v1/me"
            or path == "/api/v1/businesses" or path.startswith("/api/v1/businesses/")
            or path.startswith("/api/v1/auth/") or path == "/v1/support" or path.startswith("/api/v1/support/")):
        response.headers["Cache-Control"] = "no-store"
    return response
