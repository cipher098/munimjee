"""Audited order-first review. Resume reads; replacement uses the sole ingress worker."""
from datetime import timedelta
from uuid import UUID,uuid4
from fastapi import HTTPException
from jose import jwt,JWTError
from sqlalchemy import select,or_
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.models.parcel_tracking import OrderParcelLink,ParcelAudit,ParcelNotification
from app.services import parcel_tracking as tracking
from app.services.parcel_connector import ParcelAdapter,ConnectorUnavailable,normalize,timestamp,configuration
from app.services.identity import require_business_access

ACTIONS={'resume_tracking':'seller_resumed_tracking','close_link':'seller_closed_link','replace':'seller_replaced_link'}

def link_fingerprint(link):
    return tracking.digest({column.name:getattr(link,column.name) for column in OrderParcelLink.__table__.columns})


def connector_fingerprint(connector):
    return tracking.digest([connector.id,connector.business_id,connector.instance_id,connector.origin,connector.credential_ref,configuration(connector)])

async def context(db,actor,business_id,order_id,link_id,*,lock=False,authority=None):
    _,order=await tracking.access_order(db,actor,business_id,order_id,write=True,lock=lock)
    if authority:await authority()
    stmt=select(OrderParcelLink).where(OrderParcelLink.id==link_id,OrderParcelLink.business_id==business_id,OrderParcelLink.order_id==order_id).execution_options(populate_existing=True)
    if lock:stmt=stmt.with_for_update()
    link=await db.scalar(stmt)
    if not link:raise HTTPException(404,'Parcel link not found')
    if authority:await authority()
    await require_business_access(db,actor,business_id,'orders.write')
    return order,link


def expected(order,link,payload):
    if payload.expected_order_fingerprint!=tracking.fingerprint(order) or payload.expected_link_fingerprint!=link_fingerprint(link):
        raise HTTPException(409,{'code':'parcel_review_context_changed','message':'The order or tracking changed. Refresh and review the current facts before continuing.'})


def confirmation(payload):
    if payload.confirmed is not True or payload.remote_effects_acknowledged is not True:
        raise HTTPException(422,'Confirm the label, selected order and possible earlier remote effects before continuing')


def decode(token,actor,business_id,order_id,link_id,purpose):
    try:
        if not isinstance(token,str):raise ValueError()
        value=jwt.decode(token,settings.SECRET_KEY,algorithms=['HS256'])
        if value['purpose']!=purpose or value['actor']!=str(actor.user_id) or value['business']!=str(business_id) or value['order']!=str(order_id) or value['link']!=str(link_id):raise ValueError()
        if any(key not in value for key in ('order_fingerprint','link_fingerprint','connector_fingerprint','remote_id','courier','awb','snapshot_hash')):raise ValueError()
        return value
    except (JWTError,KeyError,ValueError,TypeError):
        raise HTTPException(409,{'code':'parcel_review_preview_expired_or_invalid','message':'This review preview expired or changed before acceptance. Review the current label and tracking again.'}) from None


def candidate_claims(actor,order,link,connector,purpose,scan_id,courier,awb,snapshot):
    return {'purpose':purpose,'actor':str(actor.user_id),'business':str(link.business_id),'order':str(order.id),'link':str(link.id),
        'order_fingerprint':tracking.fingerprint(order),'link_fingerprint':link_fingerprint(link),'connector_fingerprint':connector_fingerprint(connector),
        'courier':courier,'awb':awb,'remote_id':snapshot['shipment']['id'] if snapshot else None,'snapshot_hash':tracking.digest(snapshot) if snapshot else None,
        'scan_id':str(scan_id),'exp':tracking.now()+timedelta(minutes=5)}


def snapshot_usable(snapshot,link,*,resume=False):
    shipment=snapshot['shipment']
    if shipment['revoked'] or shipment['error_code'] or shipment['status'] not in tracking.STATES or (resume and snapshot['revision']<link.snapshot_revision):
        raise HTTPException(409,'This tracker record still needs manual review. Nothing was changed.')
    if resume and (shipment['courier_id']!=link.courier_id or shipment['awb']!=link.awb or (link.remote_id and shipment['id']!=str(link.remote_id))):
        raise HTTPException(409,'The saved parcel identity does not match the current tracker. Keep it paused for manual review.')
    checked=timestamp(shipment['checked_at'])
    if (shipment['checked_at'] is not None and checked is None) or (checked and checked>tracking.now()+timedelta(minutes=5)) or (resume and link.checked_at and (not checked or checked<link.checked_at)):
        raise HTTPException(409,'The tracker check is older or unverified. Keep this parcel paused until its current facts can be reviewed.')


async def resolved_snapshot(adapter,courier,awb):
    result=await adapter.resolve(courier,awb)
    if result['state']=='manual_review':raise HTTPException(409,'This tracking number is unowned or ambiguous. It requires manual tracker review; nothing was associated.')
    return result.get('snapshot') if result['state']=='existing' else None


async def preview(db,actor,business_id,order_id,link_id,payload,*,replacement=False,authority=None):
    order,link=await context(db,actor,business_id,order_id,link_id,authority=authority);expected(order,link,payload)
    connector=await tracking.connector_for(db,business_id)
    if connector.id!=link.connector_id:raise HTTPException(409,'The trusted parcel connector changed. Review configuration first.')
    courier,awb=(payload.courier_id,normalize(payload.courier_id,payload.awb)) if replacement else (link.courier_id,link.awb)
    if replacement and (courier,awb)==(link.courier_id,link.awb):raise HTTPException(409,'This is the same parcel. Review and resume its saved association instead of replacing it.')
    old_order,old_link=tracking.fingerprint(order),link_fingerprint(link);binding=connector_fingerprint(connector)
    remote_id=link.remote_id
    await db.commit()
    try:
        adapter=ParcelAdapter(connector)
        snapshot=await resolved_snapshot(adapter,courier,awb) if replacement or not remote_id else await adapter.read(remote_id)
    except ConnectorUnavailable:raise HTTPException(503,'Tracker facts could not be confirmed. Nothing was changed; retry this review later.') from None
    order,link=await context(db,actor,business_id,order_id,link_id,authority=authority)
    connector=await tracking.connector_for(db,business_id)
    if old_order!=tracking.fingerprint(order) or old_link!=link_fingerprint(link) or binding!=connector_fingerprint(connector):
        raise HTTPException(409,{'code':'parcel_review_context_changed','message':'The order, connector or tracking changed during review. Refresh before continuing.'})
    if not replacement and snapshot is None:raise HTTPException(409,'No owned tracker record is confirmed. Earlier enrollment may still be unknown. Keep it paused or explicitly close/replace this local association.')
    if snapshot:snapshot_usable(snapshot,link,resume=not replacement)
    claims=candidate_claims(actor,order,link,connector,'parcel_replacement' if replacement else 'parcel_review',payload.scan_id,courier,awb,snapshot)
    return {'order':tracking.order_view(order),'link_id':str(link.id),'link_fingerprint':link_fingerprint(link),'courier_id':courier,'awb':awb,
        'existing':snapshot is not None,'tracking':{'status':snapshot['shipment']['status'],'checked_at':snapshot['shipment']['checked_at']} if snapshot else None,
        'candidate_token':jwt.encode(claims,settings.SECRET_KEY,algorithm='HS256'),'expires_in':300}


async def receipt(db,actor,business_id,order_id,link_id,payload,action):
    previous=await db.scalar(select(ParcelAudit).where(ParcelAudit.business_id==business_id,ParcelAudit.idempotency_key==payload.idempotency_key))
    if not previous:return None
    body_hash=tracking.digest(payload.model_dump(mode='json'))
    if previous.actor_id!=actor.user_id or previous.action!=ACTIONS[action] or previous.details.get('request_hash')!=body_hash or previous.details.get('source_link_id')!=str(link_id) or previous.details.get('order_id')!=str(order_id):
        raise HTTPException(409,'This command identity was already used by another review or different facts')
    result_id=UUID(previous.details['result_link_id'])
    result=await db.scalar(select(OrderParcelLink).where(OrderParcelLink.id==result_id,OrderParcelLink.business_id==business_id,OrderParcelLink.order_id==order_id).execution_options(populate_existing=True))
    if not result:raise HTTPException(409,'The accepted review result requires operator investigation')
    return result,True


async def audit(db,actor,source,result,payload,action,before):
    from app.models.whatsapp import WhatsAppMessage
    from sqlalchemy import func
    withheld=[str(value) for value in (await db.scalars(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==source.business_id,WhatsAppMessage.idempotency_key.like('parcel:'+str(result.id)+':%')))).all()]
    db.add(ParcelAudit(created_at=func.clock_timestamp(),business_id=source.business_id,link_id=result.id,actor_id=actor.user_id,action=ACTIONS[action],idempotency_key=payload.idempotency_key,
        details={'request_hash':tracking.digest(payload.model_dump(mode='json')),'source_link_id':str(source.id),'result_link_id':str(result.id),'order_id':str(source.order_id),
        'reason':payload.reason,'before':before,'after':{'state':result.state,'tracking_state':result.tracking_state,'remote_id':str(result.remote_id) if result.remote_id else None},'remote_effects_acknowledged':True,'notifications':'suppressed_review_baseline','withheld_outbox_ids':withheld}))
    try:await db.flush()
    except IntegrityError:raise HTTPException(409,'A review command or parcel association changed. Refresh before retrying.') from None


def before_view(link):
    return {'state':link.state,'tracking_state':link.tracking_state,'remote_id':str(link.remote_id) if link.remote_id else None,'fingerprint':link_fingerprint(link),'had_active_lease':link.lease_token is not None}


async def baseline(db,link):
    milestone=link.tracking_state
    if milestone in {'in_transit','out_for_delivery','delivered','returned'}:
        from sqlalchemy.dialects.postgresql import insert
        await db.execute(insert(ParcelNotification).values(id=uuid4(),business_id=link.business_id,link_id=link.id,milestone=milestone,decision='skipped',reason='reviewed_without_notification').on_conflict_do_nothing(constraint='v1_parcel_milestone_once'))


async def command(db,actor,business_id,order_id,link_id,payload,*,replacement=False,authority=None):
    action='replace' if replacement else payload.action
    order,link=await context(db,actor,business_id,order_id,link_id,lock=True,authority=authority)
    previous=await receipt(db,actor,business_id,order_id,link_id,payload,action)
    if previous:return previous
    confirmation(payload);expected(order,link,payload)
    before=before_view(link)
    if action=='close_link':
        if link.state=='unlinked':raise HTTPException(409,'This association is already closed. Refresh its review history.')
        link.state,link.error_code='unlinked','seller_closed_link';link.lease_token,link.lease_until=None,None;link.revision+=1
        await audit(db,actor,link,link,payload,action,before)
        return link,False
    purpose='parcel_replacement' if replacement else 'parcel_review'
    claims=decode(payload.candidate_token,actor,business_id,order_id,link_id,purpose)
    connector=await tracking.connector_for(db,business_id)
    if claims['order_fingerprint']!=tracking.fingerprint(order) or claims['link_fingerprint']!=link_fingerprint(link) or claims['connector_fingerprint']!=connector_fingerprint(connector):
        raise HTTPException(409,{'code':'parcel_review_context_changed','message':'The reviewed order, parcel or connector changed. Review the current facts again.'})
    remote_id=claims['remote_id'];courier,awb=claims['courier'],claims['awb']
    await db.commit()  # No review mutation exists yet; never hold rows across HTTP.
    try:
        adapter=ParcelAdapter(connector)
        snapshot=await resolved_snapshot(adapter,courier,awb) if replacement else await adapter.read(UUID(remote_id))
    except ConnectorUnavailable:raise HTTPException(503,'Tracker facts could not be confirmed. Check this same saved review again.') from None
    order,link=await context(db,actor,business_id,order_id,link_id,lock=True,authority=authority)
    previous=await receipt(db,actor,business_id,order_id,link_id,payload,action)
    if previous:return previous
    claims=decode(payload.candidate_token,actor,business_id,order_id,link_id,purpose);expected(order,link,payload)
    connector=await tracking.connector_for(db,business_id)
    if claims['connector_fingerprint']!=connector_fingerprint(connector) or claims['snapshot_hash']!=(tracking.digest(snapshot) if snapshot else None):
        raise HTTPException(409,{'code':'parcel_review_context_changed','message':'The tracker or connector changed after preview. Check the current facts again.'})
    if snapshot:snapshot_usable(snapshot,link,resume=not replacement)
    if not replacement:
        if snapshot is None:raise HTTPException(409,'This parcel still needs manual review')
        conflicts=await db.scalar(select(OrderParcelLink.id).where(OrderParcelLink.id!=link.id,OrderParcelLink.state!='unlinked',or_(
            (OrderParcelLink.business_id==business_id)&(OrderParcelLink.order_id==order_id),
            (OrderParcelLink.connector_id==connector.id)&(OrderParcelLink.courier_id==courier)&(OrderParcelLink.awb==awb))))
        if conflicts:raise HTTPException(409,'Another active order or parcel association changed. Review it first.')
        link.lease_token,link.lease_until=None,None
        # Explicit review may accept a newer contradictory carrier status. Keep all
        # earlier observations; this never changes order fulfillment or payment.
        link.tracking_state='awaiting_update';link.checked_at=None;link.error_code=None;link.remote_id=UUID(snapshot['shipment']['id'])
        link.state='linked';link.order_fingerprint=tracking.fingerprint(order)
        await tracking.reconcile_snapshot(db,link,snapshot,notify=False)
        await baseline(db,link);link.next_poll_at=tracking.now()+timedelta(minutes=5)
        await audit(db,actor,link,link,payload,action,before)
        return link,False
    if (courier,awb)==(link.courier_id,link.awb):raise HTTPException(409,'The same parcel must be reviewed and resumed, not replaced')
    if order.fulfillment_status=='cancelled' or order.payment_status in {'cancelled','expired','review_required'}:raise HTTPException(409,'This order needs payment or fulfillment review before replacement')
    # Do not transfer an earlier parcel from another order, even if closed. A
    # recycled tracking number needs a separate explicit ownership process.
    conflicts=await db.scalar(select(OrderParcelLink.id).where(OrderParcelLink.id!=link.id,or_(
        (OrderParcelLink.business_id==business_id)&(OrderParcelLink.order_id==order_id)&(OrderParcelLink.state!='unlinked'),
        (OrderParcelLink.connector_id==connector.id)&(OrderParcelLink.courier_id==courier)&(OrderParcelLink.awb==awb))))
    if conflicts:raise HTTPException(409,'This order or tracking number already has another association. Manual ownership review is required.')
    link.state,link.error_code='unlinked','seller_replaced_link';link.lease_token,link.lease_until=None,None;link.revision+=1
    await db.flush()  # Retire the old partial-unique entry before inserting its successor.
    result=OrderParcelLink(id=uuid4(),business_id=business_id,order_id=order_id,connector_id=connector.id,actor_id=actor.user_id,
        idempotency_key=payload.idempotency_key,request_hash=tracking.digest(payload.model_dump(mode='json')),order_fingerprint=tracking.fingerprint(order),courier_id=courier,awb=awb)
    db.add(result)
    try:await db.flush()
    except IntegrityError:raise HTTPException(409,'Another replacement or parcel association changed. Refresh before retrying.') from None
    await audit(db,actor,link,result,payload,action,before)
    return result,False
