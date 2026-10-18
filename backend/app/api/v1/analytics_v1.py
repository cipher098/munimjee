"""Native seller purchase analytics, no mutations or provider requests."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import enabled
from app.api.v1.identity import current_actor
from app.database import get_db
from app.schemas.analytics_v1 import AnalyticsRead, Filters, PaymentMethod, PaymentStatus, FulfillmentStatus
from app.services import analytics_v1 as domain
from app.services.identity import require_business_access


def private(response: Response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})


def native_read(capability):
    async def guarded(request: Request,business_id: UUID,db: AsyncSession=Depends(get_db)):
        actor=await current_actor(request,db)
        if actor.auth_method!='v1_user':raise HTTPException(401,'Native V1 sign-in required')
        await require_business_access(db,actor,business_id,capability)
        yield actor
        fresh=await current_actor(request,db)
        if fresh!=actor:raise HTTPException(401,'Your sign-in changed')
        await require_business_access(db,fresh,business_id,capability)
    return guarded


router=APIRouter(tags=['v1-analytics'],dependencies=[Depends(enabled),Depends(private)])
STATIC=Path(__file__).resolve().parents[3]/'static'


@router.get('/v1/businesses/{business_id}/analytics',include_in_schema=False)
async def workspace(business_id: UUID,actor=Depends(native_read('business.read'))):
    return FileResponse(STATIC/'analytics_v1.html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})


@router.get('/api/v1/businesses/{business_id}/analytics',response_model=AnalyticsRead)
async def analytics(business_id: UUID,request: Request,from_date: date|None=None,to_date: date|None=None,
        payment_status: PaymentStatus|None=None,fulfillment_status: FulfillmentStatus|None=None,
        payment_method: PaymentMethod|None=None,include_gateway_test: bool=False,
        page: int=Query(1,ge=1,le=1000),page_size: int=Query(25,ge=1,le=50),
        actor=Depends(native_read('analytics.read')),db: AsyncSession=Depends(get_db)):
    allowed={'from_date','to_date','payment_status','fulfillment_status','payment_method','include_gateway_test','page','page_size'}
    keys=[key for key,_ in request.query_params.multi_items()]
    if len(keys)!=len(set(keys)) or any(key not in allowed for key in keys):
        raise HTTPException(422,'Use the supported analytics filters once each')
    today=datetime.now(timezone.utc).date()
    start=from_date or today-timedelta(days=29)
    end=to_date or today+timedelta(days=1)
    if not 1<=(end-start).days<=366:
        raise HTTPException(422,'Choose a UTC date range of 1–366 days; the end date is exclusive')
    filters=Filters(from_date=start,to_date=end,payment_status=payment_status,fulfillment_status=fulfillment_status,
        payment_method=payment_method,include_gateway_test=include_gateway_test,page=page,page_size=page_size)
    return await domain.report(db,business_id,filters)
