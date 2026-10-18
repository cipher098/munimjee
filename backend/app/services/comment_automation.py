"""Comment matching and transactional outbox. No network sends during ingestion."""
import re
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4, UUID
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
        if type(raw) in (int, float) or (isinstance(raw,str) and raw.isdigit()):
            seconds = float(raw)
            return datetime.fromtimestamp(seconds / 1000 if seconds > 1e12 else seconds, timezone.utc)
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


async def ingest_comment(db, account_id, change, entry_time=None, *, verified_source=False):
    """Accept only the signature-verified hook's account; never a body seller ID.

    The explicit trusted-source marker is internal, not a request field. Metadata
    reads can retry on transient failure; no provider mutation occurs here.
    """
    if verified_source is not True or type(change) is not dict or change.get('field') not in ('comments','live_comments'):
        return None
    value=change.get('value')
    if type(value) is not dict:return None
    def identifier(value):
        return str(value) if type(value) in (str,int) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(value)) else ''
    cid=identifier(value.get('id'));account_id=identifier(account_id)
    if not cid or not account_id:return None
    owners=(await db.scalars(select(Seller.id).where(Seller.instagram_page_id==account_id))).all()
    if len(owners)!=1:return None
    seller_id=owners[0]
    if await db.scalar(select(CommentEvent.id).where(CommentEvent.seller_id==seller_id,CommentEvent.comment_id==cid)):
        return None # Never rebind accepted or historical work on replay.
    from app.services import comment_binding as policy
    from app.schemas.comment_binding import accepted_claim,digest,source_age_reason
    first=await policy.context(db,seller_id)
    if first is None:return None
    proof=first.connection.proof() if first.connection.usable() and first.connection.account_id==account_id else None
    media=value.get('media') or {};actor=value.get('from') or {}
    if type(media) is not dict or type(actor) is not dict:return None
    media_id=identifier(media.get('id'));actor_id=identifier(actor.get('id'))
    text=value.get('text','')
    if not isinstance(text,str):return None
    text=text[:10000]
    verification='signed_webhook'
    known_ineligible=change['field']=='live_comments' or str(media.get('media_product_type','')).upper()=='LIVE' or value.get('parent_id') or actor_id in {account_id,first.config['owner_account']}
    reason=first.source_reason()
    if reason is None and proof is None:reason='source_generation_changed'
    if not reason and not known_ineligible and (not value.get('timestamp') or 'parent_id' not in value):
        from app.integrations.instagram import InstagramClient
        try:
            details=await InstagramClient(first.connection.token,account_id).get_comment_details(cid)
            if type(details) is not dict:raise ValueError()
            value={**value,'timestamp':details.get('timestamp'),'parent_id':details.get('parent_id')}
            verification='provider_metadata'
        except (httpx.TransportError,httpx.HTTPStatusError):
            # Do not propagate token-bearing provider URLs through server logs.
            raise HTTPException(503,'Comment metadata could not be verified. Retry the event.') from None
        except (ValueError,TypeError,RecursionError):
            value={**value,'timestamp':None}
    current=await policy.context(db,seller_id)
    if current is None:return None
    if reason is None:reason=current.source_reason()
    if reason is None and (not proof or not current.connection.matches(proof)):
        reason='source_generation_changed'
    if reason is None and policy.source_config(first)!=policy.source_config(current):reason='source_configuration_changed'
    timestamp=comment_time(value,entry_time)
    if change['field']=='live_comments' or str(media.get('media_product_type','')).upper()=='LIVE':reason='live_comment_not_supported'
    elif 'parent_id' in value and value['parent_id'] is not None and not identifier(value['parent_id']):reason='incomplete_event'
    elif value.get('parent_id'):reason='nested_comment'
    elif actor_id in {account_id,current.config['owner_account']}:reason='own_comment'
    elif not actor_id or not media_id:reason='incomplete_event'
    elif reason is None:reason=source_age_reason(timestamp)
    rule_id=None;selected=None
    if reason is None:
        try:
            matches_=policy.matched_rules(current.rules,text,media_id)
            if len({r['product_id'] for r in matches_})>1:reason='product_context_ambiguous'
            elif matches_:rule_id=UUID(matches_[0]['id'])
            else:reason='no_matching_rule'
        except (ValueError,TypeError,AttributeError):reason='rule_scope_unavailable'
    eid=uuid4();event=CommentEvent(id=eid,seller_id=seller_id,comment_id=cid,media_id=media_id,
        actor_id=actor_id,text=text,commented_at=timestamp,rule_id=rule_id,
        source_account_id=account_id if proof else None,source_binding=proof,
        source_verified_at=datetime.now(timezone.utc) if proof else None,source_verification=verification if proof else None)
    if rule_id is not None:
        selected=await policy.context(db,seller_id,rule_id)
        reason=policy.eligibility(selected,event)
        if reason is None and policy.source_config(first)!=policy.source_config(selected):reason='source_configuration_changed'
    event.status='queued' if reason is None else 'review_required'
    event.reason=reason
    values={key:getattr(event,key) for key in ('id','seller_id','comment_id','media_id','actor_id','text','commented_at','rule_id',
        'source_account_id','source_binding','source_verified_at','source_verification','status','reason')}
    inserted=await db.scalar(insert(CommentEvent).values(**values).on_conflict_do_nothing(constraint='comment_event_once').returning(CommentEvent.id))
    if not inserted or reason:return inserted
    link=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/shop/{selected.config['store']['slug']}?product={selected.rule['product_id']}"
    from app.models.comment_automation import CommentActionAudit
    from uuid import uuid5
    bodies=[('private',selected.rule['private_reply']+'\n'+link)]
    if selected.rule['public_reply']:bodies.append(('public',selected.rule['public_reply']))
    for kind,body in bodies:
        aid=uuid4();claim=accepted_claim(event,kind,body,selected.config)
        db.add(CommentAction(id=aid,seller_id=seller_id,event_id=eid,kind=kind,body=body,
            accepted_claim=claim,claim_hash=digest(claim),status='pending'))
        await db.flush()
        db.add(CommentActionAudit(id=uuid5(aid,'accepted'),seller_id=seller_id,event_id=eid,action_id=aid,
            stage='accepted',after_status='pending'))
    await db.flush()
    return eid
