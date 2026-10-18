"""Strict public collector and native owner-controlled measurement endpoints."""
import asyncio
import json
import re
from datetime import date,datetime,timedelta,timezone
from uuid import UUID

from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import enabled
from app.api.v1.analytics_v1 import native_read
from app.api.v1.session import require_v1_mutation
from app.config import settings
from app.database import get_db
from app.schemas.activity_v1 import (ActivityRead,ContextRead,ContextWrite,EventRead,
    EventWrite,PolicyRead,PolicyReceipt,PolicyWrite)
from app.services import activity_v1 as domain
from app.v1.storefront.rendering import canonical_origin


def private(response:Response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})


async def owner_mutation(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
    actor=await require_v1_mutation(request,db)
    await domain.owner(db,actor,business_id)
    yield actor
    current=await require_v1_mutation(request,db)
    if current!=actor:raise HTTPException(401,'Your sign-in changed')
    await domain.owner(db,current,business_id)


router=APIRouter(tags=['v1-first-party-activity'],dependencies=[Depends(enabled),Depends(private)])


async def public_scope(slug:str,db:AsyncSession=Depends(get_db)):
    business_id=await domain.public_business(db,slug)
    yield business_id
    # A publish/activity change during a collector lock wait cannot commit new
    # facts under a previously valid storefront snapshot.
    if await domain.public_business(db,slug)!=business_id:raise HTTPException(404,'Store not found')


@router.get('/api/v1/businesses/{business_id}/analytics/measurement-policy',response_model=PolicyRead)
async def policy(business_id:UUID,actor=Depends(native_read('analytics.read')),db:AsyncSession=Depends(get_db)):
    return await domain.policy_read(db,business_id,actor)


@router.put('/api/v1/businesses/{business_id}/analytics/measurement-policy',response_model=PolicyReceipt)
async def save_policy(business_id:UUID,payload:PolicyWrite,actor=Depends(owner_mutation),db:AsyncSession=Depends(get_db)):
    return await domain.change_policy(db,business_id,actor,payload)


@router.get('/api/v1/businesses/{business_id}/analytics/activity',response_model=ActivityRead)
async def report(business_id:UUID,request:Request,from_date:date|None=None,to_date:date|None=None,
        actor=Depends(native_read('analytics.read')),db:AsyncSession=Depends(get_db)):
    keys=[key for key,_ in request.query_params.multi_items()]
    if len(keys)!=len(set(keys)) or any(key not in {'from_date','to_date'} for key in keys):
        raise HTTPException(422,'Use the supported activity date filters once each')
    today=datetime.now(timezone.utc).date()
    start=from_date or today-timedelta(days=29);end=to_date or today+timedelta(days=1)
    if not 1<=(end-start).days<=90 or end>today+timedelta(days=1):
        raise HTTPException(422,'Choose 1–90 UTC dates up to today; the end date is exclusive')
    return await domain.report(db,business_id,start,end)


async def body(request,model):
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        raise HTTPException(415,'Use application/json')
    try:
        data=bytearray()
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>1024:raise HTTPException(413,'Measurement request is too large')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError()
                result[key]=value
            return result
        parsed=json.loads(data.decode('utf-8'),object_pairs_hook=unique,
            parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        return model.model_validate(parsed)
    except (UnicodeError,ValueError,RecursionError,ValidationError,TimeoutError):
        raise HTTPException(422,'Use the supported measurement fields')


def browser_context(request):
    try:origin=canonical_origin(settings.PUBLIC_BASE_URL)
    except ValueError:raise HTTPException(503,'Measurement origin is unavailable')
    if request.headers.get('origin')!=origin:
        raise HTTPException(403,'Untrusted measurement origin')
    if request.headers.get('sec-fetch-site') not in {None,'same-origin'}:
        raise HTTPException(403,'Untrusted measurement origin')
    if request.query_params:raise HTTPException(422,'Measurement does not accept query fields')
    # Transient filtering only; no UA/IP/referrer/URL is written to the ledger.
    excluded=(request.headers.get('sec-gpc')=='1' or request.headers.get('dnt')=='1'
        or any(value in request.headers.get('purpose','').lower()+' '+request.headers.get('sec-purpose','').lower()
            for value in ('prefetch','prerender'))
        or bool(re.search(r'bot|crawler|spider|headless|preview|facebookexternalhit|slurp',
            request.headers.get('user-agent',''),re.I)))
    native=any(request.cookies.get(key) for key in ('v1_session','dashboard_session','seller_session','view_seller'))
    return excluded,native


@router.post('/api/v1/storefronts/{slug}/activity/contexts',response_model=ContextRead)
async def context(slug:str,request:Request,bid=Depends(public_scope),db:AsyncSession=Depends(get_db)):
    excluded,native=browser_context(request)
    payload=await body(request,ContextWrite)
    if excluded:return ContextRead(state='excluded')
    # Any additional bearer is a native/test hint, never authority for live.
    return await domain.start_context(db,bid,payload,native=native or bool(request.headers.get('authorization')))


@router.post('/api/v1/storefronts/{slug}/activity/events',response_model=EventRead)
async def event(slug:str,request:Request,bid=Depends(public_scope),db:AsyncSession=Depends(get_db)):
    excluded,native=browser_context(request)
    payload=await body(request,EventWrite)
    if excluded:return EventRead(state='disabled',replayed=False)
    return await domain.accept_event(db,bid,request.headers.get('authorization'),payload,native=native)
