"""Comment matching and transactional outbox. No network sends during ingestion."""
import re
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.config import settings
from app.models.seller import Seller
from app.models.product import Product
from app.models.commerce import Storefront
from app.models.comment_automation import CommentRule, CommentEvent, CommentAction


def matches(rule, text, media_id):
    """Any keyword/phrase, Unicode casefold, bounded by non-word characters."""
    return (not rule.media_id or rule.media_id == media_id) and any(
        re.search(r'(?<!\w)' + re.escape(k.casefold()) + r'(?!\w)', text.casefold())
        for k in rule.keywords
    )


def public_base_ready():
    try:
        parsed = urlparse(settings.PUBLIC_BASE_URL.rstrip('/'))
        return bool(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


async def product_link(db, seller_id, product_id):
    product = await db.scalar(select(Product).where(Product.id == product_id, Product.seller_id == seller_id, Product.active.is_(True)))
    store = await db.scalar(select(Storefront).where(Storefront.seller_id == seller_id, Storefront.published.is_(True)))
    if not product or not store:
        raise HTTPException(400, 'Choose an active product and publish your storefront first')
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    if not public_base_ready():
        raise HTTPException(400, 'Configure a public HTTPS base URL before creating comment rules')
    return f'{base}/shop/{store.slug}?product={product.id}'


def comment_time(value, entry_time):
    raw = value.get('timestamp')  # Entry time is delivery time, never comment age.
    try:
        if isinstance(raw, (int, float)) or str(raw).isdigit():
            seconds = float(raw)
            return datetime.fromtimestamp(seconds / 1000 if seconds > 1e12 else seconds, timezone.utc)
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


async def ingest_comment(db, account_id, change, entry_time=None):
    seller = await db.scalar(select(Seller).where(Seller.instagram_page_id == str(account_id), Seller.is_active.is_(True)))
    if not seller or change.get('field') not in ('comments', 'live_comments'):
        return None
    value = change.get('value') or {}
    cid = str(value.get('id') or '')
    if not cid or len(cid) > 100:
        return None
    if await db.scalar(select(CommentEvent.id).where(CommentEvent.seller_id == seller.id, CommentEvent.comment_id == cid)):
        return None
    media = value.get('media') or {}
    actor = str((value.get('from') or {}).get('id') or '')
    media_id = str(media.get('id') or '')
    text = str(value.get('text') or '')[:10000]
    # Webhooks need not carry creation time/parent_id. Verify actual comment
    # metadata before deciding eligibility, never invent a fresh window on replay.
    known_ineligible = change.get('field') == 'live_comments' or str(media.get('media_product_type', '')).upper() == 'LIVE' or value.get('parent_id') or actor in {str(seller.instagram_page_id), str(seller.instagram_id)}
    if not known_ineligible and (not value.get('timestamp') or 'parent_id' not in value):
        from app.integrations.instagram import InstagramClient
        try:
            details = await InstagramClient(seller.instagram_token, seller.instagram_page_id).get_comment_details(cid)
            value = {**value, 'timestamp': details.get('timestamp'), 'parent_id': details.get('parent_id')}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 or exc.response.status_code == 429:
                raise  # Read-only verification can be safely retried by ingress.
            value = {**value, 'timestamp': None}
        except httpx.TransportError:
            raise  # Do not acknowledge/drop a comment on a transient read failure.
        except (ValueError, TypeError):
            value = {**value, 'timestamp': None}
    timestamp = comment_time(value, entry_time)
    now = datetime.now(timezone.utc)
    reason = None
    if change.get('field') == 'live_comments' or str(media.get('media_product_type', '')).upper() == 'LIVE':
        reason = 'live_comment_not_supported'
    elif value.get('parent_id'):
        reason = 'nested_comment'
    elif actor in {str(seller.instagram_page_id), str(seller.instagram_id)}:
        reason = 'own_comment'
    elif not actor or not media_id or len(actor) > 100 or len(media_id) > 100:
        reason = 'incomplete_event'
    elif not timestamp or timestamp > now + timedelta(minutes=5):
        reason = 'unverified_timestamp'
    elif now - timestamp >= timedelta(days=7):
        reason = 'private_reply_window_expired'
    eid = uuid4()
    inserted = await db.scalar(insert(CommentEvent).values(
        id=eid, seller_id=seller.id, comment_id=cid, media_id=media_id[:100], actor_id=actor[:100], text=text,
        commented_at=timestamp, status='skipped' if reason else 'received', reason=reason,
    ).on_conflict_do_nothing(constraint='comment_event_once').returning(CommentEvent.id))
    if not inserted or reason:
        return inserted
    event = await db.get(CommentEvent, eid)
    rules = (await db.scalars(select(CommentRule).where(CommentRule.seller_id == seller.id, CommentRule.enabled.is_(True)).order_by(CommentRule.created_at, CommentRule.id))).all()
    for rule in rules:
        if not matches(rule, text, media_id):
            continue
        try:
            link = await product_link(db, seller.id, rule.product_id)
        except HTTPException:
            event.status, event.reason = 'skipped', 'product_or_store_unavailable'
            return eid
        event.rule_id, event.status = rule.id, 'queued'
        db.add(CommentAction(seller_id=seller.id, event_id=eid, kind='private', body=f'{rule.private_reply}\n{link}'))
        if rule.public_reply:
            db.add(CommentAction(seller_id=seller.id, event_id=eid, kind='public', body=rule.public_reply))
        await db.flush()
        return eid
    event.status, event.reason = 'skipped', 'no_matching_rule'
    return eid
