"""Separate explicit assisted-readiness endpoints; grants never enter member auth."""
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import enabled as native_enabled
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.schemas.support_grants import GrantCreate, GrantAction, RecipientLookup, GrantCommandRead, SummaryRead
from app.services import support_grants as domain
from app.services.identity import Actor

PRIVATE={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'}
STATIC=Path(__file__).resolve().parents[3]/'static'


def private(response:Response):response.headers.update(PRIVATE)


async def native(request:Request,db:AsyncSession=Depends(get_db)):
    domain.enabled();actor=await current_actor(request,db);domain.native(actor);return actor


async def mutation(request:Request,db:AsyncSession=Depends(get_db)):
    domain.enabled();actor=await require_v1_mutation(request,db);domain.native(actor);return actor


def owner_guard(write=False):
    async def guarded(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
        actor=await (mutation(request,db) if write else native(request,db))
        await domain.owner(db,actor,business_id)
        yield actor
        fresh=await (mutation(request,db) if write else native(request,db))
        if fresh!=actor:raise HTTPException(401,'Your native sign-in changed')
        await domain.owner(db,fresh,business_id)
        if write and (created:=getattr(request.state,'support_created',None)):
            subject_id,grant_id=created
            await domain.access(db,Actor(subject_id,'v1_user'),grant_id)
    return guarded


async def open_guard(request:Request,grant_id:UUID,db:AsyncSession=Depends(get_db)):
    actor=await mutation(request,db);await domain.access(db,actor,grant_id)
    yield actor
    fresh=await mutation(request,db)
    if fresh!=actor:raise HTTPException(401,'Your native sign-in changed')
    await domain.access(db,fresh,grant_id)


router=APIRouter(tags=['v1-explicit-assistance'],dependencies=[Depends(native_enabled),Depends(private)])


@router.get('/v1/support',include_in_schema=False)
async def board_shell(actor:Actor=Depends(native)):
    return FileResponse(STATIC/'support_grants.html',headers=PRIVATE)


@router.get('/v1/businesses/{business_id}/support',include_in_schema=False)
async def owner_shell(business_id:UUID,actor:Actor=Depends(owner_guard())):
    return FileResponse(STATIC/'support_grants.html',headers=PRIVATE)


@router.get('/api/v1/support/grants')
async def board(request:Request,after:UUID|None=None,limit:int=Query(20,ge=1,le=20),
        actor:Actor=Depends(native),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        if await native(request,db)!=actor:raise HTTPException(401,'Your native sign-in changed')
    return await domain.board(db,actor,after=after,limit=limit,reauthorize=reauthorize)


@router.get('/api/v1/businesses/{business_id}/support/grants')
async def owner_list(business_id:UUID,after:UUID|None=None,limit:int=Query(20,ge=1,le=20),
        actor:Actor=Depends(owner_guard()),db:AsyncSession=Depends(get_db)):
    return await domain.owner_grants(db,actor,business_id,after,limit)


@router.post('/api/v1/businesses/{business_id}/support/recipient')
async def recipient(business_id:UUID,body:RecipientLookup,actor:Actor=Depends(owner_guard(True)),db:AsyncSession=Depends(get_db)):
    return await domain.lookup(db,actor,business_id,body.email)


@router.post('/api/v1/businesses/{business_id}/support/grants',response_model=GrantCommandRead)
async def create(business_id:UUID,request:Request,body:GrantCreate,actor:Actor=Depends(owner_guard(True)),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        if await mutation(request,db)!=actor:raise HTTPException(401,'Your native sign-in changed')
    value=await domain.create(db,actor,business_id,body,reauthorize=reauthorize)
    await reauthorize();await domain.owner(db,actor,business_id)
    await domain.subject(db,body.subject_user_id)
    request.state.support_created=(body.subject_user_id,value.grant_id)
    return value


@router.post('/api/v1/businesses/{business_id}/support/grants/{grant_id}/revoke',response_model=GrantCommandRead)
async def revoke(business_id:UUID,grant_id:UUID,request:Request,body:GrantAction,
        actor:Actor=Depends(owner_guard(True)),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        if await mutation(request,db)!=actor:raise HTTPException(401,'Your native sign-in changed')
    return await domain.revoke(db,actor,business_id,grant_id,body,reauthorize=reauthorize)


@router.post('/api/v1/support/grants/{grant_id}/open',response_model=SummaryRead)
async def open_summary(grant_id:UUID,request:Request,body:GrantAction,
        actor:Actor=Depends(open_guard),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        if await mutation(request,db)!=actor:raise HTTPException(401,'Your native sign-in changed')
    return await domain.summary(db,actor,grant_id,body,reauthorize=reauthorize)
