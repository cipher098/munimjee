import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.webhooks.instagram import router as instagram_webhook_router
from app.api.routes.auth import router as auth_router
from app.api.dashboard_auth import router as dashboard_auth_router, verify_dashboard_cookie
from app.api.routes.products import router as products_router
from app.api.routes.settings import router as settings_router
from app.api.routes.training import router as training_router
from app.api.routes.categories import router as categories_router

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
upload_dir = Path("/app/uploads")
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# Phase 1 routes
app.include_router(instagram_webhook_router)
app.include_router(auth_router)
app.include_router(dashboard_auth_router)
app.include_router(products_router)
app.include_router(settings_router)
app.include_router(training_router)
app.include_router(categories_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    """Public root. Meta hits this when verifying App Domains and rejects the
    save if the response isn't 200 — even 302 fails the validator. Serve the
    onboarding page directly so the same URL works for both Meta's crawler and
    real sellers landing on the bare domain."""
    return FileResponse("/app/static/onboarding.html")


@app.get("/privacy", include_in_schema=False)
async def privacy():
    """Placeholder privacy policy URL — Meta requires one configured on the App,
    and the page must respond 200 when Meta crawls it."""
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>SellerBot — Privacy Policy</title>"
        "<style>body{font-family:system-ui;max-width:680px;margin:60px auto;padding:0 20px;line-height:1.6;color:#222}</style>"
        "<h1>Privacy Policy</h1>"
        "<p>SellerBot processes Instagram direct messages on behalf of sellers who have explicitly connected their Instagram account. "
        "We store conversation history, customer Instagram IDs, and seller-configured product/pricing data in our database to operate the negotiation bot. "
        "We do not sell or share this data with third parties. Sellers can request deletion of their account and all associated data at any time by emailing support.</p>"
        "<h2>Data we collect</h2>"
        "<ul>"
        "<li>Instagram user IDs of customers who message a connected seller account</li>"
        "<li>Direct message content (text + image URLs) needed to generate replies</li>"
        "<li>Seller-provided product catalog, pricing, persona, and policies</li>"
        "</ul>"
        "<h2>Data we share</h2>"
        "<p>Message content is sent to Anthropic's Claude API for natural-language response generation. Anthropic's privacy terms apply to that processing.</p>"
        "<h2>Contact</h2>"
        "<p>For data deletion or privacy questions, contact the seller administrator.</p>"
    )


@app.get("/terms", include_in_schema=False)
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


@app.get("/onboarding", include_in_schema=False)
async def onboarding_page():
    """Self-serve seller signup + Instagram connect wizard. Public route."""
    return FileResponse("/app/static/onboarding.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/dashboard")
async def dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse("/app/static/dashboard.html")


@app.get("/dashboard/products")
async def products_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse("/app/static/products.html")


@app.get("/dashboard/settings")
async def settings_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse("/app/static/settings.html")


@app.get("/dashboard/categories")
async def categories_dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse("/app/static/categories.html")
