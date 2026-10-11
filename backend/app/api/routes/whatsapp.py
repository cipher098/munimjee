"""Authenticated WhatsApp account, inbox, consent and automation configuration."""
from uuid import UUID
from typing import Literal
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dashboard_auth import current_seller_id
from app.config import settings
from app.database import get_db
from app.models.product import Product
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services.channel_credentials import cipher, encrypt, decrypt
from app.services import whatsapp as service, whatsapp_provider as provider

router = APIRouter(prefix='/whatsapp', tags=['whatsapp'])


class Connect(BaseModel):
    phone_number_id: str = Field(pattern=r'^\d{1,40}$')
    waba_id: str = Field(pattern=r'^\d{1,40}$')
    access_token: str | None = Field(default=None, max_length=4096)


class Rule(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    reply: str = Field(min_length=1, max_length=3500)
    product_id: UUID | None = None

    @field_validator('keyword', 'reply')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Cannot be blank')
        return value.strip()


class TemplateRef(BaseModel):
    name: str = Field(pattern=r'^[a-z0-9_]{1,512}$')
    language: str = Field(pattern=r'^[A-Za-z_]{2,30}$')


class AccountPatch(BaseModel):
    enabled: bool | None = None
    automation_enabled: bool | None = None
    welcome_message: str | None = Field(default=None, max_length=3500)
    rules: list[Rule] | None = Field(default=None, max_length=50)
    order_templates: dict[str, TemplateRef] | None = None


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    idempotency_key: UUID

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()


class TemplateSend(TemplateRef):
    parameters: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: UUID

    @field_validator('parameters')
    @classmethod
    def parameter_size(cls, values):
        if any(not value.strip() or len(value) > 1024 for value in values):
            raise ValueError('Template parameters must contain 1 to 1024 characters')
        return values


class Consent(BaseModel):
    utility_opt_in: bool
    marketing_opt_in: bool
    source: str = Field(min_length=5, max_length=500)


class TemplateCreate(BaseModel):
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,511}$')
    language: str = Field(pattern=r'^[a-z]{2,3}(?:_[A-Z]{2})?$')
    category: Literal['UTILITY', 'MARKETING']
    body: str = Field(min_length=1, max_length=1024)
    examples: list[str] = Field(default_factory=list, max_length=20)
    footer: str = Field(default='', max_length=60)

    @model_validator(mode='after')
    def validate_content(self):
        self.body, self.footer = self.body.strip(), self.footer.strip()
        if not self.body:
            raise ValueError('Message body cannot be blank')
        tokens = re.findall(r'\{\{([1-9][0-9]*)\}\}', self.body)
        remainder = re.sub(r'\{\{[1-9][0-9]*\}\}', '', self.body)
        if '{' in remainder or '}' in remainder or '{' in self.footer or '}' in self.footer:
            raise ValueError('Use numbered body variables such as {{1}}; footers cannot contain variables')
        numbers = sorted({int(token) for token in tokens})
        if numbers != list(range(1, len(numbers) + 1)) or len(numbers) != len(self.examples):
            raise ValueError('Variables must start at {{1}}, have no gaps, and have one sample per variable')
        if any(not sample.strip() or len(sample) > 1024 or '{' in sample or '}' in sample for sample in self.examples):
            raise ValueError('Each sample must be plain text between 1 and 1024 characters')
        self.examples = [sample.strip() for sample in self.examples]
        return self

    def components(self):
        body = {'type': 'BODY', 'text': self.body}
        if self.examples:
            body['example'] = {'body_text': [self.examples]}
        return [body] + ([{'type': 'FOOTER', 'text': self.footer}] if self.footer else [])


def template_json(template):
    return {key:getattr(template,key) for key in ('name','language','status','category','components','synced_at')}


def account_json(account):
    try:
        cipher()
        ready = True
    except HTTPException:
        ready = False
    base = getattr(settings, 'PUBLIC_BASE_URL', '').rstrip('/')
    data = {'configured':bool(account and account.access_token), 'encryption_ready':ready, 'webhook_ready':bool(getattr(settings,'WHATSAPP_APP_SECRET','') and getattr(settings,'WHATSAPP_WEBHOOK_VERIFY_TOKEN','')), 'webhook_url':base + '/webhooks/whatsapp', 'enabled':False, 'automation_enabled':False, 'welcome_message':'', 'rules':[], 'order_templates':{}}
    if account:
        data.update({key:getattr(account,key) for key in ('phone_number_id','waba_id','display_phone_number','enabled','automation_enabled','welcome_message','rules','order_templates')})
    return data


def message_json(message):
    return {key:getattr(message,key) for key in ('id','direction','kind','text','status','error','created_at','payload')}


@router.get('/account')
async def get_account(seller_id=Depends(current_seller_id), db:AsyncSession=Depends(get_db)):
    return account_json(await db.get(WhatsAppAccount, seller_id))


@router.put('/account')
async def connect(payload:Connect, seller_id=Depends(current_seller_id), db:AsyncSession=Depends(get_db)):
    account = await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id == seller_id).with_for_update())
    token = payload.access_token
    if not token:
        if not account or not account.access_token or account.phone_number_id != payload.phone_number_id or account.waba_id != payload.waba_id:
            raise HTTPException(422, 'Provide an access token to connect this account')
        token = decrypt(account.access_token)
    if len(token) < 10:
        raise HTTPException(422, 'Access token is too short')
    encrypted = encrypt(token)
    phone = await provider.verify_connection(token, payload.waba_id, payload.phone_number_id)
    if account and account.phone_number_id != payload.phone_number_id:
        raise HTTPException(409, 'A store cannot switch its connected number while retaining the old inbox; use a separate store')
    if not account:
        account = WhatsAppAccount(seller_id=seller_id, phone_number_id=payload.phone_number_id, waba_id=payload.waba_id)
        db.add(account)
    account.waba_id, account.access_token = payload.waba_id, encrypted
    account.display_phone_number = str(phone.get('display_phone_number',''))[:50]
    account.enabled = False
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'This WhatsApp number is already connected to another store')
    return account_json(account)


@router.patch('/account')
async def patch_account(payload:AccountPatch, seller_id=Depends(current_seller_id), db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db,seller_id,lock=True)
    if payload.enabled:
        if not account.access_token:
            raise HTTPException(409, 'Reconnect WhatsApp before enabling sends')
        decrypt(account.access_token)
        if not getattr(settings,'WHATSAPP_APP_SECRET','') or not getattr(settings,'WHATSAPP_WEBHOOK_VERIFY_TOKEN',''):
            raise HTTPException(503, 'The operator must configure signed WhatsApp webhooks before enabling sends')
    if payload.rules is not None:
        keywords = [r.keyword.casefold() for r in payload.rules]
        if len(set(keywords)) != len(keywords) or set(keywords) & {'stop','unsubscribe','start'}:
            raise HTTPException(422, 'Keywords must be unique; STOP, UNSUBSCRIBE and START are reserved')
        for rule in payload.rules:
            if rule.product_id and not await db.scalar(select(Product.id).where(Product.id == rule.product_id,Product.seller_id == seller_id,Product.active.is_(True))):
                raise HTTPException(404, 'Rule product not found')
    if payload.order_templates is not None:
        if set(payload.order_templates) - {'placed','confirmed','shipped','delivered'}:
            raise HTTPException(422, 'Unsupported order event')
        for ref in payload.order_templates.values():
            template = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id,WhatsAppTemplate.name == ref.name,WhatsAppTemplate.language == ref.language))
            if not template or template.category != 'UTILITY' or template.status != 'APPROVED':
                raise HTTPException(422, 'Order updates require a synced, approved utility template')
            from types import SimpleNamespace
            service.check_template(template, SimpleNamespace(opted_out=False,utility_opt_in=True), ['name','order','detail'])
    for key,value in payload.model_dump(mode='json',exclude_none=True).items():
        setattr(account,key,value)
    await db.flush()
    return account_json(account)


@router.delete('/account')
async def disconnect(seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db,seller_id,lock=True)
    account.enabled, account.automation_enabled, account.access_token = False, False, ''
    return {'disconnected':True}


@router.get('/contacts')
async def contacts(seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    rows = (await db.scalars(select(WhatsAppContact).where(WhatsAppContact.seller_id == seller_id).order_by(WhatsAppContact.last_inbound_at.desc().nullslast(),WhatsAppContact.created_at.desc()).limit(200))).all()
    return {'items':[{**{key:getattr(c,key) for key in ('id','phone','name','last_inbound_at','opted_out','utility_opt_in','marketing_opt_in')},'reply_window_open':service.window_open(c),'consent_history':c.consent_history} for c in rows]}


@router.get('/contacts/{contact_id}/messages')
async def messages(contact_id:UUID,seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    await service.contact_for(db,seller_id,contact_id)
    rows = (await db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == seller_id,WhatsAppMessage.contact_id == contact_id).order_by(WhatsAppMessage.created_at.desc(),WhatsAppMessage.id).limit(200))).all()
    return {'items':[message_json(m) for m in reversed(rows)]}


@router.patch('/contacts/{contact_id}/consent')
async def consent(contact_id:UUID,payload:Consent,seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    await service.account_for(db,seller_id,lock=True)
    contact = await service.contact_for(db,seller_id,contact_id,lock=True)
    if contact.opted_out and (payload.utility_opt_in or payload.marketing_opt_in):
        raise HTTPException(409,'This contact opted out; only a new inbound START can reopen messaging')
    service.record_consent(contact,payload.utility_opt_in,payload.marketing_opt_in,'seller_attested:'+payload.source.strip())
    return {'saved':True}


@router.post('/contacts/{contact_id}/reply',status_code=202)
async def reply(contact_id:UUID,payload:Reply,seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db,seller_id,enabled=True,lock=True)
    contact = await service.contact_for(db,seller_id,contact_id,lock=True)
    return message_json(await service.queue_message(db,account,contact,key='manual:'+str(payload.idempotency_key),text=payload.text))


@router.get('/templates')
async def templates(seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    rows = (await db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id).order_by(WhatsAppTemplate.name))).all()
    return {'items':[template_json(t) for t in rows]}


@router.post('/templates', status_code=201)
async def create_template(payload:TemplateCreate,seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db, seller_id, lock=True)
    if not account.access_token:
        raise HTTPException(409, 'Reconnect WhatsApp before creating a template')
    existing = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id,
        WhatsAppTemplate.name == payload.name, WhatsAppTemplate.language == payload.language))
    if existing:
        raise HTTPException(409, 'This template already exists. Sync templates to check its current status')
    components = payload.components()
    try:
        result = await provider.create_template(account, name=payload.name, language=payload.language,
            category=payload.category, components=components)
    except provider.SendUncertain:
        raise HTTPException(504, 'Meta may have received this template. Sync templates or check WhatsApp Manager before submitting again')
    template = WhatsAppTemplate(seller_id=seller_id, name=payload.name, language=payload.language,
        category=result['category'], status=result['status'], components=components, synced_at=service.now())
    db.add(template)
    await db.flush()
    return template_json(template)


@router.post('/templates/sync')
async def template_sync(seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db,seller_id,lock=True)
    await service.sync_templates(db,account)
    return {'synced':True}


@router.post('/contacts/{contact_id}/template',status_code=202)
async def template_send(contact_id:UUID,payload:TemplateSend,seller_id=Depends(current_seller_id),db:AsyncSession=Depends(get_db)):
    account = await service.account_for(db,seller_id,enabled=True,lock=True)
    contact = await service.contact_for(db,seller_id,contact_id,lock=True)
    template = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id,WhatsAppTemplate.name == payload.name,WhatsAppTemplate.language == payload.language))
    service.check_template(template,contact,payload.parameters)
    return message_json(await service.queue_message(db,account,contact,key='manual:'+str(payload.idempotency_key),template=template,parameters=payload.parameters))
