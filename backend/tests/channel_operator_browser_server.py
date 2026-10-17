"""Loopback synthetic provider preview; never mount this fixture in production."""
from tests.safety import install_test_safety
install_test_safety()
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from cryptography.fernet import Fernet
import httpx
from fastapi import Depends
from sqlalchemy import select
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.PUBLIC_BASE_URL = "http://127.0.0.1:8145"
settings.META_WEBHOOK_SECRET = "synthetic-webhook"
settings.WHATSAPP_APP_SECRET = "synthetic-webhook"
settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "synthetic-verify"
settings.CHANNEL_ENCRYPTION_KEY = Fernet.generate_key().decode()
from app.main import app
from app.api.v1.channel_operator import router
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.channel_operator import ChannelConnectionState
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.identity import require_business_access
from app.workers.instagram_ingress import process_instagram_ingress
app.include_router(router)
process_instagram_ingress.apply_async = lambda **kwargs: None  # Browser proves durable queue, never sends.

_real_client = httpx.AsyncClient

def provider(request):
    if request.method != "GET":
        raise AssertionError("Synthetic preview forbids provider mutations and sends")
    if request.url.host == "graph.instagram.com" and request.url.path.endswith("/me"):
        return httpx.Response(200, json={"user_id":"1234567", "account_type":"BUSINESS"})
    if request.url.host == "graph.facebook.com":
        if request.url.path.endswith("/phone_numbers"):
            return httpx.Response(200, json={"data":[{"id":"7654321", "display_phone_number":"+91 00000 00000"}]})
        if request.url.path.endswith("/7654321"):
            return httpx.Response(200, json={"id":"7654321", "display_phone_number":"+91 00000 00000"})
    raise AssertionError("Unexpected synthetic provider request")

httpx.AsyncClient = lambda **kwargs: _real_client(transport=httpx.MockTransport(provider))

@app.post("/__test__/seed/{business_id}")
async def seed(business_id: str, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    from uuid import UUID
    bid = UUID(business_id)
    await require_business_access(db, actor, bid, "channels.connect")
    assert await db.scalar(select(InstagramIngress.id).where(InstagramIngress.seller_id == bid).limit(1)) is None
    seller = await db.get(Seller, bid)
    seller.instagram_page_id = seller.instagram_id = seller.fb_page_id = "1234567"
    seller.instagram_token = "synthetic-preview-token"
    db.add(ChannelConnectionState(business_id=bid,channel="instagram",automation_enabled=False,check_status="not_checked",provider_account_id="1234567"))
    current=datetime.now(timezone.utc)
    ids=[]
    for index in range(23):
        identifier=uuid4();ids.append(str(identifier))
        text = ["Is the indigo kurta still available in medium?", "Could you confirm the delivery address before I pay?", "Please check the price from yesterday’s message."][index % 3]
        db.add(InstagramIngress(id=identifier,seller_id=bid,account_id="1234567",customer_id=f"synthetic-{index:04}",
               event_key=uuid4().hex,provider_message_id=f"synthetic-preview-{index}",events=[{"type":"text","text":text}],processed_indices=[],
               status="error",error_code="processing_failed_unknown_effect",attempts=1,available_at=current,
               occurred_at=current-timedelta(days=2) if index==2 else current,
               created_at=current-timedelta(minutes=index)))
    return {"receipt_ids":ids}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8145, log_level="warning")
