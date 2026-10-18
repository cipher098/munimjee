"""Native order-scoped parcel intake; no browser-selected connector or secrets."""
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from sqlalchemy import select,func,or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.models.parcel_tracking import OrderParcelLink,ParcelObservation,ParcelNotification,ParcelAudit
from app.services import parcel_tracking as service
from app.services import parcel_reviews as reviews
from app.schemas.parcel_reviews import ReviewPreview,ReplacementPreview,ReviewCommand,ReplacementCommand
from app.services.parcel_connector import COURIERS
from app.models.whatsapp import WhatsAppMessage
from app.services.identity import Actor

def enabled():
    from app.config import settings
    if not settings.V1_PARCEL_ENABLED:raise HTTPException(404,'Not found')

router=APIRouter(tags=['v1-order-parcels'],dependencies=[Depends(enabled)])
BASE='/api/v1/businesses/{business_id}/orders/{order_id}/parcels'
STATIC=Path(__file__).resolve().parents[3]/'static'

class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scan_id:UUID
    courier_id:Literal['tirupati','aakash_ganga','skyking','shree_maruti','dhl','fedex','ups']
    awb:str=Field(min_length=6,max_length=80)

class Confirm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key:UUID
    candidate_token:str=Field(min_length=20,max_length=4000)
    expected_order_fingerprint:str=Field(pattern='^[a-f0-9]{64}$')
    confirmed:StrictBool

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key:UUID


def link_view(row):
    return {'fingerprint':reviews.link_fingerprint(row),'in_flight':row.lease_token is not None,**{k:(str(getattr(row,k)) if k in {'id','business_id','order_id','idempotency_key'} else getattr(row,k).isoformat() if getattr(row,k) is not None and k.endswith('_at') else getattr(row,k)) for k in
        ('id','business_id','order_id','idempotency_key','courier_id','awb','state','revision','tracking_state','raw_status','checked_at','attempted_at','last_sync_at','error_code','created_at')}}

async def link_for(db,business_id,order_id,link_id,lock=False):
    query=select(OrderParcelLink).where(OrderParcelLink.id==link_id,OrderParcelLink.business_id==business_id,OrderParcelLink.order_id==order_id)
    if lock:query=query.with_for_update()
    link=await db.scalar(query.execution_options(populate_existing=True))
    if not link:raise HTTPException(404,'Parcel link not found')
    return link


def request_authority(request,db,actor):
    async def recheck():
        current=await require_v1_mutation(request,db)
        if current!=actor:raise HTTPException(401,'The native session changed')
    return recheck


@router.get('/v1/businesses/{business_id}/orders/{order_id}/parcel',include_in_schema=False)
async def page(business_id:UUID,order_id:UUID,actor:Actor=Depends(current_actor),db:AsyncSession=Depends(get_db)):
    await service.access_order(db,actor,business_id,order_id)
    return FileResponse(STATIC/'parcel_tracking.html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})


@router.get(BASE)
async def overview(business_id:UUID,order_id:UUID,actor:Actor=Depends(current_actor),db:AsyncSession=Depends(get_db)):
    access,order=await service.access_order(db,actor,business_id,order_id)
    links=(await db.scalars(select(OrderParcelLink).where(OrderParcelLink.business_id==business_id,OrderParcelLink.order_id==order_id).order_by(OrderParcelLink.created_at.desc()).limit(50))).all()
    try:await service.connector_for(db,business_id);configured=True
    except HTTPException:configured=False
    result=[]
    for link in links:
        notifications=(await db.scalars(select(ParcelNotification).where(ParcelNotification.business_id==business_id,ParcelNotification.link_id==link.id).order_by(ParcelNotification.created_at))).all()
        notes=[]
        reviewed=(await db.execute(select(ParcelAudit.created_at,ParcelAudit.details).where(ParcelAudit.business_id==business_id,ParcelAudit.link_id==link.id,ParcelAudit.action.in_(['seller_resumed_tracking','seller_replaced_link'])).order_by(ParcelAudit.created_at.desc(),ParcelAudit.id.desc()).limit(1))).first()
        for n in notifications:
            status=await db.scalar(select(WhatsAppMessage.status).where(WhatsAppMessage.id==n.outbox_id,WhatsAppMessage.seller_id==business_id)) if n.outbox_id else None
            withheld=bool(reviewed and n.outbox_id and str(n.outbox_id) in reviewed.details.get('withheld_outbox_ids',[]))
            notes.append({'milestone':n.milestone,'decision':n.decision,'reason':n.reason,'outbox_status':status,'withheld_by_review':withheld})
        result.append({**link_view(link),'notifications':notes})
    return {'order':service.order_view(order),'can_link':'orders.write' in access.capabilities,'connector_configured':configured,'couriers':COURIERS,'links':result}


@router.post(BASE+'/preview')
async def preview(request:Request,business_id:UUID,order_id:UUID,payload:Preview,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    return await service.preview(db,actor,business_id,order_id,payload,authority=request_authority(request,db,actor))


@router.post(BASE)
async def confirm(request:Request,business_id:UUID,order_id:UUID,payload:Confirm,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    link,replay=await service.confirm(db,actor,business_id,order_id,payload,authority=request_authority(request,db,actor))
    link_id=link.id
    await db.commit()  # Never acknowledge a non-durable link intent.
    await service.process_link(db,link_id)
    await request_authority(request,db,actor)()
    await service.access_order(db,actor,business_id,order_id,write=True)
    current=await link_for(db,business_id,order_id,link_id)
    return {'link':link_view(current),'replayed':replay}


@router.get(BASE+'/{link_id}/history')
async def history(business_id:UUID,order_id:UUID,link_id:UUID,page:int=Query(1,ge=1,le=10000),page_size:int=Query(25,ge=1,le=100),actor:Actor=Depends(current_actor),db:AsyncSession=Depends(get_db)):
    await service.access_order(db,actor,business_id,order_id);await link_for(db,business_id,order_id,link_id)
    where=(ParcelObservation.business_id==business_id,ParcelObservation.link_id==link_id)
    total=await db.scalar(select(func.count()).select_from(ParcelObservation).where(*where))
    rows=(await db.scalars(select(ParcelObservation).where(*where).order_by(ParcelObservation.observed_at.desc(),ParcelObservation.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'items':[{'id':str(row.id),'raw_time':row.raw_time,'event_at':row.event_at.isoformat() if row.event_at else None,'status':row.status,'description':row.description,'location':row.location,'observed_at':row.observed_at.isoformat()} for row in rows],'total':total,'page':page,'page_size':page_size}


@router.post(BASE+'/{link_id}/refresh')
async def refresh(request:Request,business_id:UUID,order_id:UUID,link_id:UUID,payload:Command,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    await service.access_order(db,actor,business_id,order_id,write=True)
    link=await link_for(db,business_id,order_id,link_id,lock=True)
    await request_authority(request,db,actor)()
    await service.access_order(db,actor,business_id,order_id,write=True)
    previous=await db.scalar(select(ParcelAudit).where(ParcelAudit.business_id==business_id,ParcelAudit.idempotency_key==payload.idempotency_key))
    if previous:
        if previous.actor_id!=actor.user_id or previous.link_id!=link_id or previous.action!='seller_refresh_requested':raise HTTPException(409,'This command was already used for different details')
        return {'link':link_view(link),'replayed':True}
    db.add(ParcelAudit(business_id=business_id,link_id=link_id,actor_id=actor.user_id,action='seller_refresh_requested',idempotency_key=payload.idempotency_key,details={}))
    await db.commit()
    await service.process_link(db,link_id)
    await request_authority(request,db,actor)()
    await service.access_order(db,actor,business_id,order_id,write=True)
    return {'link':link_view(await link_for(db,business_id,order_id,link_id)),'replayed':False}


@router.post(BASE+'/{link_id}/review-preview')
async def review_preview(request:Request,business_id:UUID,order_id:UUID,link_id:UUID,payload:ReviewPreview,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    return await reviews.preview(db,actor,business_id,order_id,link_id,payload,authority=request_authority(request,db,actor))


@router.post(BASE+'/{link_id}/replacement-preview')
async def replacement_preview(request:Request,business_id:UUID,order_id:UUID,link_id:UUID,payload:ReplacementPreview,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    return await reviews.preview(db,actor,business_id,order_id,link_id,payload,replacement=True,authority=request_authority(request,db,actor))


async def reviewed_command(request,db,actor,business_id,order_id,link_id,payload,*,replacement=False):
    result,replayed=await reviews.command(db,actor,business_id,order_id,link_id,payload,replacement=replacement,authority=request_authority(request,db,actor))
    result_id=result.id
    await db.commit()
    if replacement:await service.process_link(db,result_id)
    await request_authority(request,db,actor)()
    await service.access_order(db,actor,business_id,order_id,write=True)
    return {'command_id':str(payload.idempotency_key),'action':'replace' if replacement else payload.action,'source_link_id':str(link_id),'link':link_view(await link_for(db,business_id,order_id,result_id)),'replayed':replayed}


@router.post(BASE+'/{link_id}/review')
async def review(request:Request,business_id:UUID,order_id:UUID,link_id:UUID,payload:ReviewCommand,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    return await reviewed_command(request,db,actor,business_id,order_id,link_id,payload)


@router.post(BASE+'/{link_id}/replace')
async def replace(request:Request,business_id:UUID,order_id:UUID,link_id:UUID,payload:ReplacementCommand,actor:Actor=Depends(require_v1_mutation),db:AsyncSession=Depends(get_db)):
    return await reviewed_command(request,db,actor,business_id,order_id,link_id,payload,replacement=True)


@router.get(BASE+'/{link_id}/reviews')
async def review_history(business_id:UUID,order_id:UUID,link_id:UUID,page:int=Query(1,ge=1,le=10000),page_size:int=Query(25,ge=1,le=100),actor:Actor=Depends(current_actor),db:AsyncSession=Depends(get_db)):
    await service.access_order(db,actor,business_id,order_id);await link_for(db,business_id,order_id,link_id)
    where=(ParcelAudit.business_id==business_id,or_(ParcelAudit.link_id==link_id,ParcelAudit.details['source_link_id'].astext==str(link_id)))
    total=await db.scalar(select(func.count()).select_from(ParcelAudit).where(*where))
    rows=(await db.scalars(select(ParcelAudit).where(*where).order_by(ParcelAudit.created_at.desc(),ParcelAudit.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'items':[{'id':str(row.id),'action':row.action,'reason':row.details.get('reason'),'source_link_id':row.details.get('source_link_id',str(row.link_id)),'result_link_id':row.details.get('result_link_id',str(row.link_id)),'created_at':row.created_at.isoformat()} for row in rows],'total':total,'page':page,'page_size':page_size}
