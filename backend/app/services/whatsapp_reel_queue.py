"""Seller-owned unresolved reel inbox and transactional link/resume action."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, or_

from app.models.product import Product
from app.models.whatsapp import WhatsAppMessage, WhatsAppContact
from app.services import whatsapp as service
from app.services.whatsapp_context import instagram_references, reel_catalogue_reply


def pending_query(seller_id):
    return select(WhatsAppMessage).where(
        WhatsAppMessage.seller_id == seller_id,
        WhatsAppMessage.direction == 'inbound',
        or_(*(WhatsAppMessage.payload.contains({'reel_context': {'references': [{'status': status}]}})
              for status in ('unlinked', 'ambiguous'))),
    ).order_by(WhatsAppMessage.created_at.desc(), WhatsAppMessage.id)


def references(message):
    return (message.payload or {}).get('reel_context', {}).get('references', [])


def product_index(products):
    index = {}
    for product in products:
        for ref in instagram_references(' '.join(u for u in product.reel_urls or [] if isinstance(u, str))):
            index.setdefault(ref['shortcode'], []).append(product)
    return index


async def queue_groups(db, seller_id):
    products = (await db.scalars(select(Product).where(Product.seller_id == seller_id, Product.active.is_(True)))).all()
    index = product_index(products)
    groups = {}
    # No hard cutoff: pagination is over reel groups, not arbitrary messages.
    rows = await db.stream_scalars(pending_query(seller_id))
    async for message in rows:
        for ref in references(message):
            code = ref.get('shortcode')
            if ref.get('status') not in {'unlinked', 'ambiguous'} or len(index.get(code, [])) == 1:
                continue
            group = groups.setdefault(code, {'shortcode': code, 'url': ref['url'], 'status': 'ambiguous' if index.get(code) else 'unlinked', 'messages': [], 'products': [{'id': str(p.id), 'name': p.name} for p in index.get(code, [])]})
            group['messages'].append(message)
    return list(groups.values())


async def list_queue(db, seller_id, offset=0, limit=20):
    groups = await queue_groups(db, seller_id)
    contact_ids = {m.contact_id for group in groups[offset:offset + limit] for m in group['messages']}
    contacts = {c.id: c for c in (await db.scalars(select(WhatsAppContact).where(WhatsAppContact.seller_id == seller_id, WhatsAppContact.id.in_(contact_ids)))).all()}
    items = []
    for group in groups[offset:offset + limit]:
        rows = group['messages']
        items.append({k: v for k, v in group.items() if k != 'messages'} | {
            'message_count': len(rows), 'customer_count': len({m.contact_id for m in rows}),
            'last_received_at': rows[0].created_at,
            'previews': [message_preview(m, contacts[m.contact_id]) for m in rows[:3]],
        })
    return {'items': items, 'total': len(groups), 'offset': offset, 'has_more': offset + limit < len(groups)}


def message_preview(message, contact):
    return {'id': message.id, 'contact_id': contact.id, 'customer_name': contact.name or contact.phone,
            'text': message.text, 'created_at': message.created_at, 'opted_out': contact.opted_out,
            'reply_window_open': service.window_open(contact)}


async def queue_messages(db, seller_id, shortcode, offset=0, limit=25):
    groups = await queue_groups(db, seller_id)
    group = next((g for g in groups if g['shortcode'] == shortcode), None)
    if not group:
        raise HTTPException(404, 'This reel no longer needs a product link; refresh the queue')
    rows = group['messages'][offset:offset + limit]
    contacts = {c.id: c for c in (await db.scalars(select(WhatsAppContact).where(WhatsAppContact.seller_id == seller_id, WhatsAppContact.id.in_({m.contact_id for m in rows})))).all()}
    return {'items': [message_preview(m, contacts[m.contact_id]) for m in rows], 'total': len(group['messages']), 'has_more': offset + limit < len(group['messages'])}


async def link_and_resume(db, seller_id, shortcode, product_id, resume):
    # Same account lock as ingestion and delivery: repeat clicks/webhook retries
    # cannot race the mapping update and outbox writes.
    account = await service.account_for(db, seller_id, lock=True)
    products = (await db.scalars(select(Product).where(Product.seller_id == seller_id, Product.active.is_(True)).with_for_update())).all()
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(404, 'Choose an active product from your catalogue')
    index = product_index(products)
    if any(p.id != product.id for p in index.get(shortcode, [])):
        raise HTTPException(409, 'This reel is already linked to another active product. Remove the conflicting link in Products, then refresh.')
    rows = [m for m in (await db.scalars(pending_query(seller_id).with_for_update())).all()
            if any(r.get('shortcode') == shortcode and r.get('status') in {'unlinked', 'ambiguous'} for r in references(m))]
    if not rows and product not in index.get(shortcode, []):
        raise HTTPException(404, 'No unresolved customer message for this reel')
    canonical = next((r['url'] for m in rows for r in references(m) if r.get('shortcode') == shortcode), f'https://www.instagram.com/reel/{shortcode}/')
    product.reel_urls = list(dict.fromkeys([*(product.reel_urls or []), canonical]))
    latest_per_contact = {}
    for message in rows:
        latest_per_contact.setdefault(message.contact_id, message)
        payload = deepcopy(message.payload)
        for ref in payload['reel_context']['references']:
            if ref.get('shortcode') == shortcode:
                ref.update(status='matched', products=[{'id': str(product.id), 'name': product.name}])
        payload.setdefault('reel_links', {})[shortcode] = {'product_id': str(product.id), 'linked_at': service.now().isoformat()}
        message.payload = payload
    await db.flush()
    queued, skipped = 0, Counter()
    for contact_id, message in latest_per_contact.items():
        contact = await service.contact_for(db, seller_id, contact_id, lock=True)
        reason = None
        if not resume:
            reason = 'resume_not_requested'
        elif not (account.enabled and account.automation_enabled and account.reel_replies_enabled):
            reason = 'automation_paused'
        elif contact.opted_out:
            reason = 'opted_out'
        elif not service.window_open(contact) or message.created_at < service.now() - timedelta(hours=24):
            reason = 'reply_window_closed'
        elif message.phone_number_id != account.phone_number_id:
            reason = 'account_changed'
        latest = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == seller_id, WhatsAppMessage.contact_id == contact_id, WhatsAppMessage.direction == 'inbound').order_by(WhatsAppMessage.created_at.desc(), WhatsAppMessage.id).limit(1))
        if not reason and latest.id != message.id:
            reason = 'newer_customer_message'
        attempted = await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id == seller_id, WhatsAppMessage.contact_id == contact_id, WhatsAppMessage.direction == 'outbound', WhatsAppMessage.created_at >= message.created_at).limit(1))
        if not reason and attempted:
            reason = 'reply_already_attempted'
        if not reason and message.text.strip().casefold() in {'stop', 'unsubscribe', 'start'}:
            reason = 'consent_command'
        text = None if reason else await reel_catalogue_reply(db, seller_id, message.payload['reel_context'], message.text)
        if not reason and not text:
            reason = 'needs_manual_reply'
        if reason:
            skipped[reason] += 1
            continue
        await service.queue_message(db, account, contact, key=f'auto:reel:{message.provider_message_id}', text=text,
            context={'reel_context': message.payload['reel_context'], 'customer_text': message.text})
        queued += 1
    return {'product_id': product.id, 'product_name': product.name, 'updated_messages': len(rows), 'queued_replies': queued, 'skipped': dict(skipped)}
