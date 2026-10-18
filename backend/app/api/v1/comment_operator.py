"""Native comment controls and no-send enquiry reviews. No legacy or support auth."""
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.identity import current_actor
from app.api.v1.session import business_mutation, require_v1_mutation
from app.database import get_db
from app.schemas.comment_operator import Preview, ReviewClose, RuleDisable, RuleSave
from app.services import comment_operator as service
from app.services.identity import Actor

PRIVATE = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'}


def private(response: Response):
    response.headers.update(PRIVATE)


router = APIRouter(tags=['v1-comment-operator'], dependencies=[Depends(private)])
BASE = '/api/v1/businesses/{business_id}/comment-automation'
WA = '/api/v1/businesses/{business_id}/whatsapp/enquiries'
STATIC = Path(__file__).resolve().parents[3] / 'static'


def authority(request, db, actor, *, write=False):
    async def recheck():
        current = await (require_v1_mutation(request, db) if write else current_actor(request, db))
        if current != actor:
            raise HTTPException(401, 'The native session changed')
    return recheck


@router.get('/v1/businesses/{business_id}/comment-automation', include_in_schema=False)
async def page(request: Request, business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await service.access(db, actor, business_id, authority(request, db, actor))
    return FileResponse(STATIC / 'comment_operator.html', headers=PRIVATE)


@router.get(BASE)
async def overview(request: Request, business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    guard = authority(request, db, actor)
    await service.access(db, actor, business_id, guard)
    current = await service.policy.context(db, business_id)
    access = await service.access(db, actor, business_id, guard)
    return {'business_id': str(business_id), 'business_name': access.business.name,
        'can_manage': 'automation.manage' in access.capabilities,
        'readiness_reason': current.source_reason() if current else 'business_unavailable',
        'account_hint': '…' + current.connection.account_id[-6:] if current and current.connection.account_id else None,
        'provider_permission': 'not_evaluated', 'live_delivery_test': 'not_performed', 'activated_static_replies': 'withheld'}


@router.get(BASE + '/rules')
async def rules(request: Request, business_id: UUID, cursor: str | None = Query(None, max_length=2048), limit: int = Query(20, ge=1, le=50),
                actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.list_rows(db, actor, business_id, 'rules', state='all', cursor=cursor, limit=limit,
        authority=authority(request, db, actor))


@router.get(BASE + '/products')
async def products(request: Request, business_id: UUID, cursor: str | None = Query(None, max_length=2048),
                   actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.product_choices(db, actor, business_id, cursor=cursor, authority=authority(request, db, actor))


@router.post(BASE + '/rules', status_code=201)
async def create_rule(request: Request, business_id: UUID, body: RuleSave,
                      actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.save_rule(db, actor, business_id, body, authority=authority(request, db, actor, write=True))


@router.get(BASE + '/rules/{rule_id}')
async def rule(request: Request, business_id: UUID, rule_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    guard = authority(request, db, actor)
    await service.access(db, actor, business_id, guard)
    row = await service.one(db, service.CommentRule, business_id, rule_id)
    await service.access(db, actor, business_id, guard)
    return service.rule_view(row)


@router.put(BASE + '/rules/{rule_id}')
async def update_rule(request: Request, business_id: UUID, rule_id: UUID, body: RuleSave,
                      actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.save_rule(db, actor, business_id, body, rule_id=rule_id, authority=authority(request, db, actor, write=True))


@router.post(BASE + '/rules/{rule_id}/disable')
async def disable_rule(request: Request, business_id: UUID, rule_id: UUID, body: RuleDisable,
                       actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.save_rule(db, actor, business_id, body, rule_id=rule_id, disable=True, authority=authority(request, db, actor, write=True))


@router.post(BASE + '/preview')
async def preview(request: Request, business_id: UUID, body: Preview,
                  actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.preview(db, actor, business_id, body, authority=authority(request, db, actor, write=True))


@router.get(BASE + '/events')
async def events(request: Request, business_id: UUID, state: Literal['open', 'closed', 'all'] = 'open',
                 cursor: str | None = Query(None, max_length=2048), limit: int = Query(20, ge=1, le=50),
                 actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.list_rows(db, actor, business_id, 'events', state=state, cursor=cursor, limit=limit,
        authority=authority(request, db, actor))


@router.get(BASE + '/events/{event_id}')
async def event(request: Request, business_id: UUID, event_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.event_detail(db, actor, business_id, event_id, authority=authority(request, db, actor))


@router.post(BASE + '/events/{event_id}/reviews')
async def close_event(request: Request, business_id: UUID, event_id: UUID, body: ReviewClose,
                      actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.close_comment(db, actor, business_id, event_id, body, authority=authority(request, db, actor, write=True))


@router.get(WA)
async def enquiries(request: Request, business_id: UUID, state: Literal['open', 'closed', 'all'] = 'open',
                    cursor: str | None = Query(None, max_length=2048), limit: int = Query(20, ge=1, le=50),
                    actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.list_rows(db, actor, business_id, 'enquiries', state=state, cursor=cursor, limit=limit,
        authority=authority(request, db, actor))


@router.get(WA + '/{enquiry_id}')
async def enquiry(request: Request, business_id: UUID, enquiry_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await service.enquiry_detail(db, actor, business_id, enquiry_id, authority=authority(request, db, actor))


@router.post(WA + '/{enquiry_id}/close')
async def close_enquiry(request: Request, business_id: UUID, enquiry_id: UUID, body: ReviewClose,
                        actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.close_enquiry(db, actor, business_id, enquiry_id, body, authority=authority(request, db, actor, write=True))
