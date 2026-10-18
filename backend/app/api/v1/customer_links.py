"""Native operator view. Proof cannot be asserted from any browser endpoint."""
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation, business_mutation
from app.services.identity import Actor
from app.services import customer_links as service
from app.models.customer_links import Customer, CustomerLinkChallenge as Challenge, CustomerAssociation as Association, CustomerLinkAudit as Audit
from app.models.conversation import Conversation
from app.models.whatsapp import WhatsAppContact
from app.schemas.customer_links import Start, Finish, Unlink


def enabled():
    if not service.enabled():
        raise HTTPException(404, 'Customer links are unavailable')


router = APIRouter(tags=['v1-customer-links'], dependencies=[Depends(enabled)])
BASE = '/api/v1/businesses/{business_id}/customer-links'
STATIC = Path(__file__).resolve().parents[3] / 'static'


def authority(request, db, actor):
    async def recheck():
        current = await require_v1_mutation(request, db)
        if current != actor:
            raise HTTPException(401, 'The native session changed')
    return recheck


async def read_guard(request, db, actor, business_id):
    current = await current_actor(request, db)
    if current != actor:
        raise HTTPException(401, 'The native session changed')
    return await service.access(db, current, business_id)


@router.get('/v1/businesses/{business_id}/customers', include_in_schema=False)
async def page(request: Request, business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await read_guard(request, db, actor, business_id)
    return FileResponse(STATIC / 'customer_links.html', headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'})


@router.get(BASE + '/sources')
async def sources(request: Request, business_id: UUID, channel: Literal['instagram', 'whatsapp'],
                  page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
                  actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await read_guard(request, db, actor, business_id)
    model = Conversation if channel == 'instagram' else WhatsAppContact
    query = select(model).where(model.seller_id == business_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(model.created_at.desc(), model.id).offset((page-1)*page_size).limit(page_size))).all()
    result = []
    for row in rows:
        subject = row.customer_instagram_id if channel == 'instagram' else row.phone
        name = row.customer_name if channel == 'instagram' else row.name
        linked = await db.scalar(select(Association.id).where(Association.business_id == business_id,
            Association.revoked_at.is_(None), (Association.conversation_id == row.id) if channel == 'instagram' else (Association.contact_id == row.id)))
        result.append({'id': str(row.id), 'channel': channel, 'label': (name or 'Unnamed account')[:200],
            'account_hint': '…' + subject[-6:], 'already_linked': linked is not None})
    await read_guard(request, db, actor, business_id)
    return {'items': result, 'page': page, 'page_size': page_size, 'total': total}


@router.get(BASE)
async def overview(request: Request, business_id: UUID, state: Literal['all', 'pending', 'verified', 'cancelled'] = 'all',
                   page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
                   actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await read_guard(request, db, actor, business_id)
    query = select(Challenge).where(Challenge.business_id == business_id)
    if state != 'all':
        query = query.where(Challenge.state == state)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(Challenge.issued_at.desc(), Challenge.id).offset((page-1)*page_size).limit(page_size))).all()
    items = [await service.view(db, row) for row in rows]
    await read_guard(request, db, actor, business_id)
    return {'business_id': str(business_id), 'business_name': access.business.name, 'can_manage': 'automation.manage' in access.capabilities,
        'items': items, 'page': page, 'page_size': page_size, 'total': total, 'verification_scope': service.SCOPE,
        'live_provider_canary': 'not_evaluated'}


@router.get(BASE + '/{challenge_id}')
async def detail(request: Request, business_id: UUID, challenge_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await read_guard(request, db, actor, business_id)
    row = await service.challenge_for(db, business_id, challenge_id)
    result = await service.view(db, row)
    if row.customer_id:
        fingerprint, associations = await service.association_fingerprint(db, business_id, row.customer_id)
        result['association_fingerprint'] = fingerprint
        result['linked'] = any(item.revoked_at is None for item in associations)
    else:
        result.update(association_fingerprint=None, linked=False)
    audits = (await db.scalars(select(Audit).where(Audit.business_id == business_id).order_by(Audit.created_at.desc()).limit(100))).all()
    result['audit'] = [{'action': a.action, 'at': a.created_at.isoformat(),
        'reason': a.result.get('reason')} for a in audits if a.result.get('challenge_id') == str(row.id) or (row.customer_id and a.result.get('customer_id') == str(row.customer_id))]
    await read_guard(request, db, actor, business_id)
    return result


@router.post(BASE, status_code=201)
async def start(request: Request, business_id: UUID, payload: Start,
                actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    row = await service.start(db, actor, business_id, payload, authority=authority(request, db, actor))
    result = await service.view(db, row)
    # Never returned by GET/list/audit. Only the exact creator's mutation replay
    # can recover its own original expiring command; no provider send occurs.
    secret = service.secret_for(row)
    result['consent_command'] = f'LINK {secret} I CONSENT' if row.state == 'pending' and row.expires_at > service.now() and result['binding_current'] and service.hmac.compare_digest(service.secret_digest(secret), row.secret_digest) else None
    result['command_id'] = str(payload.idempotency_key)
    return result


@router.post(BASE + '/{challenge_id}/finalize')
async def finalize(request: Request, business_id: UUID, challenge_id: UUID, payload: Finish,
                   actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.finish(db, actor, business_id, challenge_id, payload, authority=authority(request, db, actor))


@router.post(BASE + '/{challenge_id}/cancel')
async def cancel(request: Request, business_id: UUID, challenge_id: UUID, payload: Finish,
                 actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.finish(db, actor, business_id, challenge_id, payload, cancel=True, authority=authority(request, db, actor))


@router.post(BASE + '/customers/{customer_id}/unlink')
async def unlink(request: Request, business_id: UUID, customer_id: UUID, payload: Unlink,
                 actor: Actor = Depends(business_mutation('automation.manage')), db: AsyncSession = Depends(get_db)):
    return await service.unlink(db, actor, business_id, customer_id, payload, authority=authority(request, db, actor))
