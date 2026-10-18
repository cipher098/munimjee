"""Native one-enquiry review; registry/wiring belongs to the integrator."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.identity import current_actor
from app.api.v1.session import business_mutation, require_v1_mutation
from app.database import get_db
from app.schemas.whatsapp_reel_operator import LinkCommand
from app.services import whatsapp_reel_operator as service
from app.services.auth_sessions import native_session, request_auth_token

PRIVATE={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'}
BASE='/api/v1/businesses/{business_id}/whatsapp/reel-enquiries'


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def protected(request):
            try:
                response=await handler(request)
            except HTTPException as error:
                error.headers={**(error.headers or {}),**PRIVATE}
                raise
            except RequestValidationError:
                return JSONResponse(status_code=422,content={'detail':'Review the selected enquiry and try again'},headers=PRIVATE)
            response.headers.update(PRIVATE)
            return response
        return protected


router=APIRouter(tags=['v1-whatsapp-reel-operator'],route_class=PrivateRoute)


async def read_actor(request,db,business_id):
    actor=await current_actor(request,db)
    await service.access(db,actor,business_id)
    return actor


@router.get(BASE)
async def collection(request:Request,business_id:UUID,cursor:str|None=Query(None,max_length=2048),
                     limit:int=Query(20,ge=1,le=50),db:AsyncSession=Depends(get_db)):
    actor=await read_actor(request,db,business_id)
    result=await service.list_enquiries(db,actor,business_id,cursor=cursor,limit=limit)
    if await read_actor(request,db,business_id)!=actor:
        raise HTTPException(401,'Native session changed')
    return result


@router.get(BASE+'/{inbound_id}')
async def detail(request:Request,business_id:UUID,inbound_id:UUID,db:AsyncSession=Depends(get_db)):
    actor=await read_actor(request,db,business_id)
    result=await service.read_enquiry(db,actor,business_id,inbound_id)
    if await read_actor(request,db,business_id)!=actor:
        raise HTTPException(401,'Native session changed')
    return result


@router.post(BASE+'/{inbound_id}/link')
async def link(request:Request,business_id:UUID,inbound_id:UUID,command:LinkCommand,
               actor=Depends(business_mutation('automation.manage')),db:AsyncSession=Depends(get_db)):
    async def request_authority():
        current=await require_v1_mutation(request,db)
        context=await native_session(db,request_auth_token(request))
        if current!=actor or context.actor!=actor:
            raise HTTPException(401,'Native session changed')
        return service.ReviewerBinding(actor.user_id,context.session.id,context.session.auth_version)
    return await service.link_enquiry(db,actor,business_id,inbound_id,command,request_authority=request_authority)
