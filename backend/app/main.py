import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.webhooks.instagram import router as instagram_webhook_router
from app.api.routes.auth import router as auth_router
from app.api.dashboard_auth import router as dashboard_auth_router, verify_dashboard_cookie
from app.api.routes.products import router as products_router
from app.api.routes.training import router as training_router

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
app.include_router(training_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/dashboard")
async def dashboard(phone: str = Depends(verify_dashboard_cookie)):
    return FileResponse("/app/static/dashboard.html")
