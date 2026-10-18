"""Native, tenant-scoped inspection and no-send review commands.

No provider calls, commits, accepted action mutation or outgoing message creation.
The router supplies a fresh native authority callback around awaited boundaries.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import exists, select, text, tuple_

from app.config import settings
from app.models.comment_automation import CommentAction, CommentEvent, CommentRule
from app.models.comment_operator import (CommentOperatorCommand as Command, CommentOperatorReview as Review,
    WhatsAppEnquiryReview as Enquiry, WhatsAppEnquiryClosure as Closure)
from app.models.product import Product
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage
from app.services import comment_binding as policy
from app.services.identity import require_business_access


def canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def stale(message='The saved facts changed. Refresh and review them again.'):
    # Only called after receipt lookup, before any operator mutation.
    raise HTTPException(409, {'code': 'comment_operator_context_changed', 'message': message})


async def access(db, actor, business_id, authority=None, *, write=False):
    if actor.auth_method != 'v1_user':
        raise HTTPException(401, 'Native sign-in is required')
    if authority:
        await authority()
    return await require_business_access(db, actor, business_id, 'automation.manage' if write else 'inbox.read')


async def one(db, model, business_id, resource_id, *, lock=False):
    column = model.seller_id if hasattr(model, 'seller_id') else model.business_id
    query = select(*model.__table__.columns).where(column == business_id, model.id == resource_id)
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query.execution_options(autoflush=False))).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, 'Record not found')
    return dict(row)


def rule_view(row):
    keys = ('id', 'name', 'enabled', 'media_id', 'keywords', 'product_id', 'private_reply', 'public_reply', 'created_at')
    return {key: canonical(row[key]) for key in keys} | {'fingerprint': fingerprint(row)}


def outcome(row):
    if row['provider_id']:
        return 'provider_accepted'
    if not row['accepted_claim'] or row['attempted_at'] or row['claim_token'] or row['status'] in {'sending', 'unknown', 'sent'}:
        return 'not_confirmed'
    return 'not_attempted'


async def actions(db, business_id, event_id):
    return [dict(row) for row in (await db.execute(select(*CommentAction.__table__.columns).where(
        CommentAction.seller_id == business_id, CommentAction.event_id == event_id)
        .order_by(CommentAction.id).execution_options(autoflush=False))).mappings()]


def event_fingerprint(event, rows):
    return fingerprint({'event': event, 'actions': rows})


async def command_receipt(db, actor, business_id, operation, body, resource_id, authority):
    # Serialize only this exact command, without a Business lock or catalogue lock.
    key = str(body.idempotency_key)
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'),
        {'scope': 'native-comment-command:' + str(business_id) + ':' + key})
    await access(db, actor, business_id, authority, write=True)
    request_hash = fingerprint({'operation': operation, 'resource_id': resource_id, 'body': body.model_dump(mode='json')})
    row = (await db.execute(select(*Command.__table__.columns).where(Command.business_id == business_id,
        Command.idempotency_key == body.idempotency_key).execution_options(autoflush=False))).mappings().one_or_none()
    if row:
        if row['actor_id'] != actor.user_id or row['operation'] != operation or row['request_hash'] != request_hash:
            raise HTTPException(409, 'This command key belongs to different saved facts or another reviewer')
        await access(db, actor, business_id, authority, write=True)
        return request_hash, {'command_id': str(row['id']), 'idempotency_key': key, 'operation': operation,
            'request_hash': request_hash, 'result': row['result'], 'replayed': True}
    return request_hash, None


async def record(db, actor, business_id, operation, body, request_hash, resource_id, accepted_fingerprint):
    command = Command(id=uuid4(), business_id=business_id, actor_id=actor.user_id,
        operation=operation, idempotency_key=body.idempotency_key, request_hash=request_hash,
        result={'resource_id': str(resource_id), 'fingerprint': accepted_fingerprint})
    db.add(command)
    await db.flush()
    return command, {'command_id': str(command.id), 'idempotency_key': str(body.idempotency_key), 'operation': operation,
        'request_hash': request_hash, 'result': command.result, 'replayed': False}


async def validate_rule(db, business_id, facts):
    query = select(Product.id).where(Product.id == facts.product_id, Product.seller_id == business_id, Product.active.is_(True))
    if await db.scalar(query.execution_options(autoflush=False)) is None:
        stale('The selected product is unavailable. Select a current product from this business.')
    from app.services.sku_fact_replies import is_activated
    if facts.enabled and await is_activated(db, business_id, facts.product_id):
        stale('Static comment replies cannot be enabled for an activated catalogue product.')
    if facts.enabled:
        current = await policy.context(db, business_id)
        reason = current.source_reason() if current else 'business_unavailable'
        from app.services.comment_automation import product_link
        if reason:
            stale('Account access or channel controls need attention before enabling this rule.')
        await product_link(db, business_id, facts.product_id)


async def save_rule(db, actor, business_id, body, *, rule_id=None, disable=False, authority=None):
    await access(db, actor, business_id, authority, write=True)
    operation = 'rule_disable' if disable else 'rule_update' if rule_id else 'rule_create'
    request_hash, replay = await command_receipt(db, actor, business_id, operation, body, rule_id, authority)
    if replay:
        return replay
    row = await one(db, CommentRule, business_id, rule_id, lock=True) if rule_id else None
    await access(db, actor, business_id, authority, write=True)
    if row and body.expected_fingerprint != fingerprint(row):
        stale()
    if not row and body.expected_fingerprint is not None:
        stale('A new rule cannot replace an earlier saved rule.')
    if disable:
        values = {'enabled': False}
    else:
        await validate_rule(db, business_id, body.facts)
        values = body.facts.model_dump()
    await access(db, actor, business_id, authority, write=True)
    if row:
        # The native scalar lock above is current; do not refresh unrelated ORM state.
        from sqlalchemy import update
        await db.execute(update(CommentRule).where(CommentRule.id == rule_id, CommentRule.seller_id == business_id)
            .values(**values).execution_options(synchronize_session=False))
    else:
        rule = CommentRule(id=uuid4(), seller_id=business_id, **values)
        db.add(rule)
        rule_id = rule.id
    await db.flush()
    row = await one(db, CommentRule, business_id, rule_id)
    _, result = await record(db, actor, business_id, operation, body, request_hash, rule_id, fingerprint(row))
    await access(db, actor, business_id, authority, write=True)
    return result


async def close_comment(db, actor, business_id, event_id, body, *, authority=None):
    await access(db, actor, business_id, authority, write=True)
    request_hash, replay = await command_receipt(db, actor, business_id, 'comment_close', body, event_id, authority)
    if replay:
        return replay
    # Never acquire an Action lock while holding Event; sender is Action→Event.
    event = await one(db, CommentEvent, business_id, event_id, lock=True)
    await access(db, actor, business_id, authority, write=True)
    rows = await actions(db, business_id, event_id)
    expected = event_fingerprint(event, rows)
    if any(row['status'] in {'pending', 'sending'} for row in rows):
        stale('An action is still waiting or running. Its result must settle before this review can be closed.')
    if body.expected_fingerprint != expected:
        stale()
    if await db.scalar(select(Review.id).where(Review.business_id == business_id, Review.event_id == event_id)):
        stale('This event was already reviewed. Refresh its history.')
    command, result = await record(db, actor, business_id, 'comment_close', body, request_hash, event_id, expected)
    db.add(Review(business_id=business_id, event_id=event_id, command_id=command.id, reason=body.reason))
    await db.flush()
    await access(db, actor, business_id, authority, write=True)
    return result


async def close_enquiry(db, actor, business_id, enquiry_id, body, *, authority=None):
    await access(db, actor, business_id, authority, write=True)
    request_hash, replay = await command_receipt(db, actor, business_id, 'enquiry_close', body, enquiry_id, authority)
    if replay:
        return replay
    enquiry = await one(db, Enquiry, business_id, enquiry_id, lock=True)
    await access(db, actor, business_id, authority, write=True)
    if body.expected_fingerprint != fingerprint(enquiry):
        stale()
    if await db.scalar(select(Closure.id).where(Closure.business_id == business_id, Closure.enquiry_id == enquiry_id)):
        stale('This enquiry was already reviewed. Refresh its history.')
    command, result = await record(db, actor, business_id, 'enquiry_close', body, request_hash, enquiry_id, fingerprint(enquiry))
    db.add(Closure(business_id=business_id, enquiry_id=enquiry_id, command_id=command.id, reason=body.reason))
    await db.flush()
    await access(db, actor, business_id, authority, write=True)
    return result


def cursor_token(business_id, kind, state, row):
    return jwt.encode({'purpose': 'comment-operator-page.v1', 'business': str(business_id), 'kind': kind,
        'state': state, 'created_at': canonical(row['created_at']), 'id': str(row['id']),
        'exp': datetime.now(timezone.utc) + timedelta(minutes=30)}, settings.SECRET_KEY, algorithm='HS256')


def cursor_values(token, business_id, kind, state):
    try:
        row = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        if row['purpose'] != 'comment-operator-page.v1' or row['business'] != str(business_id) or row['kind'] != kind or row['state'] != state:
            raise ValueError()
        timestamp = datetime.fromisoformat(row['created_at'])
        if timestamp.utcoffset() is None:
            raise ValueError()
        return timestamp, UUID(row['id'])
    except (JWTError, ValueError, TypeError, KeyError):
        raise HTTPException(400, 'This page cursor is unavailable. Refresh the list.') from None


async def list_rows(db, actor, business_id, kind, *, state='open', cursor=None, limit=20, authority=None):
    if kind not in {'events', 'rules', 'enquiries'} or state not in {'open', 'closed', 'all'} or not 1 <= limit <= 50:
        raise HTTPException(422, 'Choose a valid list and filter')
    await access(db, actor, business_id, authority)
    model = {'events': CommentEvent, 'rules': CommentRule, 'enquiries': Enquiry}[kind]
    tenant = model.seller_id if hasattr(model, 'seller_id') else model.business_id
    query = select(*model.__table__.columns).where(tenant == business_id)
    if kind != 'rules' and state != 'all':
        reviewed = exists(select(Review.id).where(Review.business_id == business_id, Review.event_id == CommentEvent.id)) if kind == 'events' else exists(select(Closure.id).where(Closure.business_id == business_id, Closure.enquiry_id == Enquiry.id))
        query = query.where(~reviewed if state == 'open' else reviewed)
    if cursor:
        query = query.where(tuple_(model.created_at, model.id) < cursor_values(cursor, business_id, kind, state))
    rows = [dict(row) for row in (await db.execute(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
        .execution_options(autoflush=False))).mappings()]
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        if kind == 'rules':
            items.append(rule_view(row))
        elif kind == 'events':
            items.append(await event_detail(db, actor, business_id, row['id'], authority=authority))
        else:
            items.append(await enquiry_detail(db, actor, business_id, row['id'], authority=authority))
    final = await access(db, actor, business_id, authority)
    if 'automation.manage' not in final.capabilities:
        for item in items:
            if 'can_close' in item:
                item['can_close'] = False
    return {'items': items, 'next_cursor': cursor_token(business_id, kind, state, rows[-1]) if more and rows else None,
        'can_manage': 'automation.manage' in final.capabilities}


async def event_detail(db, actor, business_id, event_id, *, authority=None):
    await access(db, actor, business_id, authority)
    event = await one(db, CommentEvent, business_id, event_id)
    rows = await actions(db, business_id, event_id)
    current = await policy.context(db, business_id, event['rule_id'])
    reason = policy.eligibility(current, SimpleNamespace(**event)) if event['source_binding'] else 'legacy_binding_unverified'
    review = (await db.execute(select(Review.reason, Review.created_at).where(Review.business_id == business_id,
        Review.event_id == event_id))).mappings().one_or_none()
    final = await access(db, actor, business_id, authority)
    return {'id': str(event_id), 'text': event['text'], 'media_id': event['media_id'], 'created_at': canonical(event['created_at']),
        'source_time': canonical(event['commented_at']), 'status': event['status'], 'reason': event['reason'], 'eligibility_reason': reason,
        'actions': [{'kind': row['kind'], 'status': row['status'], 'body': row['body'], 'reason': row['error_code'], 'delivery_state': outcome(row)} for row in rows],
        'review': canonical(dict(review)) if review else None, 'fingerprint': event_fingerprint(event, rows),
        'can_close': not review and not any(row['status'] in {'pending', 'sending'} for row in rows) and 'automation.manage' in final.capabilities}


async def enquiry_detail(db, actor, business_id, enquiry_id, *, authority=None):
    await access(db, actor, business_id, authority)
    row = await one(db, Enquiry, business_id, enquiry_id)
    message = await one(db, WhatsAppMessage, business_id, row['inbound_message_id'])
    contact = await one(db, WhatsAppContact, business_id, row['contact_id'])
    closure = (await db.execute(select(Closure.reason, Closure.created_at).where(Closure.business_id == business_id,
        Closure.enquiry_id == enquiry_id))).mappings().one_or_none()
    final = await access(db, actor, business_id, authority)
    return {'id': str(enquiry_id), 'inbound_message_id': str(row['inbound_message_id']), 'message': message['text'],
        'customer_name': contact['name'], 'customer_ref': contact['phone'][-4:], 'created_at': canonical(row['created_at']),
        'reason': row['reason'], 'review': canonical(dict(closure)) if closure else None, 'fingerprint': fingerprint(row),
        'can_close': not closure and 'automation.manage' in final.capabilities}


async def product_choices(db, actor, business_id, *, cursor=None, authority=None):
    from app.models.checkout_v1 import CatalogueActivation
    await access(db, actor, business_id, authority)
    activated = exists(select(CatalogueActivation.product_id).where(CatalogueActivation.business_id == business_id,
        CatalogueActivation.product_id == Product.id))
    query = select(Product.id, Product.name, Product.created_at, activated.label('activated')).where(
        Product.seller_id == business_id, Product.active.is_(True))
    if cursor:
        query = query.where(tuple_(Product.created_at, Product.id) < cursor_values(cursor, business_id, 'products', 'active'))
    rows = [dict(row) for row in (await db.execute(query.order_by(Product.created_at.desc(), Product.id.desc())
        .limit(51).execution_options(autoflush=False))).mappings()]
    more = len(rows) > 50
    rows = rows[:50]
    await access(db, actor, business_id, authority)
    return {'items': [{'id': str(row['id']), 'name': row['name'], 'activated': row['activated']} for row in rows],
        'next_cursor': cursor_token(business_id, 'products', 'active', rows[-1]) if more and rows else None}


async def preview(db, actor, business_id, body, *, authority=None):
    await access(db, actor, business_id, authority, write=True)
    rule = await one(db, CommentRule, business_id, body.rule_id)
    current = await policy.context(db, business_id, body.rule_id)
    from app.services.comment_automation import matches, public_base_ready
    reason = (current.source_reason() or ('activated_context_requires_review' if current.activated else
        'rule_configuration_changed' if not current.rule.get('enabled') else
        'product_context_unbound' if current.rule.get('media_id') != body.media_id else
        'product_context_unavailable' if not current.product_available or not current.published else
        'configuration_unavailable' if not public_base_ready() else None)) if current else 'business_unavailable'
    await access(db, actor, business_id, authority, write=True)
    return {'matches': matches(SimpleNamespace(**rule), body.text, body.media_id), 'private_reply': rule['private_reply'],
        'public_reply': rule['public_reply'], 'withheld_reason': reason, 'sends': False}
