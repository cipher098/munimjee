"""At-most-once dispatch: ambiguous delivery is held for review, never resent."""
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select, update, func
from app.database import worker_session
from app.models.comment_automation import CommentAction, CommentEvent, CommentRule
from app.models.seller import Seller
from app.services.comment_automation import product_link
from app.integrations.instagram import InstagramClient
from app.workers.celery_app import celery_app
from app.workers.async_runner import run_async


async def dispatch_one(db, action_id):
    action = await db.scalar(select(CommentAction).where(CommentAction.id == action_id, CommentAction.status == 'pending').with_for_update(skip_locked=True))
    if not action:
        return False
    event = await db.get(CommentEvent, action.event_id)
    # Serialize claim/rate accounting per seller across concurrent beat workers.
    seller = await db.scalar(select(Seller).where(Seller.id == action.seller_id).with_for_update())
    rule = await db.get(CommentRule, event.rule_id) if event.rule_id else None
    now = datetime.now(timezone.utc)
    invalid = not seller or not seller.is_active or not seller.instagram_token or not rule or not rule.enabled
    if not invalid:
        try:
            link = await product_link(db, seller.id, rule.product_id)
            current_body = f'{rule.private_reply}\n{link}' if action.kind == 'private' else rule.public_reply
            invalid = action.body != current_body
        except Exception:
            invalid = True
    if invalid or not event.commented_at or now - event.commented_at >= timedelta(days=7):
        action.status, action.error_code = 'cancelled', 'rule_account_product_or_window_unavailable'
        await update_event_status(db, event)
        await db.commit()
        return False
    recent = await db.scalar(select(func.count()).select_from(CommentAction).where(
        CommentAction.seller_id == action.seller_id,
        CommentAction.kind == action.kind,
        CommentAction.attempted_at >= now - timedelta(hours=1)))
    if recent >= 250:  # Conservative local throughput cap, not a claimed Meta quota.
        await db.commit()
        return False
    action.status, action.attempted_at = 'sending', now
    # Commit claim BEFORE any network call. Process death after this cannot resend.
    await db.commit()
    client = InstagramClient(seller.instagram_token, seller.instagram_page_id)
    try:
        result = await (client.send_private_reply(event.comment_id, action.body) if action.kind == 'private' else client.reply_to_comment(event.comment_id, action.body))
        provider_id = result.get('message_id') or result.get('id')
        action.status = 'sent' if provider_id else 'unknown'
        action.provider_id = str(provider_id) if provider_id else None
        action.error_code = None if provider_id else 'missing_provider_receipt'
    except httpx.HTTPStatusError as exc:
        # A definitive 4xx is rejected; even provider 5xx can follow acceptance.
        action.status = 'rejected' if 400 <= exc.response.status_code < 500 else 'unknown'
        action.error_code = f'http_{exc.response.status_code}'
    except Exception:
        action.status, action.error_code = 'unknown', 'delivery_not_confirmed'
    await update_event_status(db, event)
    await db.commit()
    return True


async def update_event_status(db, event):
    await db.flush()
    # Aggregate independent public/private completions without stale status races.
    await db.execute(select(CommentEvent.id).where(CommentEvent.id == event.id).with_for_update())
    states = (await db.scalars(select(CommentAction.status).where(CommentAction.event_id == event.id))).all()
    event.status = 'review_required' if any(s in ('unknown', 'rejected') for s in states) else (
        'cancelled' if states and all(s == 'cancelled' for s in states) else (
            'complete' if all(s in ('sent', 'cancelled') for s in states) else 'queued'))


async def dispatch_pending():
    async with worker_session() as db:
        # A crashed task may have sent already. Preserve this uncertainty.
        stale_ids = (await db.scalars(update(CommentAction).where(CommentAction.status == 'sending', CommentAction.attempted_at < datetime.now(timezone.utc) - timedelta(minutes=5)).values(status='unknown', error_code='worker_interrupted').returning(CommentAction.event_id))).all()
        if stale_ids:
            await db.execute(update(CommentEvent).where(CommentEvent.id.in_(stale_ids)).values(status='review_required'))
        await db.commit()
        # Select sellers first: a rate-limited seller's old backlog must not
        # occupy the entire batch and starve other shops.
        sellers = (await db.scalars(select(CommentAction.seller_id).where(CommentAction.status == 'pending').distinct())).all()
        for seller_id in sellers:
            ids = (await db.scalars(select(CommentAction.id).where(CommentAction.status == 'pending', CommentAction.seller_id == seller_id).order_by(CommentAction.created_at).limit(10))).all()
            for action_id in ids:
                await dispatch_one(db, action_id)


@celery_app.task(name='app.workers.comment_automation.dispatch_pending_comments')
def dispatch_pending_comments():
    run_async(dispatch_pending())
