"""Optional first-party measurement. No customer facts or financial writers.

All mutations use the caller's transaction. Policy changes serialize on Business
then Policy. Product events take Product KEY SHARE before Policy then Context:
the event's tenant FK also needs that lock, so taking it first avoids an implicit
Product/Context inversion with canonical checkout. No Storefront locks here.
"""
import hashlib
import hmac
import json
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.activity_v1 import (ActivityContext, ActivityEvent, ActivityGap,
    ActivityPolicy, ActivityPolicyCommand, ActivitySource, OrderActivity)
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.seller import Seller
from app.schemas.activity_v1 import ActivityRead, ContextRead, EventRead, PolicyRead, PolicyReceipt
from app.services.identity import require_business_access

ROLE='public_activity_context'
PURPOSE='storefront.activity.v1'
AUDIENCE='munimjee.activity.v1'
CONTEXT_MINUTES=30
RETENTION_DAYS=90
CONTEXT_CAP=300
PRODUCT_CAP=200


def enabled():
    return bool(settings.V1_ACTIVITY_ENABLED and settings.V1_ACTIVITY_RETENTION_READY)


def public_enabled():
    return enabled() and settings.V1_STOREFRONT_ENABLED


async def clock(db):
    return await db.scalar(select(func.clock_timestamp()))


async def owner(db, actor, business_id):
    if actor.auth_method!='v1_user':
        raise HTTPException(401,'Native V1 sign-in required')
    access=await require_business_access(db,actor,business_id,'analytics.read')
    if access.role!='owner':
        raise HTTPException(403,'Only the current business owner can change measurement')
    return access


async def policy_read(db,business_id,actor):
    access=await require_business_access(db,actor,business_id,'analytics.read')
    row=(await db.execute(select(ActivityPolicy.mode,ActivityPolicy.revision,ActivityPolicy.updated_at)
        .where(ActivityPolicy.business_id==business_id).execution_options(autoflush=False))).one_or_none()
    return PolicyRead(business_id=business_id,mode=row.mode if row else 'off',
        revision=row.revision if row else 0,changed_at=row.updated_at if row else None,
        can_change=access.role=='owner',collector_available=public_enabled())


def receipt(row,replayed):
    return PolicyReceipt(business_id=row.business_id,idempotency_key=row.idempotency_key,
        mode=row.mode,applied_revision=row.revision,accepted_at=row.created_at,replayed=replayed)


async def change_policy(db,business_id,actor,payload):
    await owner(db,actor,business_id)
    # Compatible with FK KEY SHARE, while serializing all policy writers.
    await db.scalar(select(Business.id).where(Business.id==business_id)
        .with_for_update(key_share=True))
    await owner(db,actor,business_id)
    digest=hashlib.sha256(json.dumps(payload.model_dump(mode='json'),sort_keys=True,
        separators=(',',':')).encode()).hexdigest()
    previous=await db.get(ActivityPolicyCommand,(business_id,payload.idempotency_key))
    if previous:
        if previous.actor_user_id!=actor.user_id or not hmac.compare_digest(previous.request_hash,digest):
            raise HTTPException(409,{'code':'measurement_key_conflict','message':'This measurement command key has different details.'})
        return receipt(previous,True)
    policy=await db.scalar(select(ActivityPolicy).where(ActivityPolicy.business_id==business_id)
        .with_for_update().execution_options(populate_existing=True))
    revision=policy.revision if policy else 0
    if revision!=payload.expected_revision:
        raise HTTPException(409,{'code':'measurement_policy_stale','message':'Measurement changed. Reload and review the current policy.'})
    accepted=await clock(db)
    if policy is None:
        policy=ActivityPolicy(business_id=business_id,mode=payload.mode,revision=1,updated_at=accepted)
        db.add(policy)
    else:
        policy.mode=payload.mode;policy.revision+=1;policy.updated_at=accepted
    command=ActivityPolicyCommand(business_id=business_id,idempotency_key=payload.idempotency_key,
        actor_user_id=actor.user_id,request_hash=digest,mode=payload.mode,revision=revision+1,
        notice_version='first-party.v1',created_at=accepted)
    db.add(command)
    await db.flush()
    return receipt(command,False)


async def public_business(db,slug):
    business_id=await db.scalar(select(Storefront.seller_id).join(Business,Business.id==Storefront.seller_id)
        .join(Seller,Seller.id==Storefront.seller_id).where(Storefront.slug==slug,
        Storefront.published.is_(True),Business.is_active.is_(True),Seller.is_active.is_(True))
        .execution_options(autoflush=False))
    if business_id is None:raise HTTPException(404,'Store not found')
    return business_id


async def locked_policy(db,business_id,*,write=False):
    return await db.scalar(select(ActivityPolicy).where(ActivityPolicy.business_id==business_id)
        .with_for_update(read=not write).execution_options(populate_existing=True))


def classification(mode,*,native=False):
    if native:return 'test','native_context'
    if settings.APP_ENV not in {'production','prod'}:return 'test','nonproduction'
    if mode=='test':return 'test','policy_test'
    return 'live','live_policy'


def issue_capability(row):
    claims={'role':ROLE,'purpose':PURPOSE,'aud':AUDIENCE,'sub':str(row.id),
        'business_id':str(row.business_id),'iat':int(row.started_at.timestamp()),
        'exp':int(row.expires_at.timestamp())}
    return jwt.encode(claims,settings.SECRET_KEY,algorithm=settings.JWT_ALGORITHM)


def decode_capability(value):
    try:
        if not isinstance(value,str) or not value.startswith('Bearer ') or len(value)>4200:raise ValueError()
        claims=jwt.decode(value[7:],settings.SECRET_KEY,algorithms=[settings.JWT_ALGORITHM],audience=AUDIENCE,
            options={'require_exp':True,'require_sub':True,'require_aud':True,'require_iat':True})
        if (set(claims)!={'role','purpose','aud','sub','business_id','iat','exp'} or claims['role']!=ROLE
                or claims['purpose']!=PURPOSE or claims['aud']!=AUDIENCE
                or type(claims['iat']) is not int or type(claims['exp']) is not int
                or claims['exp']-claims['iat']!=CONTEXT_MINUTES*60
                or claims['iat']>int(datetime.now(timezone.utc).timestamp())+5):raise ValueError()
        UUID(claims['sub']);UUID(claims['business_id'])
        return claims
    except (JWTError,ValueError,TypeError,KeyError,AttributeError):
        raise HTTPException(401,'Measurement context is invalid or expired')


def context_result(row):
    return ContextRead(state='ready',context_id=row.id,expires_at=row.expires_at,capability=issue_capability(row))


async def gap(db,business_id,kind,at,reason):
    await db.execute(insert(ActivityGap).values(business_id=business_id,classification=kind,
        minute=at.replace(second=0,microsecond=0),reason=reason).on_conflict_do_nothing())


async def start_context(db,business_id,payload,*,native=False):
    if not public_enabled():return ContextRead(state='disabled')
    policy=await locked_policy(db,business_id,write=True)
    if policy is None or policy.mode=='off':return ContextRead(state='disabled')
    existing=await db.scalar(select(ActivityContext).where(ActivityContext.business_id==business_id,
        ActivityContext.idempotency_key==payload.idempotency_key))
    at=await clock(db)
    if existing:
        # Neither changing native context nor policy may promote/restart a key.
        if existing.expires_at<=at:return ContextRead(state='expired')
        if (native or policy.mode=='test') and existing.classification=='live':return ContextRead(state='excluded')
        return context_result(existing)
    kind,reason=classification(policy.mode,native=native)
    minute=at.replace(second=0,microsecond=0)
    count=await db.scalar(select(func.count()).select_from(ActivityContext).where(
        ActivityContext.business_id==business_id,ActivityContext.classification==kind,
        ActivityContext.started_at>=minute,ActivityContext.started_at<minute+timedelta(minutes=1)))
    if count>=CONTEXT_CAP:
        await gap(db,business_id,kind,at,'context_capacity')
        return ContextRead(state='capped')
    row=ActivityContext(business_id=business_id,idempotency_key=payload.idempotency_key,
        classification=kind,reason=reason,policy_revision=policy.revision,started_at=at,
        expires_at=at+timedelta(minutes=CONTEXT_MINUTES),retained_until=at+timedelta(days=RETENTION_DAYS))
    db.add(row);await db.flush()
    return context_result(row)


async def accept_event(db,business_id,authorization,payload,*,native=False):
    claims=decode_capability(authorization)
    if claims['business_id']!=str(business_id):raise HTTPException(401,'Measurement context is invalid or expired')
    if not public_enabled():return EventRead(state='disabled',replayed=False)
    if payload.product_id is not None:
        # The INSERT tenant FK needs Product KEY SHARE anyway. Acquire before
        # Context (matching checkout's Product→Policy→Context), not implicitly
        # at flush after Context: that order can deadlock stock reservations.
        product=await db.scalar(select(Product.id).where(Product.seller_id==business_id,
            Product.id==payload.product_id,Product.active.is_(True))
            .with_for_update(read=True,key_share=True))
        if product is None:raise HTTPException(404,'Product not found')
    policy=await locked_policy(db,business_id)
    if policy is None or policy.mode=='off':return EventRead(state='disabled',replayed=False)
    row=await db.scalar(select(ActivityContext).where(ActivityContext.business_id==business_id,
        ActivityContext.id==UUID(claims['sub'])).with_for_update().execution_options(populate_existing=True))
    at=await clock(db)
    if (row is None or row.expires_at<=at or int(row.expires_at.timestamp())!=claims['exp']
            or (native and row.classification=='live')):
        raise HTTPException(401,'Measurement context is invalid or expired')
    if policy.mode=='test' and row.classification=='live':return EventRead(state='disabled',replayed=False)
    existing=await db.scalar(select(ActivityEvent.id).where(ActivityEvent.context_id==row.id,
        ActivityEvent.event_kind==payload.event_kind,ActivityEvent.product_id==payload.product_id))
    if existing:return EventRead(state='accepted',replayed=True)
    if payload.product_id is not None:
        product=await db.scalar(select(Product.id).join(CatalogueActivation,
            (CatalogueActivation.business_id==Product.seller_id)&(CatalogueActivation.product_id==Product.id))
            .where(Product.seller_id==business_id,Product.id==payload.product_id,Product.active.is_(True),
                select(CatalogueSKU.id).where(CatalogueSKU.business_id==business_id,
                    CatalogueSKU.product_id==Product.id,CatalogueSKU.active.is_(True)).exists()))
        if product is None:raise HTTPException(404,'Product not found')
        count=await db.scalar(select(func.count()).select_from(ActivityEvent).where(
            ActivityEvent.context_id==row.id,ActivityEvent.event_kind=='product_view'))
        if count>=PRODUCT_CAP:
            row.lossy=True
            await gap(db,business_id,row.classification,at,'event_capacity')
            await db.flush()
            return EventRead(state='capped',replayed=False)
    db.add(ActivityEvent(business_id=business_id,context_id=row.id,event_kind=payload.event_kind,
        product_id=payload.product_id,created_at=at))
    await db.flush()
    return EventRead(state='accepted',replayed=False)


async def record_order(db,order,*,context_id=None,authorization=None,native=False):
    """ONLY for a newly accepted canonical order, before its caller commits.

    An accepted replay must never call this helper to backfill provenance. Proof
    failures become unknown, without modifying or denying the financial order.
    The helper does not accept client classification or a replay override.
    """
    if await db.get(OrderActivity,order.id) is not None:return
    kind,reason,linked='unknown','unproven_context',None
    if (order.gateway_credentials or {}).get('mode')=='test':kind,reason='test','gateway_test'
    elif native or settings.APP_ENV not in {'production','prod'}:kind,reason='test','nonproduction'
    elif not public_enabled():reason='tracking_disabled'
    else:
        policy=await locked_policy(db,order.seller_id)
        if policy is None or policy.mode=='off':reason='tracking_disabled'
        elif policy.mode=='test':kind,reason='test','nonproduction'
        else:
            try:
                claims=decode_capability(authorization)
                if UUID(claims['sub'])!=context_id or UUID(claims['business_id'])!=order.seller_id:raise ValueError()
                context=await db.scalar(select(ActivityContext).where(ActivityContext.id==context_id,
                    ActivityContext.business_id==order.seller_id).with_for_update(read=True))
                if (context is None or not context.started_at<=order.created_at<context.expires_at
                        or context.expires_at<=await clock(db) or int(context.expires_at.timestamp())!=claims['exp']):raise ValueError()
                kind=context.classification
                if kind in {'live','test'}:
                    reason='live_context' if kind=='live' else 'test_context';linked=context.id
            except (HTTPException,ValueError,TypeError):pass
    db.add(OrderActivity(order_id=order.id,business_id=order.seller_id,classification=kind,
        reason=reason,context_id=linked,accepted_at=order.created_at))
    await db.flush()


SOURCE_LOOKUP={
    'instagram_ingress':text("SELECT created_at FROM instagram_ingress WHERE id=:sid AND seller_id=:bid AND NULLIF(provider_message_id,'') IS NOT NULL"),
    'wa_inbound':text("SELECT created_at FROM whatsapp_messages WHERE id=:sid AND seller_id=:bid AND direction='inbound' AND NULLIF(provider_message_id,'') IS NOT NULL"),
    'wa_outbound':text("SELECT created_at FROM whatsapp_messages WHERE id=:sid AND seller_id=:bid AND direction='outbound'"),
    'comment_action':text("SELECT a.created_at FROM comment_actions a JOIN comment_events e ON e.id=a.event_id AND e.seller_id=a.seller_id WHERE a.id=:sid AND a.seller_id=:bid"),
}


async def record_source(db,business_id,source_kind,source_id,*,origin,is_new,test_evidence=False):
    """Server-only seam for a NEW deduplicated source row, same transaction.

    No public/native endpoint accepts these arguments. Internal producers must
    call only in their actual new-row branch, never a retry/backfill. Explicit
    origin is a code-owned producer fact, not inferred from text/key prefixes.
    This helper's presence does not install producer coverage or enable metrics.
    No customer/body/provider scalar is fetched or copied into this ledger.
    """
    if type(is_new) is not bool or type(test_evidence) is not bool:
        raise ValueError('Internal source flags must be booleans')
    if source_kind not in SOURCE_LOOKUP or origin not in {'inbound','automated','operator','unknown'}:
        raise ValueError('Unsupported internal activity source')
    if (source_kind in {'instagram_ingress','wa_inbound'})!=(origin=='inbound') and origin!='unknown':
        raise ValueError('Source kind and internal origin disagree')
    if not is_new or not enabled():return False
    if await db.get(ActivitySource,(business_id,source_kind,source_id)) is not None:return False
    policy=await locked_policy(db,business_id)
    if policy is None or policy.mode=='off':return False
    active=await db.scalar(select(Business.id).join(Seller,Seller.id==Business.id).where(
        Business.id==business_id,Business.is_active.is_(True),Seller.is_active.is_(True)).execution_options(autoflush=False))
    if active is None:return False
    source_time=await db.scalar(SOURCE_LOOKUP[source_kind],{'bid':business_id,'sid':source_id})
    at=await clock(db)
    if source_time is None or source_time<policy.updated_at or source_time>at:return False
    kind=('test' if test_evidence or policy.mode=='test' or settings.APP_ENV not in {'production','prod'}
        else 'unknown' if origin in {'operator','unknown'} else 'live')
    # Concurrency-safe first association wins. Exact producer replay never
    # reclassifies an existing fact after policy/credentials/environment change.
    result=await db.execute(insert(ActivitySource).values(business_id=business_id,source_kind=source_kind,
        source_id=source_id,classification=kind,origin=origin,created_at=source_time,
        retained_until=source_time+timedelta(days=RETENTION_DAYS)).on_conflict_do_nothing()
        .returning(ActivitySource.source_id))
    return result.scalar_one_or_none() is not None


async def delete_expired(db,*,batch_size=500):
    """Bounded scheduler seam. No deployed schedule is implied by this helper."""
    if type(batch_size) is not int or not 1<=batch_size<=1000:raise ValueError('Use a batch size from 1 to 1000')
    at=await clock(db);deleted={}
    for model,column in ((ActivityContext,ActivityContext.retained_until),
            (ActivitySource,ActivitySource.retained_until),(ActivityGap,ActivityGap.minute)):
        expiry=at-timedelta(days=RETENTION_DAYS) if model is ActivityGap else at
        # SKIP LOCKED avoids waiting for ingestion/another cleanup worker. The
        # database independently refuses deleting unexpired raw facts.
        primary=list(model.__table__.primary_key.columns)
        rows=(await db.execute(select(*primary).where(column<=expiry).limit(batch_size)
            .with_for_update(skip_locked=True))).all()
        for row in rows:
            await db.execute(delete(model).where(*(col==value for col,value in zip(primary,row))))
        deleted[model.__tablename__]=len(rows)
    return deleted


# All counts, policy intervals and canonical current states use ONE PostgreSQL
# statement snapshot. No credential/provider/customer scalar leaves PostgreSQL.
REPORT=text('''
WITH bounds AS (
 SELECT CAST(:bid AS uuid) AS bid,CAST(:start AS timestamptz) AS lo,
 LEAST(CAST(:end AS timestamptz),statement_timestamp()) AS hi,
 statement_timestamp() AS stamp,statement_timestamp()-interval '2160 hours' AS retained
), history AS (
 SELECT mode,created_at AS since,LEAD(created_at,1,(SELECT stamp FROM bounds))
 OVER(ORDER BY revision) AS until FROM v1_activity_policy_commands WHERE business_id=CAST(:bid AS uuid)
), intervals AS (
 SELECT GREATEST(since,lo,retained) AS lo,LEAST(until,hi) AS hi
 FROM history CROSS JOIN bounds WHERE mode='live' AND since<hi AND until>GREATEST(lo,retained)
), coverage AS (
 SELECT COALESCE(SUM(EXTRACT(EPOCH FROM hi-lo)),0) AS seconds,
 MIN(lo) AS since,MAX(hi) AS until FROM intervals
), expired AS (
 SELECT retained_until AS expiry FROM v1_activity_contexts CROSS JOIN bounds b WHERE business_id=b.bid AND retained_until<=b.stamp
 UNION ALL SELECT retained_until FROM v1_activity_sources CROSS JOIN bounds b WHERE business_id=b.bid AND retained_until<=b.stamp
 UNION ALL SELECT minute+interval '2160 hours' FROM v1_activity_gaps CROSS JOIN bounds b WHERE business_id=b.bid AND minute+interval '2160 hours'<=b.stamp
), contexts AS (
 SELECT c.id,c.lossy FROM v1_activity_contexts c CROSS JOIN bounds b
 WHERE c.business_id=b.bid AND c.classification='live' AND c.started_at>=GREATEST(b.lo,b.retained) AND c.started_at<b.hi
), linked AS (
 SELECT a.order_id,a.context_id FROM v1_order_activity a JOIN contexts c ON c.id=a.context_id
 JOIN commerce_orders o ON o.id=a.order_id AND o.seller_id=a.business_id
 WHERE a.classification='live' AND COALESCE(o.gateway_credentials->>'mode','')<>'test'
), orders AS (
 SELECT o.currency,o.total,o.payment_method,o.payment_status,o.fulfillment_status,
 NULLIF(o.gateway_payment_id,'') IS NOT NULL AS captured,
 CASE WHEN o.gateway_credentials->>'mode'='test' OR a.classification='test' THEN 'test'
 WHEN a.classification='live' THEN 'live' ELSE 'unknown' END AS class
 FROM commerce_orders o CROSS JOIN bounds b LEFT JOIN v1_order_activity a
 ON a.order_id=o.id AND a.business_id=o.seller_id
 WHERE o.seller_id=b.bid AND o.created_at>=b.lo AND o.created_at<b.hi
), production AS (SELECT * FROM orders WHERE class='live'), money AS (
 SELECT currency,SUM(total)::text AS placed_order_value_minor,
 COALESCE(SUM(total) FILTER(WHERE payment_method='razorpay' AND payment_status='paid' AND captured),0)::text AS online_paid_minor,
 COALESCE(SUM(total) FILTER(WHERE payment_method='cod' AND payment_status='collected'),0)::text AS cod_collected_minor,
 COALESCE(SUM(total) FILTER(WHERE payment_method='razorpay' AND payment_status='review_required' AND captured),0)::text AS captured_review_minor
 FROM production GROUP BY currency
)
SELECT jsonb_build_object(
 'stamp',b.stamp,'end',b.hi,'retained',b.retained,
 'current_mode',COALESCE((SELECT mode FROM v1_activity_policies WHERE business_id=b.bid),'off'),
 'history_started',EXISTS(SELECT 1 FROM history WHERE mode<>'off'),
 'cleanup_overdue_rows',(SELECT COUNT(*) FROM expired),
 'cleanup_lag_seconds',(SELECT FLOOR(EXTRACT(EPOCH FROM b.stamp-MIN(expiry)))::bigint FROM expired),
 'covered_seconds',c.seconds,'available_from',c.since,'available_to',c.until,
 'expected_seconds',GREATEST(EXTRACT(EPOCH FROM b.hi-b.lo),0),
 'retention_truncated',b.lo<b.retained,
 'capped',EXISTS(SELECT 1 FROM v1_activity_gaps g WHERE g.business_id=b.bid AND g.classification='live'
   AND g.minute<b.hi AND g.minute+interval '1 minute'>GREATEST(b.lo,b.retained)) OR EXISTS(SELECT 1 FROM contexts WHERE lossy),
 'visits',(SELECT COUNT(*) FROM contexts),
 'product_views',(SELECT COUNT(*) FROM v1_activity_events e JOIN contexts c ON c.id=e.context_id WHERE e.event_kind='product_view'),
 'checkout_starts',(SELECT COUNT(*) FROM v1_activity_events e JOIN contexts c ON c.id=e.context_id WHERE e.event_kind='checkout_opened'),
 'accepted_placements',(SELECT COUNT(*) FROM linked),
 'converted',(SELECT COUNT(DISTINCT context_id) FROM linked),
 'production_orders',(SELECT jsonb_build_object('placed',COUNT(*),
   'online_paid',COUNT(*) FILTER(WHERE payment_method='razorpay' AND payment_status='paid' AND captured),
   'cod_collected',COUNT(*) FILTER(WHERE payment_method='cod' AND payment_status='collected'),
   'cancelled',COUNT(*) FILTER(WHERE fulfillment_status='cancelled' OR payment_status='cancelled'),
   'expired',COUNT(*) FILTER(WHERE payment_status='expired')) FROM production),
 'money',COALESCE((SELECT jsonb_agg(to_jsonb(money) ORDER BY currency) FROM money),'[]'::jsonb),
 'excluded_test',(SELECT COUNT(*) FROM orders WHERE class='test'),
 'excluded_unknown',(SELECT COUNT(*) FROM orders WHERE class='unknown'),
 'classified_started',EXISTS(SELECT 1 FROM v1_order_activity WHERE business_id=b.bid)
) FROM bounds b CROSS JOIN coverage c
''')


async def report(db,business_id,from_date,to_date):
    start=datetime.combine(from_date,time.min,tzinfo=timezone.utc)
    end=datetime.combine(to_date,time.min,tzinfo=timezone.utc)
    data=await db.scalar(REPORT,{'bid':business_id,'start':start,'end':end})
    reasons=[]
    if not public_enabled():reasons.append('collector_disabled')
    if not data['history_started']:reasons.append('measurement_not_started')
    elif data['covered_seconds']==0:reasons.append('measurement_off' if data['current_mode']=='off' else 'uncovered_interval')
    elif data['covered_seconds']<data['expected_seconds']:reasons.append('uncovered_interval')
    if data['retention_truncated']:reasons.append('retention_truncated')
    if data['capped']:reasons.append('ingestion_capped')
    state=('disabled' if not public_enabled() or (data['current_mode']=='off' and data['covered_seconds']==0)
        else 'not_started' if not data['history_started'] else 'partial' if reasons else 'available')
    observed=data['covered_seconds']>0
    counts={field:data[field] if observed else None for field in ('visits','product_views','checkout_starts','accepted_placements')}
    numerator=data['converted'] if observed else None
    denominator=data['visits'] if observed else None
    unavailable=(('collector_disabled' if not public_enabled() else 'measurement_not_started' if not data['history_started']
        else 'measurement_off' if not observed and data['current_mode']=='off' else 'partial_coverage') if reasons
        else 'no_observed_contexts' if not denominator else None)
    percentage=None if unavailable else format((Decimal(numerator)*100/Decimal(denominator)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'.2f')
    production=data['production_orders']
    if not data['classified_started']:
        production={field:None for field in production}
    production.update(state='not_started' if not data['classified_started'] else 'partial' if data['excluded_unknown'] else 'available',
        currency_totals=data['money'],excluded_test=data['excluded_test'],excluded_unclassified=data['excluded_unknown'])
    return ActivityRead(business_id=business_id,from_date=from_date,to_date=to_date,generated_at=data['stamp'],
        coverage={'state':state,'measurement_mode':data['current_mode'],'available_from':data['available_from'],
            'available_to':data['available_to'],'reasons':reasons,'retention_ready':settings.V1_ACTIVITY_RETENTION_READY,
            'cleanup_overdue_rows':data['cleanup_overdue_rows'],'cleanup_lag_seconds':data['cleanup_lag_seconds']},counts=counts,
        conversion={'numerator':numerator,'denominator':denominator,'percentage':percentage,'unavailable_reason':unavailable},
        production_orders=production,channel_activity={'reason':'producer_not_installed'})
