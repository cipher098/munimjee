"""Once-only comment dispatch with immutable source binding and current controls."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4, uuid5
import httpx
from sqlalchemy import select, func, text
from app.database import worker_session
from app.models.comment_automation import CommentAction, CommentEvent, CommentActionAudit
from app.services import comment_binding as policy
from app.integrations.instagram import InstagramClient
from app.workers.celery_app import celery_app
from app.workers.async_runner import run_async


def audit(db,action,stage,before,after,reason=None,provider_id=None):
    db.add(CommentActionAudit(id=uuid5(action.id,stage+':'+str(action.claim_token)),seller_id=action.seller_id,
        event_id=action.event_id,action_id=action.id,claim_token=action.claim_token,stage=stage,
        before_status=before,after_status=after,reason=reason,provider_id=provider_id))


async def event_for(db,action):
    return await db.scalar(select(CommentEvent).where(CommentEvent.id==action.event_id,
        CommentEvent.seller_id==action.seller_id))


async def hold(db,action,event,reason):
    expected_token,expected_status=action.claim_token,action.status
    fresh=await db.scalar(select(CommentAction).where(CommentAction.id==action.id,
        CommentAction.seller_id==action.seller_id).with_for_update().execution_options(populate_existing=True))
    if fresh is None or fresh.claim_token!=expected_token or fresh.status!=expected_status:
        await db.rollback();return False
    action=fresh
    before=action.status
    action.status,action.error_code='review_required',reason
    action.finalized_at=datetime.now(timezone.utc)
    if event is not None:
        audit(db,action,'withheld',before,'review_required',reason)
        await update_event_status(db,event)
    await db.commit()
    return False


async def dispatch_one(db,action_id):
    action=await db.scalar(select(CommentAction).where(CommentAction.id==action_id,
        CommentAction.status=='pending').with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if action is None:return False
    event=await event_for(db,action)
    if event is None:return await hold(db,action,None,'historical_tenant_binding_invalid')
    if action.accepted_claim is None or event.source_binding is None:
        return await hold(db,action,event,'legacy_binding_unverified')
    if action.claim_token or action.attempted_at or action.provider_id:
        return await hold(db,action,event,'prior_attempt_requires_review')
    current=await policy.context(db,action.seller_id,event.rule_id)
    reason=policy.eligibility(current,event,action)
    if reason:return await hold(db,action,event,reason)
    # Serialize local rate accounting without acquiring credential/catalogue rows.
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'),{'scope':'comment-throughput:'+str(action.seller_id)})
    now=datetime.now(timezone.utc)
    recent=await db.scalar(select(func.count()).select_from(CommentAction).where(CommentAction.seller_id==action.seller_id,
        CommentAction.kind==action.kind,CommentAction.attempted_at>=now-timedelta(hours=1)))
    if recent>=250: # Local cap only, never a claimed provider quota.
        await db.commit();return False
    action.claim_token=uuid4();action.status='sending';action.attempted_at=now
    audit(db,action,'claim','pending','sending')
    claim_token=action.claim_token
    await db.commit() # Crash after this is unknown, never automatically pending.
    current=await policy.context(db,action.seller_id,event.rule_id,action_id=action.id,claim_token=claim_token)
    if current is not None and not current.claim_active:
        await db.rollback();return False # Recovery/cancellation fenced this worker.
    reason=policy.eligibility(current,event,action)
    if reason:return await hold(db,action,event,reason)
    # No row lock or catalogue sweep spans this HTTP boundary. The scalar read
    # above is the current observation, not authority to ignore a later revoke.
    client=InstagramClient(current.connection.token,current.connection.account_id)
    provider_id=None;cancelled=False;error=None
    try:
        result=await (client.send_private_reply(event.comment_id,action.body) if action.kind=='private'
                      else client.reply_to_comment(event.comment_id,action.body))
        candidate=result.get('message_id') or result.get('id') if type(result) is dict else None
        if (isinstance(candidate,(str,int)) and not isinstance(candidate,bool) and 1<=len(str(candidate))<=200
            and current.connection.token not in str(candidate) and '://' not in str(candidate)
            and all(32<ord(char)<127 for char in str(candidate))):
            provider_id=str(candidate)
        else:error='missing_provider_receipt'
    except asyncio.CancelledError:
        cancelled=True;error='delivery_not_confirmed'
    except httpx.HTTPStatusError:
        # An intermediary status alone cannot establish non-acceptance.
        error='provider_http_result_unconfirmed'
    except Exception:
        error='delivery_not_confirmed'
    try:
        latest=await db.scalar(select(CommentAction).where(CommentAction.id==action.id,
            CommentAction.seller_id==action.seller_id).with_for_update().execution_options(populate_existing=True))
        if latest is None:return True
        if latest.claim_token!=claim_token or latest.status!='sending':
            # Preserve receipt against original claim without reviving stale work.
            db.add(CommentActionAudit(id=uuid5(action.id,'provider_result:'+str(claim_token)),seller_id=action.seller_id,
                event_id=action.event_id,action_id=action.id,claim_token=claim_token,stage='provider_result',
                before_status='sending',after_status=latest.status,reason='claim_changed_after_dispatch',provider_id=provider_id))
            event.status,event.reason='review_required','claim_changed_after_dispatch'
        else:
            current=await policy.context(db,latest.seller_id,event.rule_id)
            changed=policy.eligibility(current,event,latest)
            latest.status='sent' if provider_id else 'unknown'
            latest.provider_id=provider_id
            latest.error_code=('post_send_'+changed) if changed else error
            latest.finalized_at=datetime.now(timezone.utc)
            audit(db,latest,'provider_result','sending',latest.status,latest.error_code,provider_id)
            await update_event_status(db,event)
        await db.commit()
    finally:
        if cancelled:raise asyncio.CancelledError()
    return True


async def update_event_status(db,event):
    await db.flush()
    await db.execute(select(CommentEvent.id).where(CommentEvent.id==event.id,CommentEvent.seller_id==event.seller_id).with_for_update())
    states=(await db.execute(select(CommentAction.status,CommentAction.error_code).where(
        CommentAction.event_id==event.id,CommentAction.seller_id==event.seller_id))).all()
    event.status='review_required' if any(s in ('unknown','rejected','review_required') or (e or '').startswith('post_send_') for s,e in states) else (
        'cancelled' if states and all(s=='cancelled' for s,_ in states) else (
        'complete' if states and all(s in ('sent','cancelled') for s,_ in states) else 'queued'))
    if event.status=='review_required':
        event.reason=next((e for s,e in states if e),None) or 'send_result_unknown'


async def dispatch_pending():
    async with worker_session() as db:
        rows=(await db.scalars(select(CommentAction).where(CommentAction.status=='sending',
            CommentAction.attempted_at<datetime.now(timezone.utc)-timedelta(minutes=5)).with_for_update(skip_locked=True))).all()
        for action in rows:
            action.status,action.error_code='unknown','worker_interrupted'
            action.finalized_at=datetime.now(timezone.utc)
            event=await event_for(db,action)
            if event is not None:
                audit(db,action,'worker_recovered','sending','unknown','worker_interrupted',action.provider_id)
                await update_event_status(db,event)
        await db.commit()
        sellers=(await db.scalars(select(CommentAction.seller_id).where(CommentAction.status=='pending').distinct())).all()
        for seller_id in sellers:
            ids=(await db.scalars(select(CommentAction.id).where(CommentAction.status=='pending',CommentAction.seller_id==seller_id)
                .order_by(CommentAction.created_at).limit(10))).all()
            for action_id in ids:await dispatch_one(db,action_id)


@celery_app.task(name='app.workers.comment_automation.dispatch_pending_comments')
def dispatch_pending_comments():
    run_async(dispatch_pending())
