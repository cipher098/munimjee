"""Membership-based assistance. No impersonation, access grants or provider calls."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import func, select
from app.models.assistance import AssistanceCommand, OnboardingAssignment
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.models.channel_operator import ChannelConnectionState
from app.models.commerce import Storefront
from app.models.identity import Business, Membership, User
from app.models.imports_v1 import ImportJob
from app.models.seller import Seller
from app.schemas.assistance import (AssignmentRead, AssistanceBusinessRead, AssistanceCommandRead,
    AssistancePage, AssistanceStep, ChannelCheck)
from app.services.identity import capabilities_for, require_business_access
from app.services.identity_auth import audit


def native(actor):
    if actor.auth_method != 'v1_user':
        raise HTTPException(401, 'Sign in with your own V1 account to use onboarding assistance')


def hash_request(operation, body):
    return hashlib.sha256(json.dumps({'operation':operation,'body':body},sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def assignment_view(db,business_id):
    row=(await db.execute(select(OnboardingAssignment.assignee_user_id,OnboardingAssignment.version,
        OnboardingAssignment.updated_at).where(OnboardingAssignment.business_id==business_id)
        .execution_options(autoflush=False))).one_or_none()
    if row is None:return AssignmentRead(version=0,assignee_user_id=None,display_name=None,eligible=False,updated_at=None)
    eligible=None
    if row.assignee_user_id:
        eligible=(await db.execute(select(User.display_name).join(Membership,Membership.user_id==User.id).where(
            Membership.business_id==business_id,Membership.user_id==row.assignee_user_id,
            Membership.is_active.is_(True),Membership.revoked_at.is_(None),Membership.role.in_(('owner','manager')),
            User.is_active.is_(True),User.revoked_at.is_(None)).execution_options(autoflush=False))).one_or_none()
    return AssignmentRead(version=row.version,assignee_user_id=row.assignee_user_id,
        display_name=(eligible.display_name or 'Assigned team member') if eligible else None,
        eligible=eligible is not None,updated_at=row.updated_at)


def action(paths,business_id,path):
    value=path.format(business_id=business_id)
    base=value.split('?',1)[0].split('#',1)[0]
    return value if base in {path.replace('{business_id}',str(business_id)) for path in paths} else None


async def business_view(db,actor,business_id,*,available_paths=frozenset()):
    native(actor)
    await require_business_access(db,actor,business_id,'readiness.read')
    profile=(await db.execute(select(Business.name,Business.profile_confirmed_at).join(Seller,Seller.id==Business.id).where(
        Business.id==business_id,Business.is_active.is_(True),Seller.is_active.is_(True)).execution_options(autoflush=False))).one_or_none()
    if profile is None:raise HTTPException(404,'Business not found')
    reviewed=await db.scalar(select(func.count()).select_from(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id==business_id,CatalogueProductMapping.state=='reviewed'))
    skus=await db.scalar(select(func.count()).select_from(CatalogueSKU).where(CatalogueSKU.business_id==business_id,CatalogueSKU.active.is_(True)))
    activated=await db.scalar(select(func.count()).select_from(CatalogueActivation).where(CatalogueActivation.business_id==business_id))
    jobs=dict((await db.execute(select(ImportJob.state,func.count()).where(ImportJob.business_id==business_id).group_by(ImportJob.state))).all())
    store=(await db.execute(select(Storefront.published).where(Storefront.seller_id==business_id).execution_options(autoflush=False))).one_or_none()
    policy=await db.scalar(select(CatalogueStorePolicy.checkout_enabled).where(CatalogueStorePolicy.business_id==business_id).execution_options(autoflush=False))
    checks=[ChannelCheck(channel=row.channel,checked_at=row.checked_at,status=row.check_status) for row in
        (await db.execute(select(ChannelConnectionState.channel,ChannelConnectionState.checked_at,ChannelConnectionState.check_status).where(
            ChannelConnectionState.business_id==business_id,ChannelConnectionState.channel.in_(('instagram','whatsapp')))
            .execution_options(autoflush=False))).all()]
    assigned=await assignment_view(db,business_id)
    # The final authority projection bypasses retained role/user ORM state. A
    # revoke during any aggregate query must not return the older business row.
    access=await require_business_access(db,actor,business_id,'readiness.read')
    caps=access.capabilities
    active=bool(activated and store and store.published and policy)
    work=jobs.get('pending',0)+jobs.get('running',0)
    steps=[
        AssistanceStep(id='profile',label='Business details',status='ready_local' if profile.profile_confirmed_at else 'action_required',
            reason='Business details are confirmed.' if profile.profile_confirmed_at else 'Confirm the boutique details with its owner.',
            action_url=action(available_paths,business_id,'/v1?business={business_id}#profile')),
        AssistanceStep(id='imports',label='Import review',status='action_required',
            reason=f"{work} imports pending/running; {jobs.get('failed',0)} failed and {jobs.get('review_required',0)} need review. Source approval never publishes inventory.",
            action_url=action(available_paths,business_id,'/v1/businesses/{business_id}/imports') if 'catalogue.read' in caps else None),
        AssistanceStep(id='catalogue',label='Catalogue and stock',status='ready_local' if activated else 'action_required',
            reason=f'{reviewed} reviewed snapshots, {activated} activated products and {skus} active SKUs. Confirm current facts and availability in Catalogue.',
            action_url=action(available_paths,business_id,'/v1/businesses/{business_id}/catalogue') if 'catalogue.read' in caps else None),
        AssistanceStep(id='channels',label='Channel accounts and live test',status='pending_external',
            reason='Local account checks do not prove provider approval or a successful live customer message. Complete an authorized provider test separately.',
            action_url=action(available_paths,business_id,'/v1/businesses/{business_id}/channels') if 'inbox.read' in caps else None),
        AssistanceStep(id='storefront',label='Store publication and checkout',status='ready_local' if active else 'action_required',
            reason=('Local publication, activated stock and checkout policy are enabled.' if active else 'Publication, product activation and checkout policy are separate owner-reviewed gates.'),
            action_url=action(available_paths,business_id,'/v1/businesses/{business_id}/catalogue') if 'catalogue.read' in caps else None),
        AssistanceStep(id='payments',label='Payment configuration and test',status='pending_external',
            reason='Credential configuration is local only. A real approved payment test and settlement check remain separate.',
            action_url=action(available_paths,business_id,'/v1/businesses/{business_id}/payments') if 'business.write' in caps else None),
    ]
    return AssistanceBusinessRead(business_id=business_id,name=profile.name,role=access.role,
        can_assign='members.manage' in caps,assignment=assigned,steps=steps,channel_checks=checks)


async def businesses(db,actor,*,after=None,limit=20,assigned_to_me=False,available_paths=frozenset(),reauthorize):
    native(actor)
    query=select(Business.id).join(Membership,Membership.business_id==Business.id).join(Seller,Seller.id==Business.id).where(
        Membership.user_id==actor.user_id,Membership.is_active.is_(True),Membership.revoked_at.is_(None),
        Business.is_active.is_(True),Seller.is_active.is_(True))
    if after:query=query.where(Business.id>after)
    if assigned_to_me:query=query.join(OnboardingAssignment,OnboardingAssignment.business_id==Business.id).where(
        OnboardingAssignment.assignee_user_id==actor.user_id,Membership.role.in_(('owner','manager')))
    ids=list(await db.scalars(query.order_by(Business.id).limit(limit+1).execution_options(autoflush=False)))
    items=[]
    for business_id in ids[:limit]:
        try:items.append(await business_view(db,actor,business_id,available_paths=available_paths))
        except HTTPException as exc:
            if exc.status_code not in (403,404):raise
    await reauthorize()
    # A revoked earlier business cannot survive while later rows were awaited.
    current=dict((await db.execute(select(Business.id,Membership.role).join(Membership,Membership.business_id==Business.id)
        .join(Seller,Seller.id==Business.id).where(Business.id.in_([item.business_id for item in items]),
        Membership.user_id==actor.user_id,Membership.is_active.is_(True),Membership.revoked_at.is_(None),
        Business.is_active.is_(True),Seller.is_active.is_(True)).execution_options(autoflush=False))).all())
    await reauthorize()
    visible=[]
    for item in items:
        role=current.get(item.business_id)
        if role is None:continue
        caps=capabilities_for(role)
        steps=[step.model_copy(update={'action_url':None}) if step.id=='payments' and 'business.write' not in caps else step for step in item.steps]
        visible.append(item.model_copy(update={'role':role,'can_assign':'members.manage' in caps,'steps':steps}))
    return AssistancePage(items=visible,next_after=ids[limit-1] if len(ids)>limit else None)


async def assignees(db,actor,business_id):
    native(actor)
    await require_business_access(db,actor,business_id,'members.manage')
    rows=(await db.execute(select(User.id,User.display_name,User.auth_email,Membership.role).join(
        Membership,Membership.user_id==User.id).where(Membership.business_id==business_id,
        Membership.is_active.is_(True),Membership.revoked_at.is_(None),Membership.role.in_(('owner','manager')),
        User.is_active.is_(True),User.revoked_at.is_(None)).order_by(User.id).limit(100).execution_options(autoflush=False))).all()
    await require_business_access(db,actor,business_id,'members.manage')
    # Email labels are restricted to the existing member-management capability;
    # ordinary readiness projections never expose another member's email.
    return {'business_id':business_id,'items':[{'user_id':row.id,'label':row.display_name or row.auth_email or 'Team member','role':row.role} for row in rows]}


async def command(db,actor,business_id,body,operation,*,reauthorize):
    native(actor)
    capability='members.manage' if operation=='assignment' else 'readiness.read'
    await require_business_access(db,actor,business_id,capability)
    await db.scalar(select(Business.id).where(Business.id==business_id).with_for_update(key_share=True))
    await reauthorize()
    await require_business_access(db,actor,business_id,capability)
    payload=body.model_dump(mode='json');request_hash=hash_request(operation,payload)
    receipt=await db.get(AssistanceCommand,(business_id,body.idempotency_key),populate_existing=True)
    if receipt:
        if receipt.actor_user_id!=actor.user_id or receipt.operation!=operation or receipt.request_hash!=request_hash:
            raise HTTPException(409,'This assistance command key was already used for different details')
        return AssistanceCommandRead.model_validate({**receipt.result,'replayed':True})
    version=None;assignee_user_id=None
    if operation=='assignment':
        row=await db.scalar(select(OnboardingAssignment).where(OnboardingAssignment.business_id==business_id)
            .with_for_update().execution_options(populate_existing=True))
        current=row.version if row else 0
        if current!=body.expected_version:
            raise HTTPException(409,{'code':'assistance_assignment_stale','message':'The onboarding lead changed. Reload and review the current assignment.'})
        if current>=2000000000:raise HTTPException(409,'Assignment version limit reached')
        if body.assignee_user_id:
            eligible=await db.scalar(select(Membership.id).join(User,User.id==Membership.user_id).where(
                Membership.business_id==business_id,Membership.user_id==body.assignee_user_id,
                Membership.is_active.is_(True),Membership.revoked_at.is_(None),Membership.role.in_(('owner','manager')),
                User.is_active.is_(True),User.revoked_at.is_(None)).with_for_update(read=True,of=(Membership,User)).execution_options(autoflush=False))
            if eligible is None:raise HTTPException(409,'Choose an active owner or manager who already belongs to this business')
        await reauthorize()
        await require_business_access(db,actor,business_id,capability)
        previous=row.assignee_user_id if row else None
        if row is None:
            row=OnboardingAssignment(business_id=business_id,version=1,assignee_user_id=body.assignee_user_id,assigned_by_user_id=actor.user_id)
            db.add(row)
        else:row.version+=1;row.assignee_user_id=body.assignee_user_id;row.assigned_by_user_id=actor.user_id
        row.updated_at=datetime.now(timezone.utc);version=row.version;assignee_user_id=row.assignee_user_id
        audit(db,actor.user_id,'assistance_assignment_updated',business_id=business_id,details={
            'command_id':str(body.idempotency_key),'version':version,'previous_assignee':str(previous) if previous else None,
            'assignee':str(assignee_user_id) if assignee_user_id else None})
    elif operation=='open':
        audit(db,actor.user_id,'assistance_opened',business_id=business_id,details={'command_id':str(body.idempotency_key)})
    else:raise ValueError('Unsupported assistance command')
    result=AssistanceCommandRead(business_id=business_id,idempotency_key=body.idempotency_key,operation=operation,
        version=version,assignee_user_id=assignee_user_id,workspace_url=f'/v1/businesses/{business_id}/assistance',replayed=False)
    db.add(AssistanceCommand(business_id=business_id,idempotency_key=body.idempotency_key,actor_user_id=actor.user_id,
        operation=operation,request_hash=request_hash,result=result.model_dump(mode='json')))
    await db.flush()
    return result
