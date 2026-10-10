"""Seller-facing comment rules, safe previews, and delivery history."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from app.api.dashboard_auth import current_seller_id
from app.database import get_db
from app.models.seller import Seller
from app.models.comment_automation import CommentRule, CommentEvent, CommentAction
from app.services.comment_automation import matches, product_link, public_base_ready

router = APIRouter(prefix='/comment-automation', tags=['comment-automation'])


class RuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = False
    media_id: str | None = Field(default=None, pattern=r'^\d{1,100}$')
    keywords: list[str] = Field(min_length=1, max_length=30)
    product_id: UUID
    private_reply: str = Field(min_length=1, max_length=700)
    public_reply: str | None = Field(default=None, max_length=500)

    @field_validator('keywords')
    @classmethod
    def clean_keywords(cls, keywords):
        cleaned = list(dict.fromkeys(k.strip().casefold() for k in keywords))
        if any(not k or len(k) > 60 for k in cleaned):
            raise ValueError('Keywords must contain 1–60 characters')
        return cleaned

    @field_validator('name', 'private_reply')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value.strip()


def serialize_rule(rule):
    return {key: getattr(rule, key) for key in ('id','name','enabled','media_id','keywords','product_id','private_reply','public_reply','created_at')}


async def get_rule(db, seller_id, rule_id):
    rule = await db.scalar(select(CommentRule).where(CommentRule.id == rule_id, CommentRule.seller_id == seller_id))
    if not rule:
        raise HTTPException(404, 'Rule not found')
    return rule


@router.get('/status')
async def status(seller_id=Depends(current_seller_id), db=Depends(get_db)):
    seller = await db.get(Seller, UUID(seller_id))
    return {'connected': bool(seller and seller.instagram_token and seller.instagram_page_id),
            'account_id': seller.instagram_page_id if seller else None,
            'permissions_status': 'not_verified', 'reconnect_required': True,
            'public_base_ready': public_base_ready(),
            'required_permissions': ['instagram_business_basic','instagram_business_manage_comments','instagram_business_manage_messages'],
            'webhook_fields': ['messages','comments'],
            'policy': {'private_reply_days':7,'private_replies_per_comment':1,'followups':'Only after recipient replies, within 24 hours'}}


@router.get('/rules')
async def list_rules(seller_id=Depends(current_seller_id), db=Depends(get_db)):
    return [serialize_rule(r) for r in (await db.scalars(select(CommentRule).where(CommentRule.seller_id == seller_id).order_by(CommentRule.created_at))).all()]


async def validate_rule(data, seller_id, db):
    await product_link(db, seller_id, data.product_id)
    if data.enabled:
        seller = await db.get(Seller, UUID(seller_id))
        if not seller or not seller.instagram_token or not seller.instagram_page_id:
            raise HTTPException(400, 'Connect Instagram before enabling a rule')


@router.post('/rules', status_code=201)
async def create_rule(data: RuleInput, seller_id=Depends(current_seller_id), db=Depends(get_db)):
    await validate_rule(data, seller_id, db)
    rule = CommentRule(seller_id=UUID(seller_id), **data.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return serialize_rule(rule)


@router.put('/rules/{rule_id}')
async def update_rule(rule_id: UUID, data: RuleInput, seller_id=Depends(current_seller_id), db=Depends(get_db)):
    rule = await get_rule(db, seller_id, rule_id)
    await validate_rule(data, seller_id, db)
    for key, value in data.model_dump().items():
        setattr(rule, key, value)
    await db.flush()
    return serialize_rule(rule)


@router.delete('/rules/{rule_id}')
async def delete_rule(rule_id: UUID, seller_id=Depends(current_seller_id), db=Depends(get_db)):
    rule = await get_rule(db, seller_id, rule_id)
    # Keep history and pending action provenance. Deletion means disabling.
    rule.enabled = False
    return {'status':'disabled'}


class PreviewInput(BaseModel):
    rule_id: UUID
    text: str = Field(max_length=10000)
    media_id: str = Field(max_length=100)


@router.post('/preview')
async def preview(data: PreviewInput, seller_id=Depends(current_seller_id), db=Depends(get_db)):
    rule = await get_rule(db, seller_id, data.rule_id)
    link = await product_link(db, seller_id, rule.product_id)
    return {'matches': matches(rule, data.text, data.media_id), 'private_reply': f'{rule.private_reply}\n{link}',
            'public_reply': rule.public_reply, 'product_url': link, 'sends':False}


@router.get('/events')
async def events(seller_id=Depends(current_seller_id), db=Depends(get_db)):
    rows = (await db.scalars(select(CommentEvent).where(CommentEvent.seller_id == seller_id).order_by(CommentEvent.created_at.desc()).limit(100))).all()
    actions = (await db.scalars(select(CommentAction).where(CommentAction.seller_id == seller_id, CommentAction.event_id.in_([r.id for r in rows])))).all() if rows else []
    return [{**{k:getattr(r,k) for k in ('id','comment_id','media_id','text','status','reason','created_at')},
             'actions':[{k:getattr(a,k) for k in ('id','kind','status','error_code','provider_id')} for a in actions if a.event_id == r.id]} for r in rows]
