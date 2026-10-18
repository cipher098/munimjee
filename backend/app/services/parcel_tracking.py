"""Durable association and cache synchronization; no courier booking/order transitions."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from uuid import UUID,uuid4
from jose import jwt,JWTError
from fastapi import HTTPException
from sqlalchemy import select,func,or_,and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.models.parcel_tracking import ParcelConnector,OrderParcelLink,ParcelObservation,ParcelNotification,ParcelAudit
from app.models.commerce import CommerceOrder
from app.models.identity import Business
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppTemplate,WhatsAppMessage
from app.services.identity import Actor,require_business_access
from app.services.parcel_connector import ParcelAdapter,ConnectorUnavailable,normalize,timestamp,configuration

now=lambda:datetime.now(timezone.utc)
digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
STATES={'Awaiting update':'awaiting_update','Awaiting courier update':'awaiting_update','In transit':'in_transit','Out for delivery':'out_for_delivery','Delivered':'delivered','Delivery issue':'delivery_issue','Returning':'returning','Returned':'returned'}
RANK={'awaiting_update':0,'unknown':0,'in_transit':1,'delivery_issue':1,'out_for_delivery':2,'returning':3,'delivered':4,'returned':4}


def fingerprint(order):
    return digest({k:getattr(order,k) for k in ('id','seller_id','payment_status','fulfillment_status','updated_at','tracking_number','carrier')})


async def access_order(db,actor,business_id,order_id,*,write=False,lock=False):
    if actor.auth_method!='v1_user':raise HTTPException(403,'Use a native business session')
    access=await require_business_access(db,actor,business_id,'orders.write' if write else 'orders.read')
    statement=select(CommerceOrder).where(CommerceOrder.id==order_id,CommerceOrder.seller_id==business_id).execution_options(populate_existing=True)
    if lock:statement=statement.with_for_update()
    order=await db.scalar(statement)
    if not order:raise HTTPException(404,'Order not found')
    if lock:access=await require_business_access(db,actor,business_id,'orders.write' if write else 'orders.read')
    return access,order


async def connector_for(db,business_id):
    row=await db.scalar(select(ParcelConnector).where(ParcelConnector.business_id==business_id).execution_options(populate_existing=True))
    if not row:raise HTTPException(409,'Parcel tracking is not configured for this business')
    try:configuration(row)
    except ConnectorUnavailable:raise HTTPException(409,'The parcel connector is unavailable; keep the label and retry later') from None
    return row


def order_view(order):
    return {'id':str(order.id),'number':'MJ-'+order.id.hex[:12].upper(),'customer_name':order.customer.get('name',''),
        'payment_status':order.payment_status,'fulfillment_status':order.fulfillment_status,'fingerprint':fingerprint(order)}


async def preview(db,actor,business_id,order_id,payload,*,adapter_factory=ParcelAdapter,authority=None):
    _,order=await access_order(db,actor,business_id,order_id,write=True)
    if order.fulfillment_status=='cancelled' or order.payment_status in {'cancelled','expired','review_required'}:
        raise HTTPException(409,'This order needs review before a parcel can be linked')
    connector=await connector_for(db,business_id);awb=normalize(payload.courier_id,payload.awb);context=order_view(order)
    claims={'purpose':'parcel_candidate','actor':str(actor.user_id),'business':str(business_id),'order':str(order_id),
        'connector':str(connector.id),'connector_version':digest([connector.origin,connector.instance_id,connector.credential_ref]),'courier':payload.courier_id,'awb':awb,'fingerprint':context['fingerprint'],
        'scan_id':str(payload.scan_id),'exp':now()+timedelta(minutes=5)}
    # No order/connector row lock remains held through the remote read.
    await db.commit()
    try:result=await adapter_factory(connector).resolve(payload.courier_id,awb)
    except ConnectorUnavailable:raise HTTPException(503,'Parcel details could not be checked. Nothing was linked.') from None
    if authority:await authority()
    await require_business_access(db,actor,business_id,'orders.write')
    if result['state']=='manual_review' or (result.get('snapshot') or {}).get('shipment',{}).get('revoked'):
        raise HTTPException(409,'This tracking number needs manual review. It was not linked.')
    return {'order':context,'courier_id':payload.courier_id,'awb':awb,'existing':result['state']=='existing',
        'status':result.get('snapshot',{}).get('shipment',{}).get('status','Not yet enrolled for tracking'),
        'candidate_token':jwt.encode(claims,settings.SECRET_KEY,algorithm='HS256'),'expires_in':300}


async def confirm(db,actor,business_id,order_id,payload,*,authority=None):
    _,order=await access_order(db,actor,business_id,order_id,write=True,lock=True)
    if authority:
        await authority()
        await require_business_access(db,actor,business_id,'orders.write')
    # Replay is identified before candidate expiry; it cannot create a new intent.
    request_hash=digest({'order':order_id,'candidate_token':payload.candidate_token,'fingerprint':payload.expected_order_fingerprint,'confirmed':payload.confirmed})
    previous=await db.scalar(select(OrderParcelLink).where(OrderParcelLink.business_id==business_id,OrderParcelLink.idempotency_key==payload.idempotency_key))
    if previous:
        if previous.actor_id!=actor.user_id or previous.order_id!=order_id or previous.request_hash!=request_hash:raise HTTPException(409,'This command was already used for different details')
        return previous,True
    if await db.scalar(select(ParcelAudit.id).where(ParcelAudit.business_id==business_id,ParcelAudit.idempotency_key==payload.idempotency_key)):
        raise HTTPException(409,'This command identity was already used by another parcel action')
    if payload.confirmed is not True:raise HTTPException(422,'Confirm the parcel and selected order before linking')
    try:
        candidate=jwt.decode(payload.candidate_token,settings.SECRET_KEY,algorithms=['HS256'])
        if candidate.get('purpose')!='parcel_candidate' or candidate['actor']!=str(actor.user_id) or candidate['business']!=str(business_id) or candidate['order']!=str(order_id):raise ValueError()
    except (JWTError,KeyError,ValueError,TypeError):raise HTTPException(409,{'code':'parcel_preview_expired_or_invalid','message':'The parcel preview expired or changed. Check the label again.'}) from None
    connector=await connector_for(db,business_id)
    if candidate['connector']!=str(connector.id) or candidate.get('connector_version')!=digest([connector.origin,connector.instance_id,connector.credential_ref]) or candidate['fingerprint']!=fingerprint(order) or payload.expected_order_fingerprint!=fingerprint(order):
        raise HTTPException(409,'The order changed. Review the order and label again.')
    existing=await db.scalar(select(OrderParcelLink.id).where(OrderParcelLink.business_id==business_id,or_(OrderParcelLink.order_id==order_id,and_(OrderParcelLink.connector_id==connector.id,OrderParcelLink.courier_id==candidate['courier'],OrderParcelLink.awb==candidate['awb']))))
    if existing:raise HTTPException(409,'This order or parcel already has tracking history. Use an explicit reviewed resume or replacement.')
    link=OrderParcelLink(id=uuid4(),business_id=business_id,order_id=order_id,connector_id=connector.id,actor_id=actor.user_id,
        idempotency_key=payload.idempotency_key,request_hash=request_hash,order_fingerprint=fingerprint(order),courier_id=candidate['courier'],awb=candidate['awb'])
    db.add(link)
    try:await db.flush()
    except IntegrityError:raise HTTPException(409,'A parcel association changed. Refresh the order before retrying.') from None
    db.add(ParcelAudit(business_id=business_id,link_id=link.id,actor_id=actor.user_id,action='seller_confirmed_link',idempotency_key=payload.idempotency_key,
        details={'courier_id':link.courier_id,'awb':link.awb,'order_fingerprint':link.order_fingerprint}))
    await db.flush()
    return link,False


async def business_live(db,business_id):
    return bool(await db.scalar(select(Business.id).join(Seller,Seller.id==Business.id).where(Business.id==business_id,Business.is_active.is_(True),Seller.is_active.is_(True)).execution_options(autoflush=False)))


async def notification_decision(db,link,milestone):
    if await db.scalar(select(ParcelNotification.id).where(ParcelNotification.link_id==link.id,ParcelNotification.milestone==milestone)):return
    order=await db.scalar(select(CommerceOrder).where(CommerceOrder.id==link.order_id,CommerceOrder.seller_id==link.business_id).execution_options(populate_existing=True))
    decision,reason,message='skipped','not_consented',None
    from app.services import whatsapp as wa
    if order.whatsapp_updates_opt_in and order.fulfillment_status!='cancelled' and order.payment_status not in {'cancelled','expired','review_required'}:
        account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==link.business_id).with_for_update())
        contact=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id==link.business_id,WhatsAppContact.phone==wa.normalize_phone(order.customer['phone'])).with_for_update())
        mapping=(account.order_templates or {}).get('parcel_'+milestone) if account else None
        reason='approved_utility_template_unavailable'
        if account and account.enabled and contact and contact.utility_opt_in and not contact.opted_out and isinstance(mapping,dict):
            template=await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id==link.business_id,WhatsAppTemplate.name==mapping.get('name'),WhatsAppTemplate.language==mapping.get('language'),WhatsAppTemplate.category=='UTILITY'))
            try:
                if template:
                    message=await wa.queue_message(db,account,contact,key=f'parcel:{link.id}:{milestone}',template=template,
                        parameters=[order.customer.get('name',''),'MJ-'+order.id.hex[:12].upper(),link.raw_status])
                    decision,reason='queued','approved_utility_template'
            except HTTPException:reason='consent_or_template_not_eligible'
    db.add(ParcelNotification(business_id=link.business_id,link_id=link.id,milestone=milestone,decision=decision,reason=reason,outbox_id=message.id if message else None))


async def reconcile_snapshot(db,link,snapshot,*,notify=True):
    shipment=snapshot['shipment']
    if str(link.remote_id or shipment['id'])!=shipment['id'] or link.courier_id!=shipment['courier_id'] or link.awb!=shipment['awb']:
        raise ConnectorUnavailable('parcel_identity_changed')
    # Keep every independently observed provider event, even if a later response
    # contains only a shorter history. Unknown dates remain raw, never invented.
    events=[]
    for value in shipment['events']:
        if not isinstance(value,dict):continue
        raw_time=value.get('date',value.get('time',''))
        row={'raw_time':raw_time if isinstance(raw_time,str) else '', 'status':value.get('status',value.get('description','')),
             'description':value.get('description',value.get('detail','')),'location':value.get('location','')}
        if any(not isinstance(row[k],str) for k in row):continue
        row={k:v[:{'raw_time':100,'status':120,'description':500,'location':200}[k]] for k,v in row.items()}
        if not row['status']:continue
        event_hash=digest(row)
        events.append({'id':uuid4(),'business_id':link.business_id,'link_id':link.id,'event_hash':event_hash,**row,'event_at':timestamp(row['raw_time'])})
    if events:await db.execute(insert(ParcelObservation).values(events).on_conflict_do_nothing(constraint='v1_parcel_event_dedupe'))
    link.last_sync_at=now()
    if shipment['revoked']:
        link.state,link.error_code='review_required','remote_parcel_revoked';return
    if snapshot['revision']<link.snapshot_revision:
        link.error_code='older_snapshot_ignored';return
    checked=timestamp(shipment['checked_at']);attempted=timestamp(shipment['attempted_at'])
    if checked and (checked>now()+timedelta(minutes=5) or (link.checked_at and checked<link.checked_at)):
        link.error_code='older_or_invalid_check_ignored';return
    new_state=STATES.get(shipment['status'],'unknown')
    old_state=link.tracking_state
    if old_state in {'delivered','returned'} and new_state!=old_state:
        link.state,link.error_code='review_required','terminal_status_conflict';return
    if RANK[new_state]<RANK.get(old_state,0):
        link.error_code='status_regression_ignored';return
    link.remote_id=UUID(shipment['id']);link.snapshot_revision=snapshot['revision']
    link.tracking_state,link.raw_status=new_state,shipment['status']
    link.checked_at=checked or link.checked_at;link.attempted_at=attempted or link.attempted_at
    link.error_code=shipment['error_code'];link.state='linked';link.revision+=1
    if notify and checked and not shipment['error_code'] and new_state in {'in_transit','out_for_delivery','delivered','returned'}:
        await notification_decision(db,link,new_state)


async def process_link(db,link_id,*,adapter_factory=ParcelAdapter,force_refresh=False):
    link=await db.scalar(select(OrderParcelLink).where(OrderParcelLink.id==link_id).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if not link or link.state not in {'pending_enrollment','enrollment_unknown','linked'} or (link.lease_until and link.lease_until>now()):return
    connector=await db.scalar(select(ParcelConnector).where(ParcelConnector.id==link.connector_id,ParcelConnector.business_id==link.business_id).execution_options(populate_existing=True))
    if not connector or not await business_live(db,link.business_id):
        link.error_code='business_or_connector_inactive';await db.commit();return
    pending=link.state!='linked'
    if pending:
        try:
            _,order=await access_order(db,Actor(link.actor_id,'v1_user'),link.business_id,link.order_id,write=True)
            if fingerprint(order)!=link.order_fingerprint:raise HTTPException(409,'Order changed')
        except HTTPException:
            link.state,link.error_code='review_required','order_or_authority_changed';await db.commit();return
    token=uuid4();link.lease_token,link.lease_until=token,now()+timedelta(seconds=60)
    key,courier,awb,remote_id=link.idempotency_key,link.courier_id,link.awb,link.remote_id
    connector_identity=(connector.origin,connector.instance_id,connector.credential_ref)
    await db.commit()  # Durable intent/claim exists before any remote mutation.
    result,error=None,None
    try:
        adapter=adapter_factory(connector)
        result=await adapter.ensure(key,courier,awb) if pending else await adapter.read(remote_id,refresh=force_refresh)
    except ConnectorUnavailable as exc:error=str(exc)
    link=await db.scalar(select(OrderParcelLink).where(OrderParcelLink.id==link_id).with_for_update().execution_options(populate_existing=True))
    if not link or link.lease_token!=token:return
    current=await db.scalar(select(ParcelConnector).where(ParcelConnector.id==link.connector_id).execution_options(populate_existing=True))
    link.lease_token,link.lease_until=None,None;link.next_poll_at=now()+timedelta(minutes=5)
    try:
        if current is None:raise ConnectorUnavailable('connector_unconfigured')
        configuration(current)  # Registry/feature policy can change during HTTP.
        authorized=True
    except ConnectorUnavailable:authorized=False
    if not authorized or not await business_live(db,link.business_id) or connector_identity!=(current.origin,current.instance_id,current.credential_ref):
        link.state,link.error_code='review_required','business_or_connector_changed'
    elif pending:
        try:
            _,order=await access_order(db,Actor(link.actor_id,'v1_user'),link.business_id,link.order_id,write=True)
            if fingerprint(order)!=link.order_fingerprint:raise HTTPException(409,'Order changed')
        except HTTPException:
            link.state,link.error_code='review_required','order_or_authority_changed';result=None
    if link.state!='review_required':
        if error:
            link.state='enrollment_unknown' if pending else 'linked';link.error_code=error[:64]
        elif result:
            try:
                reviewed_replacement=pending and bool(await db.scalar(select(ParcelAudit.id).where(ParcelAudit.link_id==link.id,ParcelAudit.business_id==link.business_id,ParcelAudit.action=='seller_replaced_link')))
                await reconcile_snapshot(db,link,result,notify=not reviewed_replacement)
                if reviewed_replacement:
                    from app.services.parcel_reviews import baseline
                    await baseline(db,link)
            except ConnectorUnavailable as exc:link.state,link.error_code='review_required',str(exc)[:64]
    await db.commit()


async def revalidate_notification(db,message,contact):
    """Existing WhatsApp sender calls this after approval refresh, before send."""
    if not message.idempotency_key.startswith('parcel:'):return
    if not settings.V1_PARCEL_ENABLED:raise HTTPException(409,'Parcel updates are paused')
    parts=message.idempotency_key.split(':')
    if len(parts)!=3 or parts[2] not in {'in_transit','out_for_delivery','delivered','returned'}:raise HTTPException(409,'Invalid parcel update')
    try:link_id=UUID(parts[1])
    except ValueError:raise HTTPException(409,'Invalid parcel update') from None
    link=(await db.execute(select(OrderParcelLink.order_id,OrderParcelLink.state,OrderParcelLink.tracking_state,OrderParcelLink.error_code,OrderParcelLink.connector_id).where(OrderParcelLink.id==link_id,OrderParcelLink.business_id==message.seller_id).execution_options(autoflush=False))).first()
    if not link or link.state!='linked' or link.error_code or link.tracking_state!=parts[2] or not await business_live(db,message.seller_id):raise HTTPException(409,'Parcel updates are paused or superseded')
    review=(await db.execute(select(ParcelAudit.created_at,ParcelAudit.details).where(ParcelAudit.business_id==message.seller_id,ParcelAudit.link_id==link_id,ParcelAudit.action.in_(['seller_resumed_tracking','seller_replaced_link'])).order_by(ParcelAudit.created_at.desc(),ParcelAudit.id.desc()).limit(1).execution_options(autoflush=False))).first()
    if review and (message.created_at<=review.created_at or str(message.id) in review.details.get('withheld_outbox_ids',[])):raise HTTPException(409,'This earlier parcel update was withheld by an operator review')
    connector=(await db.execute(select(ParcelConnector.business_id,ParcelConnector.instance_id,ParcelConnector.origin,ParcelConnector.credential_ref,ParcelConnector.enabled).where(ParcelConnector.id==link.connector_id,ParcelConnector.business_id==message.seller_id).execution_options(autoflush=False))).first()
    try:
        if connector is None:raise ConnectorUnavailable('connector_unconfigured')
        configuration(connector)
    except ConnectorUnavailable:raise HTTPException(409,'Parcel connector authorization changed') from None
    order=(await db.execute(select(CommerceOrder.whatsapp_updates_opt_in,CommerceOrder.fulfillment_status,CommerceOrder.payment_status,CommerceOrder.customer).where(CommerceOrder.id==link.order_id,CommerceOrder.seller_id==message.seller_id).execution_options(autoflush=False))).first()
    from app.services import whatsapp as wa
    if not order or not order.whatsapp_updates_opt_in or order.fulfillment_status=='cancelled' or order.payment_status in {'cancelled','expired','review_required'} or not contact.utility_opt_in or contact.opted_out or contact.phone!=wa.normalize_phone(order.customer['phone']):raise HTTPException(409,'Parcel notification consent or order changed')
    template=await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id==message.seller_id,WhatsAppTemplate.name==message.payload.get('name'),WhatsAppTemplate.language==message.payload.get('language'),WhatsAppTemplate.category=='UTILITY').execution_options(populate_existing=True,autoflush=False))
    wa.check_template(template,contact,message.payload.get('parameters',[]))
