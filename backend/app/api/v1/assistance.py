"""Native assistance over current memberships; never a support impersonation API."""
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import enabled
from app.api.v1.identity import current_actor
from app.api.v1.session import business_mutation, require_v1_mutation
from app.database import get_db
from app.schemas.assistance import (AssignmentWrite, AssistanceOpenWrite, AssistanceBusinessRead,
    AssistanceCommandRead, AssistancePage)
from app.services import assistance as domain
from app.services.identity import Actor, require_business_access


def private(response:Response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})


async def native_actor(request:Request,db:AsyncSession=Depends(get_db)):
    actor=await current_actor(request,db);domain.native(actor);return actor


def native_read(capability):
    async def guarded(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
        actor=await native_actor(request,db)
        await require_business_access(db,actor,business_id,capability)
        yield actor
        fresh=await native_actor(request,db)
        if fresh!=actor:raise HTTPException(401,'Your sign-in changed')
        await require_business_access(db,fresh,business_id,capability)
    return guarded


def available_paths(request):return {getattr(route,'path','') for route in request.app.routes}


router=APIRouter(tags=['v1-assistance'],dependencies=[Depends(enabled),Depends(private)])
STATIC=Path(__file__).resolve().parents[3]/'static'
PRIVATE_HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'}


@router.get('/v1/assistance',include_in_schema=False)
async def console(actor:Actor=Depends(native_actor)):
    return FileResponse(STATIC/'assistance.html',headers=PRIVATE_HEADERS)


@router.get('/v1/businesses/{business_id}/assistance',include_in_schema=False)
async def workspace(business_id:UUID,actor:Actor=Depends(native_read('readiness.read'))):
    return FileResponse(STATIC/'assistance.html',headers=PRIVATE_HEADERS)


@router.get('/api/v1/assistance/businesses',response_model=AssistancePage)
async def businesses(request:Request,after:UUID|None=None,limit:int=Query(20,ge=1,le=20),assigned_to_me:bool=False,
        actor:Actor=Depends(native_actor),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        if await native_actor(request,db)!=actor:raise HTTPException(401,'Your sign-in changed')
    return await domain.businesses(db,actor,after=after,limit=limit,assigned_to_me=assigned_to_me,
        available_paths=available_paths(request),reauthorize=reauthorize)


@router.get('/api/v1/businesses/{business_id}/assistance',response_model=AssistanceBusinessRead)
async def business(business_id:UUID,request:Request,actor:Actor=Depends(native_read('readiness.read')),db:AsyncSession=Depends(get_db)):
    return await domain.business_view(db,actor,business_id,available_paths=available_paths(request))


@router.get('/api/v1/businesses/{business_id}/assistance/assignees')
async def assignees(business_id:UUID,actor:Actor=Depends(native_read('members.manage')),db:AsyncSession=Depends(get_db)):
    return await domain.assignees(db,actor,business_id)


@router.put('/api/v1/businesses/{business_id}/assistance/assignment',response_model=AssistanceCommandRead)
async def assign(business_id:UUID,request:Request,body:AssignmentWrite,
        actor:Actor=Depends(business_mutation('members.manage')),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        fresh=await require_v1_mutation(request,db)
        domain.native(fresh)
        if fresh!=actor:raise HTTPException(401,'Your sign-in changed')
    return await domain.command(db,actor,business_id,body,'assignment',reauthorize=reauthorize)


@router.post('/api/v1/businesses/{business_id}/assistance/open',response_model=AssistanceCommandRead)
async def open_workspace(business_id:UUID,request:Request,body:AssistanceOpenWrite,
        actor:Actor=Depends(business_mutation('readiness.read')),db:AsyncSession=Depends(get_db)):
    async def reauthorize():
        fresh=await require_v1_mutation(request,db)
        domain.native(fresh)
        if fresh!=actor:raise HTTPException(401,'Your sign-in changed')
    return await domain.command(db,actor,business_id,body,'open',reauthorize=reauthorize)
