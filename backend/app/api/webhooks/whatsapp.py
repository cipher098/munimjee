"""Cloud API webhook: fail closed and commit inbox/outbox before acknowledging."""
import hashlib
import hmac
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.services.whatsapp import ingest

router = APIRouter(prefix='/webhooks/whatsapp',tags=['whatsapp-webhook'])


@router.get('')
async def verify(request:Request):
    token = getattr(settings,'WHATSAPP_WEBHOOK_VERIFY_TOKEN','')
    supplied = request.query_params.get('hub.verify_token','')
    challenge = request.query_params.get('hub.challenge','')
    if not token:
        raise HTTPException(503,'WhatsApp webhook verification is not configured')
    if request.query_params.get('hub.mode') != 'subscribe' or not hmac.compare_digest(token.encode(),supplied.encode()) or not challenge:
        raise HTTPException(403,'Invalid webhook verification')
    return PlainTextResponse(challenge)


@router.post('')
async def receive(request:Request,db:AsyncSession=Depends(get_db)):
    secret = getattr(settings,'WHATSAPP_APP_SECRET','')
    if not secret:
        raise HTTPException(503,'WhatsApp webhook signatures are not configured')
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413,'Webhook payload too large')
    signature = request.headers.get('x-hub-signature-256','')
    expected = 'sha256=' + hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(),signature.encode()):
        raise HTTPException(403,'Invalid webhook signature')
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400,'Invalid JSON')
    if not isinstance(payload,dict):
        raise HTTPException(400,'Invalid webhook payload')
    await ingest(db,payload)
    await db.commit()
    return {'status':'ok'}
