"""Owner-consented read-only support. Never a membership/impersonation resolver."""
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from app.config import settings
from app.models.identity import Business, Membership, User
from app.models.seller import Seller
from app.models.support_grants import SupportCommand, SupportGrant
from app.models.imports_v1 import ImportJob
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.models.commerce import Storefront
from app.models.channel_operator import ChannelConnectionState
from app.schemas.support_grants import GrantRead, GrantCommandRead, SummaryRead
from app.services.identity import require_business_access
from app.services.assistance import hash_request, native
from app.services.identity_auth import audit


def enabled():
    if not settings.V1_SUPPORT_GRANTS_ENABLED:raise HTTPException(404,'Assisted access is unavailable')


def operators():return frozenset(settings.V1_SUPPORT_OPERATOR_IDS)


async def clock(db):return await db.scalar(select(func.clock_timestamp()).execution_options(autoflush=False))


async def owner(db,actor,business_id):
    enabled();native(actor)
    access=await require_business_access(db,actor,business_id,'members.manage')
    if access.role!='owner':raise HTTPException(403,'Current owner consent is required')
    return access


async def subject(db,user_id):
    if user_id not in operators():raise HTTPException(404,'Provisioned operator not found')
    row=(await db.execute(select(User.id,User.auth_version,User.auth_email,User.display_name).where(
        User.id==user_id,User.is_active.is_(True),User.revoked_at.is_(None),User.password_hash.is_not(None))
        .execution_options(autoflush=False))).one_or_none()
    if row is None:raise HTTPException(404,'Provisioned operator not found')
    return row


async def lookup(db,actor,business_id,email):
    await owner(db,actor,business_id)
    uid=await db.scalar(select(User.id).where(User.auth_email==str(email).strip().lower(),User.id.in_(operators()))
        .execution_options(autoflush=False))
    if uid is None:raise HTTPException(404,'Provisioned operator not found')
    row=await subject(db,uid)
    await owner(db,actor,business_id)
    return {'user_id':row.id,'label':row.display_name or row.auth_email,'email':row.auth_email}


def grant_view(row,label=None,email=None):
    return GrantRead(grant_id=row.id,business_id=row.business_id,subject_user_id=row.subject_user_id,
        scope=row.scope,reason=row.reason,created_at=row.created_at,expires_at=row.expires_at,
        revoked_at=row.revoked_at,consented_by_user_id=row.consented_by_user_id,subject_label=label,subject_email=email)


async def owner_grants(db,actor,business_id,after=None,limit=20):
    await owner(db,actor,business_id)
    q=select(SupportGrant,User.display_name,User.auth_email).join(User,User.id==SupportGrant.subject_user_id).where(SupportGrant.business_id==business_id)
    if after:q=q.where(SupportGrant.id>after)
    rows=(await db.execute(q.order_by(SupportGrant.id).limit(limit+1).execution_options(autoflush=False,populate_existing=True))).all()
    await owner(db,actor,business_id)
    return {'contract_version':'support-grants.v1','business_id':business_id,'items':[grant_view(row[0],row.display_name or row.auth_email,row.auth_email) for row in rows[:limit]],
        'next_after':rows[limit-1][0].id if len(rows)>limit else None}


def valid_query(actor,grant_id=None):
    consenting=aliased(User);recipient=aliased(User);membership=aliased(Membership)
    q=select(SupportGrant.id,SupportGrant.business_id,SupportGrant.subject_user_id,SupportGrant.expires_at,
        Business.name).join(Business,Business.id==SupportGrant.business_id).join(Seller,Seller.id==Business.id)
    q=q.join(consenting,consenting.id==SupportGrant.consented_by_user_id).join(recipient,recipient.id==SupportGrant.subject_user_id)
    q=q.join(membership,(membership.business_id==SupportGrant.business_id)&(membership.user_id==SupportGrant.consented_by_user_id))
    q=q.where(SupportGrant.subject_user_id==actor.user_id,SupportGrant.subject_user_id.in_(operators()),
        SupportGrant.revoked_at.is_(None),SupportGrant.expires_at>func.clock_timestamp(),SupportGrant.scope=='readiness.summary',
        Business.is_active.is_(True),Seller.is_active.is_(True),recipient.is_active.is_(True),recipient.revoked_at.is_(None),
        recipient.password_hash.is_not(None),recipient.auth_version==SupportGrant.subject_auth_version,
        consenting.is_active.is_(True),consenting.revoked_at.is_(None),consenting.auth_version==SupportGrant.owner_auth_version,
        membership.is_active.is_(True),membership.revoked_at.is_(None),membership.role=='owner')
    if grant_id:q=q.where(SupportGrant.id==grant_id)
    return q.execution_options(autoflush=False)


async def access(db,actor,grant_id):
    enabled();native(actor)
    row=(await db.execute(valid_query(actor,grant_id))).one_or_none()
    if row is None:raise HTTPException(404,'Current assisted access is unavailable')
    return row


async def board(db,actor,*,after=None,limit=20,reauthorize):
    enabled();native(actor)
    q=valid_query(actor)
    if after:q=q.where(SupportGrant.id>after)
    rows=(await db.execute(q.order_by(SupportGrant.id).limit(limit+1))).all()
    await reauthorize()
    # Each row is checked after all preceding awaits, never against retained ORM.
    ids=[row.id for row in rows[:limit]]
    visible=(await db.execute(valid_query(actor).where(SupportGrant.id.in_(ids)).order_by(SupportGrant.id))).all() if ids else []
    await reauthorize()
    enabled()
    if actor.user_id not in operators():return {'contract_version':'support-board.v1','items':[],'next_after':None}
    return {'contract_version':'support-board.v1','items':[{'grant_id':row.id,'business_id':row.business_id,
        'name':row.name,'scope':'readiness.summary','expires_at':row.expires_at} for row in visible],
        'next_after':rows[limit-1].id if len(rows)>limit else None}


async def saved(db,actor,business_id,key,operation,payload):
    receipt=await db.get(SupportCommand,(business_id,key),populate_existing=True)
    if receipt and (receipt.actor_user_id!=actor.user_id or receipt.operation!=operation or receipt.request_hash!=hash_request(operation,payload)):
        raise HTTPException(409,'This assisted-access command key was used for different details')
    return receipt


async def record(db,actor,business_id,grant_id,key,operation,payload,result):
    db.add(SupportCommand(business_id=business_id,grant_id=grant_id,idempotency_key=key,actor_user_id=actor.user_id,
        operation=operation,request_hash=hash_request(operation,payload),result=result.model_dump(mode='json')))
    audit(db,actor.user_id,'support_'+operation,business_id=business_id,details={'grant_id':str(grant_id),'command_id':str(key),'scope':'readiness.summary'})
    await db.flush()
    return result


async def create(db,actor,business_id,body,*,reauthorize):
    await owner(db,actor,business_id)
    await db.scalar(select(Business.id).where(Business.id==business_id).with_for_update(key_share=True))
    await reauthorize();await owner(db,actor,business_id)
    payload=body.model_dump(mode='json');receipt=await saved(db,actor,business_id,body.idempotency_key,'create',payload)
    if receipt:return GrantCommandRead.model_validate({**receipt.result,'replayed':True})
    target=await subject(db,body.subject_user_id)
    if target.id==actor.user_id:raise HTTPException(409,'Choose another provisioned operator')
    now=await clock(db)
    if not now+timedelta(minutes=5)<=body.expires_at<=now+timedelta(minutes=60):
        raise HTTPException(409,{'code':'support_expiry_invalid','message':'Choose an expiry between five and sixty minutes from now.'})
    exists=await db.scalar(select(SupportGrant.id).where(SupportGrant.business_id==business_id,
        SupportGrant.subject_user_id==target.id,SupportGrant.revoked_at.is_(None),SupportGrant.expires_at>func.clock_timestamp()))
    if exists:raise HTTPException(409,'This operator already has unexpired consent. Revoke it before granting again.')
    owner_version=await db.scalar(select(User.auth_version).where(User.id==actor.user_id).execution_options(autoflush=False))
    row=SupportGrant(id=uuid4(),business_id=business_id,subject_user_id=target.id,consented_by_user_id=actor.user_id,
        subject_auth_version=target.auth_version,owner_auth_version=owner_version,scope=body.scope,reason=body.reason,
        created_at=now,expires_at=body.expires_at)
    db.add(row);await db.flush()
    await reauthorize();await owner(db,actor,business_id);current=await subject(db,target.id)
    if current.auth_version!=target.auth_version:raise HTTPException(409,'Operator authority changed; review a fresh consent.')
    result=GrantCommandRead(business_id=business_id,grant_id=row.id,idempotency_key=body.idempotency_key,operation='create',grant=grant_view(row,target.display_name or target.auth_email,target.auth_email))
    return await record(db,actor,business_id,row.id,body.idempotency_key,'create',payload,result)


async def revoke(db,actor,business_id,grant_id,body,*,reauthorize):
    await owner(db,actor,business_id)
    await db.scalar(select(Business.id).where(Business.id==business_id).with_for_update(key_share=True))
    await reauthorize();await owner(db,actor,business_id)
    payload={'grant_id':str(grant_id),**body.model_dump(mode='json')}
    receipt=await saved(db,actor,business_id,body.idempotency_key,'revoke',payload)
    if receipt:return GrantCommandRead.model_validate({**receipt.result,'replayed':True})
    row=await db.scalar(select(SupportGrant).where(SupportGrant.business_id==business_id,SupportGrant.id==grant_id)
        .with_for_update().execution_options(populate_existing=True))
    if row is None:raise HTTPException(404,'Consent not found')
    if row.revoked_at is None:row.revoked_at=await clock(db);row.revoked_by_user_id=actor.user_id
    await reauthorize();await owner(db,actor,business_id)
    labels=(await db.execute(select(User.display_name,User.auth_email).where(User.id==row.subject_user_id).execution_options(autoflush=False))).one()
    result=GrantCommandRead(business_id=business_id,grant_id=row.id,idempotency_key=body.idempotency_key,operation='revoke',grant=grant_view(row,labels.display_name or labels.auth_email,labels.auth_email))
    return await record(db,actor,business_id,row.id,body.idempotency_key,'revoke',payload,result)


async def summary(db,actor,grant_id,body,*,reauthorize):
    grant=await access(db,actor,grant_id)
    await db.scalar(select(Business.id).where(Business.id==grant.business_id).with_for_update(key_share=True))
    await reauthorize();grant=await access(db,actor,grant_id)
    payload={'grant_id':str(grant_id),**body.model_dump(mode='json')}
    receipt=await saved(db,actor,grant.business_id,body.idempotency_key,'open',payload)
    if receipt:
        await reauthorize();await access(db,actor,grant_id)
        return SummaryRead.model_validate({**receipt.result,'replayed':True})
    profile=await db.scalar(select(Business.profile_confirmed_at).where(Business.id==grant.business_id))
    jobs=dict((await db.execute(select(ImportJob.state,func.count()).where(ImportJob.business_id==grant.business_id).group_by(ImportJob.state))).all())
    activated=await db.scalar(select(func.count()).select_from(CatalogueActivation).where(CatalogueActivation.business_id==grant.business_id))
    skus=await db.scalar(select(func.count()).select_from(CatalogueSKU).where(CatalogueSKU.business_id==grant.business_id,CatalogueSKU.active.is_(True)))
    store=await db.scalar(select(Storefront.published).where(Storefront.seller_id==grant.business_id))
    policy=await db.scalar(select(CatalogueStorePolicy.checkout_enabled).where(CatalogueStorePolicy.business_id==grant.business_id))
    checks=[{'channel':row.channel,'status':row.check_status if row.check_status in {'not_checked','verified','needs_reconnect','failed'} else 'not_evaluated','checked_at':row.checked_at.isoformat() if row.checked_at else None} for row in
        (await db.execute(select(ChannelConnectionState.channel,ChannelConnectionState.check_status,ChannelConnectionState.checked_at)
            .where(ChannelConnectionState.business_id==grant.business_id,ChannelConnectionState.channel.in_(('instagram','whatsapp'))))).all()]
    await reauthorize();grant=await access(db,actor,grant_id)
    result=SummaryRead(business_id=grant.business_id,grant_id=grant_id,idempotency_key=body.idempotency_key,
        name=grant.name,captured_at=await clock(db),expires_at=grant.expires_at,profile_confirmed=profile is not None,
        imports_pending=jobs.get('pending',0)+jobs.get('running',0),imports_need_review=jobs.get('failed',0)+jobs.get('review_required',0),
        activated_products=activated,active_skus=skus,store_published=bool(store),checkout_policy_enabled=bool(policy),channel_checks=checks)
    return await record(db,actor,grant.business_id,grant_id,body.idempotency_key,'open',payload,result)
