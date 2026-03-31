import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.webhooks.instagram import router as instagram_webhook_router
from app.api.routes.auth import router as auth_router

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

# Phase 1 routes
app.include_router(instagram_webhook_router)
app.include_router(auth_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
