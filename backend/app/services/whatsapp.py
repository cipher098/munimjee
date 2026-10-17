"""WhatsApp conversation policy, inbound ingestion and transactional outbox."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import re
from fastapi import HTTPException
from sqlalchemy import select, delete
from app.config import settings
from app.models.seller import Seller
from app.models.product import Product
from app.models.commerce import Storefront
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services import whatsapp_provider as provider
from app.services.whatsapp_context import inbound_context, reel_catalogue_reply


def now():
    return datetime.now(timezone.utc)


def window_open(contact):
    return bool(contact.last_inbound_at and now() - timedelta(hours=24) < contact.last_inbound_at <= now() + timedelta(minutes=5))


def normalize_phone(phone):
    clean = re.sub(r'[\s()+-]', '', str(phone))
    # Commerce checkout currently accepts Indian mobile numbers.
    if re.fullmatch(r'[6-9]\d{9}', clean):
        clean = '91' + clean
    if not re.fullmatch(r'[1-9]\d{7,14}', clean):
        raise HTTPException(422, 'Use an international phone number including country code')
    return clean


async def account_for(db, seller_id, *, enabled=False, lock=False):
    stmt = select(WhatsAppAccount).join(Seller, Seller.id == WhatsAppAccount.seller_id).where(WhatsAppAccount.seller_id == seller_id, Seller.is_active.is_(True))
    if lock:
        stmt = stmt.with_for_update(of=WhatsAppAccount)
    account = await db.scalar(stmt)
    if not account or (enabled and not account.enabled):
        raise HTTPException(409, 'Connect and enable WhatsApp first')
    return account


async def contact_for(db, seller_id, contact_id, *, lock=False):
    stmt = select(WhatsAppContact).where(WhatsAppContact.id == contact_id, WhatsAppContact.seller_id == seller_id)
    if lock:
        stmt = stmt.with_for_update()
    contact = await db.scalar(stmt)
    if not contact:
        raise HTTPException(404, 'Contact not found')
    return contact


def check_template(template, contact, parameters):
    if not template or template.status != 'APPROVED':
        raise HTTPException(409, 'Use a currently approved template; sync templates first')
    if template.category not in {'UTILITY', 'MARKETING'}:
        raise HTTPException(422, 'Only utility and marketing templates are supported')
    if contact.opted_out or not getattr(contact, 'utility_opt_in' if template.category == 'UTILITY' else 'marketing_opt_in'):
        raise HTTPException(409, 'This contact has not consented to this message category')
    body = ''
    for component in template.components:
        kind = component.get('type', '').upper()
        if kind == 'BODY':
            body = component.get('text', '')
        elif kind != 'FOOTER':
            raise HTTPException(422, 'Only text body templates with an optional footer are supported')
    placeholders = re.findall(r'{{(.*?)}}', body)
    if any(not p.isdigit() for p in placeholders):
        raise HTTPException(422, 'Use a template with numbered body parameters')
    nums = sorted({int(p) for p in placeholders})
    if nums != list(range(1, len(nums) + 1)) or len(parameters) != len(nums):
        raise HTTPException(422, f'This template requires {len(nums)} body parameters')


async def sync_templates(db, account):
    rows = await provider.fetch_templates(account)
    await db.execute(delete(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == account.seller_id))
    for row in rows:
        if all(isinstance(row.get(key), str) for key in ('name','language','status','category')):
            db.add(WhatsAppTemplate(seller_id=account.seller_id, name=row['name'], language=row['language'], status=row['status'], category=row['category'], components=row.get('components', []), synced_at=now()))
    await db.flush()


async def queue_message(db, account, contact, *, key, text='', template=None, parameters=None, context=None):
    existing = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == account.seller_id, WhatsAppMessage.idempotency_key == key))
    payload = {} if not template else {'name':template.name,'language':template.language,'parameters':parameters or []}
    if context and not template:
        payload = context
    if existing:
        if existing.contact_id != contact.id or existing.text != text or existing.payload != payload:
            raise HTTPException(409, 'This idempotency key was used for a different message')
        return existing
    if not account.enabled or contact.opted_out:
        raise HTTPException(409, 'Messaging is disabled or this contact has opted out')
    if template:
        check_template(template, contact, parameters or [])
    elif not window_open(contact):
        raise HTTPException(409, 'The 24-hour reply window has closed; use an approved, consented template')
    message = WhatsAppMessage(seller_id=account.seller_id, contact_id=contact.id, phone_number_id=account.phone_number_id, idempotency_key=key, direction='outbound', kind='template' if template else 'text', text=text, payload=payload, status='queued')
    db.add(message)
    await db.flush()
    return message


def record_consent(contact, utility, marketing, source, *, at=None):
    timestamp = at or now().replace(microsecond=0)
    contact.utility_opt_in = utility
    contact.marketing_opt_in = marketing
    contact.consent_updated_at = timestamp
    contact.consent_history = [*(contact.consent_history or []), {'at':timestamp.isoformat(),'utility_opt_in':utility,'marketing_opt_in':marketing,'source':source}]


async def record_checkout_opt_in(db, seller_id, phone, consent):
    if not consent:
        return
    # Account lock serializes contact upserts with inbound webhooks.
    account = await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id == seller_id).with_for_update())
    if not account:
        return
    phone = normalize_phone(phone)
    contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id == seller_id, WhatsAppContact.phone == phone).with_for_update())
    if not contact:
        contact = WhatsAppContact(seller_id=seller_id, phone=phone)
        db.add(contact)
        await db.flush()
    if not contact.opted_out:
        record_consent(contact, True, bool(contact.marketing_opt_in), 'storefront_checkout_explicit_checkbox')


async def queue_order_update(db, order, event):
    account = await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id == order.seller_id).with_for_update())
    if not getattr(order, 'whatsapp_updates_opt_in', False) or not account or not account.enabled or event not in {'placed','confirmed','shipped','delivered'}:
        return 'skipped'
    mapping = (account.order_templates or {}).get(event)
    if not mapping:
        return 'skipped'
    phone = normalize_phone(order.customer['phone'])
    contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id == order.seller_id, WhatsAppContact.phone == phone).with_for_update())
    if not contact or contact.opted_out or not contact.utility_opt_in:
        return 'skipped'
    template = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == order.seller_id, WhatsAppTemplate.name == mapping['name'], WhatsAppTemplate.language == mapping['language'], WhatsAppTemplate.category == 'UTILITY'))
    parameters = [order.customer['name'], 'MJ-' + order.id.hex[:12].upper(), (order.tracking_url or order.tracking_number or 'Tracking will follow') if event == 'shipped' else f'{order.currency} {order.total / 100:.2f}']
    try:
        await queue_message(db, account, contact, key=f'order:{order.id}:{event}', template=template, parameters=parameters) if template else None
    except HTTPException:
        return 'skipped'
    return 'queued' if template else 'skipped'


async def ingest(db, payload):
    if payload.get('object') != 'whatsapp_business_account':
        return
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            if change.get('field') != 'messages':
                continue
            value = change.get('value') or {}
            phone_id = (value.get('metadata') or {}).get('phone_number_id')
            account = await db.scalar(select(WhatsAppAccount).join(Seller, Seller.id == WhatsAppAccount.seller_id).where(WhatsAppAccount.phone_number_id == phone_id, WhatsAppAccount.waba_id == str(entry.get('id')), Seller.is_active.is_(True)).with_for_update(of=WhatsAppAccount))
            if not account:
                continue
            for event in value.get('messages', []):
                await ingest_message(db, account, value, event)
            for event in value.get('statuses', []):
                await ingest_status(db, account, event)


async def ingest_message(db, account, value, event):
    mid, phone = event.get('id'), event.get('from')
    if not isinstance(mid, str) or len(mid) > 255 or not isinstance(phone, str) or not re.fullmatch(r'[1-9]\d{7,14}', phone):
        return
    if await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id == account.seller_id, WhatsAppMessage.provider_message_id == mid)):
        return
    try:
        timestamp = datetime.fromtimestamp(int(event['timestamp']), timezone.utc)
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return
    if timestamp > now() + timedelta(minutes=5):
        return
    contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id == account.seller_id, WhatsAppContact.phone == phone).with_for_update())
    first = contact is None
    if not contact:
        profile = next((x.get('profile', {}) for x in value.get('contacts', []) if x.get('wa_id') == phone), {})
        contact = WhatsAppContact(seller_id=account.seller_id, phone=phone, name=str(profile.get('name', ''))[:200])
        db.add(contact)
        await db.flush()
    kind = event.get('type', 'unsupported')
    text = str((event.get('text') or {}).get('body', ''))[:4096] if kind == 'text' else f'[{kind} message]'
    if kind in {'image', 'video', 'document'} and isinstance(event.get(kind), dict):
        caption = event[kind].get('caption')
        if isinstance(caption, str) and caption:
            text += '\n' + caption[:4096]
    context = await inbound_context(db, account, contact, event, text)
    db.add(WhatsAppMessage(seller_id=account.seller_id, contact_id=contact.id, phone_number_id=account.phone_number_id, provider_message_id=mid, idempotency_key=f'in:{mid}', direction='inbound', kind=str(kind)[:30], text=text, payload=context, status='received', created_at=timestamp))
    contact.last_inbound_at = max(contact.last_inbound_at or timestamp, timestamp)
    command = text.strip().casefold() if kind == 'text' else ''
    # Older deliveries cannot reverse a more recent consent decision.
    if command in {'stop','unsubscribe','start'} and (not contact.consent_updated_at or timestamp >= contact.consent_updated_at):
        contact.opted_out = command != 'start'
        # START reopens replies only; it does not create marketing/utility consent.
        record_consent(contact, False, False, f'inbound:{command}:{mid}', at=timestamp)
    await db.flush()
    if command in {'stop','unsubscribe','start'} or contact.opted_out or not account.enabled or not account.automation_enabled or not window_open(contact) or timestamp < now() - timedelta(hours=24):
        return
    if account.reel_replies_enabled and context.get('reel_context'):
        reply = await reel_catalogue_reply(db, account.seller_id, context['reel_context'], text)
        if reply:
            await queue_message(db, account, contact, key=f'auto:reel:{mid}', text=reply,
                context={'reel_context': context['reel_context'], 'customer_text': text})
        return
    reply, product_id = '', None
    for rule in account.rules or []:
        if command == rule['keyword'].strip().casefold():
            reply, product_id = rule['reply'], rule.get('product_id')
            break
    if not reply and first:
        reply = account.welcome_message
    if not reply:
        return
    store = await db.get(Storefront, account.seller_id)
    base_url = getattr(settings, 'PUBLIC_BASE_URL', '').rstrip('/')
    if '{store_url}' in reply or product_id:
        if not store or not store.published or not base_url.startswith('https://'):
            return
        store_url = base_url + '/shop/' + store.slug
        reply = reply.replace('{store_url}', store_url)
        if product_id:
            product = await db.scalar(select(Product).where(Product.id == UUID(product_id), Product.seller_id == account.seller_id, Product.active.is_(True)))
            if not product:
                return
            reply += '\n' + store_url + '?product=' + str(product.id)
    await queue_message(db, account, contact, key=f'auto:{mid}', text=reply[:4096])


async def ingest_status(db, account, event):
    status = event.get('status')
    if status not in {'sent','delivered','read','failed'}:
        return
    message = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == account.seller_id, WhatsAppMessage.provider_message_id == event.get('id'), WhatsAppMessage.direction == 'outbound').with_for_update()) if event.get('id') else None
    if not message and event.get('biz_opaque_callback_data'):
        try:
            callback_id = UUID(event['biz_opaque_callback_data'])
        except (ValueError, TypeError):
            return
        message = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.id == callback_id, WhatsAppMessage.seller_id == account.seller_id, WhatsAppMessage.direction == 'outbound', WhatsAppMessage.phone_number_id == account.phone_number_id).with_for_update())
    if not message or message.phone_number_id != account.phone_number_id:
        return
    contact = await db.get(WhatsAppContact, message.contact_id)
    if event.get('recipient_id') != contact.phone:
        return
    if message.provider_message_id and message.provider_message_id != event.get('id'):
        return
    if not message.provider_message_id:
        if message.status not in {'sending','unknown'} or not event.get('id'):
            return
        message.provider_message_id = event['id']
    rank = {'queued':0,'sending':0,'unknown':0,'failed':0,'accepted':0,'sent':1,'delivered':2,'read':3}
    if status == 'failed':
        if rank.get(message.status, 0) < 2:
            message.status = 'failed'
            codes = [str(x.get('code','unknown'))[:20] for x in event.get('errors', [])]
            message.error = 'WhatsApp delivery failed' + (': ' + ', '.join(codes) if codes else '')
    elif rank[status] > rank.get(message.status, 0) and not (message.status == 'failed' and status == 'sent'):
        message.status, message.error = status, None


async def order_updates_available(db, seller_id):
    account = await db.get(WhatsAppAccount,seller_id)
    if not account or not account.enabled or not account.access_token:
        return False
    mapping = (account.order_templates or {}).get('placed')
    if not mapping:
        return False
    template = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id,WhatsAppTemplate.name == mapping['name'],WhatsAppTemplate.language == mapping['language'],WhatsAppTemplate.category == 'UTILITY'))
    from types import SimpleNamespace
    try:
        check_template(template,SimpleNamespace(opted_out=False,utility_opt_in=True),['name','order','detail'])
        return True
    except HTTPException:
        return False
