"""Proof of current channel control, not legal identity or permission to send.

The ingest_* functions are internal seams called ONLY after provider signature
verification and trusted account resolution. They never commit, send, or log.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text, or_, and_, exists, func
from sqlalchemy.orm import aliased
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.customer_links import Customer, CustomerLinkChallenge as Challenge, CustomerLinkProof as Proof, CustomerAssociation as Association, CustomerLinkAudit as Audit
from app.models.conversation import Conversation
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact
from app.models.seller import Seller
from app.models.identity import Business
from app.models.channel_operator import ChannelConnectionState
from app.services.identity import require_business_access

SCOPE = 'Control of these two channel accounts and consent to link their seller records only. No legal identity, marketing consent, payment access or combined message history.'
RESERVED = re.compile(r'^\s*LINK\s+[A-Za-z0-9_-]{30,}', re.IGNORECASE | re.ASCII)
EXACT = re.compile(r'^LINK ([A-Za-z0-9_-]{43}) I CONSENT$', re.ASCII)
REDACT = re.compile(r'LINK\s+[A-Za-z0-9_-]{30,}(?:\s+I\s+CONSENT)?', re.IGNORECASE | re.ASCII)


def now():
    return datetime.now(timezone.utc)


def enabled():
    return bool(getattr(settings, 'V1_CUSTOMER_LINKS_ENABLED', False))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def secret_for(challenge):
    key = settings.SECRET_KEY
    if not key:
        raise HTTPException(503, 'Customer link proof is not configured')
    raw = hmac.new(key.encode(), f'v1-customer-link:{challenge.business_id}:{challenge.id}'.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def secret_digest(secret):
    return hashlib.sha256(secret.encode('ascii')).hexdigest()


async def binding(db, business_id, *, lock=False):
    """Read current facts, with reader locks for native writes through commit.

    Seller→WA order matches connection mutations. Signed WA ingestion already
    owns WAAccount; its proof path uses scalar reads without new account locks.
    """
    query = select(Seller.id, Seller.instagram_page_id, Seller.instagram_token, Seller.instagram_token_expires_at).join(Business, Business.id == Seller.id).where(
        Seller.id == business_id, Seller.is_active.is_(True), Business.is_active.is_(True))
    if lock:
        query = query.with_for_update(read=True, of=Seller)
    seller = (await db.execute(query.execution_options(autoflush=False))).one_or_none()
    query = select(WhatsAppAccount.phone_number_id, WhatsAppAccount.waba_id, WhatsAppAccount.access_token,
        WhatsAppAccount.connected_at).where(WhatsAppAccount.seller_id == business_id)
    if lock:
        query = query.with_for_update(read=True)
    wa = (await db.execute(query.execution_options(autoflush=False))).one_or_none()
    if not seller or not seller.instagram_page_id or not seller.instagram_token or not wa or not wa.access_token:
        raise HTTPException(409, 'Both channel accounts must remain connected')
    if seller.instagram_token_expires_at and seller.instagram_token_expires_at <= now():
        raise HTTPException(409, 'Reconnect Instagram before linking accounts')
    owners = (await db.scalars(select(Seller.id).where(Seller.instagram_page_id == seller.instagram_page_id,
        Seller.is_active.is_(True)).limit(2).execution_options(autoflush=False))).all()
    if owners != [business_id]:
        raise HTTPException(409, 'The Instagram account binding needs review')
    controls = (await db.execute(select(ChannelConnectionState.channel, ChannelConnectionState.version,
        ChannelConnectionState.check_status, ChannelConnectionState.provider_account_id).where(
        ChannelConnectionState.business_id == business_id).execution_options(autoflush=False))).all()
    if any(row.check_status in {'disconnected', 'needs_reconnect'} for row in controls):
        raise HTTPException(409, 'Reconnect the channel account before linking')
    facts = {'ig': seller.instagram_page_id, 'ig_token': seller.instagram_token,
        'ig_expiry': seller.instagram_token_expires_at, 'wa': wa.phone_number_id,
        'waba': wa.waba_id, 'wa_token': wa.access_token, 'wa_connected': wa.connected_at,
        'controls': sorted(tuple(row) for row in controls)}
    return {'instagram': seller.instagram_page_id, 'whatsapp': wa.phone_number_id, 'hash': digest(facts), 'facts': facts}


async def access(db, actor, business_id, *, write=False, authority=None):
    if actor.auth_method != 'v1_user':
        raise HTTPException(401, 'A current native sign-in is required')
    if authority:
        await authority()
    return await require_business_access(db, actor, business_id, 'automation.manage' if write else 'inbox.read')


async def challenge_for(db, business_id, challenge_id, *, lock=False):
    query = select(Challenge).where(Challenge.business_id == business_id, Challenge.id == challenge_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Customer link request not found')
    return row


async def proofs_for(db, row):
    return (await db.scalars(select(Proof).where(Proof.business_id == row.business_id,
        Proof.challenge_id == row.id).order_by(Proof.channel))).all()


async def fingerprint(db, row):
    proofs = await proofs_for(db, row)
    return digest({'id': row.id, 'state': row.state, 'customer': row.customer_id,
        'binding': row.binding_hash, 'expires': row.expires_at,
        'proofs': [(p.id, p.channel, p.provider_message_id) for p in proofs]})


async def view(db, row):
    proofs = await proofs_for(db, row)
    try:
        current = (await binding(db, row.business_id))['hash'] == row.binding_hash
    except HTTPException:
        current = False
    ig_name = await db.scalar(select(Conversation.customer_name).where(Conversation.id == row.conversation_id, Conversation.seller_id == row.business_id))
    wa_name = await db.scalar(select(WhatsAppContact.name).where(WhatsAppContact.id == row.contact_id, WhatsAppContact.seller_id == row.business_id))
    active = await db.scalar(select(func.count()).select_from(Association).where(Association.business_id == row.business_id,
        Association.challenge_id == row.id, Association.customer_id == row.customer_id, Association.revoked_at.is_(None))) if row.customer_id else 0
    return {'id': str(row.id), 'business_id': str(row.business_id), 'state': row.state,
        'linked': active == 2,
        'instagram_label': f'{ig_name or "Unnamed Instagram account"} · …{row.instagram_subject[-6:]}',
        'whatsapp_label': f'{wa_name or "Unnamed WhatsApp account"} · …{row.whatsapp_subject[-6:]}',
        'expired': row.expires_at <= now(), 'binding_current': current,
        'conversation_id': str(row.conversation_id), 'contact_id': str(row.contact_id),
        'customer_id': str(row.customer_id) if row.customer_id else None,
        'issued_at': row.issued_at.isoformat(), 'expires_at': row.expires_at.isoformat(),
        'proofs': [{'channel': p.channel, 'received_at': p.received_at.isoformat()} for p in proofs],
        'fingerprint': await fingerprint(db, row), 'verification_scope': SCOPE}


async def begin(db, actor, business_id, action, payload, resource_id=None):
    # Serializes only this command key, not inbound proofs or unrelated buyers.
    key = int.from_bytes(hashlib.sha256(f'customer-command:{business_id}:{payload.idempotency_key}'.encode()).digest()[:8], 'big', signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
    request_hash = digest({'action': action, 'resource_id': resource_id, 'body': payload.model_dump(mode='json')})
    receipt = await db.scalar(select(Audit).where(Audit.business_id == business_id,
        Audit.idempotency_key == payload.idempotency_key))
    if receipt and (receipt.actor_id != actor.user_id or receipt.action != action or receipt.request_hash != request_hash):
        raise HTTPException(409, 'This command key belongs to a different action')
    return receipt, request_hash


async def record(db, actor, business_id, payload, action, request_hash, result):
    result = {**result, 'command_id': str(payload.idempotency_key)}
    db.add(Audit(id=uuid4(), business_id=business_id, actor_id=actor.user_id,
        idempotency_key=payload.idempotency_key, action=action, request_hash=request_hash, result=result))
    await db.flush()
    return result


def not_accepted(message):
    # Only called after exact receipt lookup and before any domain mutation.
    raise HTTPException(409, {'code': 'customer_link_not_accepted', 'message': message})


async def start(db, actor, business_id, payload, *, authority=None):
    await access(db, actor, business_id, write=True, authority=authority)
    receipt, request_hash = await begin(db, actor, business_id, 'create', payload)
    await access(db, actor, business_id, write=True, authority=authority)
    if receipt:
        row = await challenge_for(db, business_id, receipt.result['challenge_id'])
        return row
    if payload.scope_confirmed is not True:
        raise HTTPException(422, 'Review the limited account-link consent scope')
    current = await binding(db, business_id, lock=True)
    conversation = await db.scalar(select(Conversation).where(Conversation.id == payload.conversation_id,
        Conversation.seller_id == business_id).with_for_update(read=True))
    contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.id == payload.contact_id,
        WhatsAppContact.seller_id == business_id).with_for_update(read=True))
    if not conversation or not contact:
        raise HTTPException(404, 'Selected channel record not found')
    await access(db, actor, business_id, write=True, authority=authority)
    existing = await db.scalar(select(Association.id).where(Association.business_id == business_id,
        Association.revoked_at.is_(None), or_(Association.conversation_id == conversation.id, Association.contact_id == contact.id)).limit(1))
    if existing:
        not_accepted('A selected account already has a link. Review or unlink it first; records cannot be merged')
    issued = now().replace(microsecond=0)
    row = Challenge(id=uuid4(), business_id=business_id, created_by=actor.user_id,
        conversation_id=conversation.id, contact_id=contact.id, instagram_account=current['instagram'],
        instagram_subject=conversation.customer_instagram_id, whatsapp_account=current['whatsapp'],
        whatsapp_subject=contact.phone, binding_hash=current['hash'], state='pending',
        issued_at=issued, expires_at=issued + timedelta(minutes=10))
    row.secret_digest = secret_digest(secret_for(row))
    db.add(row)
    await db.flush()
    await record(db, actor, business_id, payload, 'create', request_hash, {'challenge_id': str(row.id)})
    return row


async def finish(db, actor, business_id, challenge_id, payload, *, cancel=False, authority=None):
    action = 'cancel' if cancel else 'finalize'
    await access(db, actor, business_id, write=True, authority=authority)
    receipt, request_hash = await begin(db, actor, business_id, action, payload, challenge_id)
    await access(db, actor, business_id, write=True, authority=authority)
    if receipt:
        return receipt.result
    try:
        current = await binding(db, business_id, lock=True) if not cancel else None
    except HTTPException as exc:
        not_accepted(str(exc.detail))
    row = await challenge_for(db, business_id, challenge_id, lock=True)
    await access(db, actor, business_id, write=True, authority=authority)
    if payload.confirmed is not True or row.state != 'pending' or payload.expected_fingerprint != await fingerprint(db, row):
        not_accepted('The link request changed. Review its current state')
    if cancel:
        row.state = 'cancelled'
        result = {'challenge_id': str(row.id), 'state': 'cancelled'}
    else:
        proofs = await proofs_for(db, row)
        expected_sources = {'instagram': (row.instagram_account, row.instagram_subject), 'whatsapp': (row.whatsapp_account, row.whatsapp_subject)}
        valid_proofs = all((p.account_id, p.subject_id) == expected_sources.get(p.channel)
            and row.issued_at <= p.provider_at <= min(row.expires_at, p.received_at + timedelta(seconds=60))
            and row.issued_at <= p.received_at < row.expires_at for p in proofs)
        if row.expires_at <= now() or current['hash'] != row.binding_hash or {p.channel for p in proofs} != {'instagram', 'whatsapp'} or not valid_proofs:
            not_accepted('Both fresh channel proofs and unchanged account connections are required')
        # Independently recheck exact source records: no profile/name/phone match.
        ig = await db.scalar(select(Conversation.customer_instagram_id).where(Conversation.id == row.conversation_id,
            Conversation.seller_id == business_id).with_for_update(read=True))
        wa = await db.scalar(select(WhatsAppContact.phone).where(WhatsAppContact.id == row.contact_id,
            WhatsAppContact.seller_id == business_id).with_for_update(read=True))
        if ig != row.instagram_subject or wa != row.whatsapp_subject:
            not_accepted('A source account changed. Start a new proof request')
        await access(db, actor, business_id, write=True, authority=authority)
        customer = Customer(id=uuid4(), business_id=business_id)
        db.add(customer)
        await db.flush()
        for channel, account, subject, conversation_id, contact_id in (
            ('instagram', row.instagram_account, row.instagram_subject, row.conversation_id, None),
            ('whatsapp', row.whatsapp_account, row.whatsapp_subject, None, row.contact_id)):
            db.add(Association(id=uuid4(), business_id=business_id, customer_id=customer.id, challenge_id=row.id,
                channel=channel, account_id=account, subject_id=subject, conversation_id=conversation_id, contact_id=contact_id))
        try:
            await db.flush()
        except IntegrityError:
            raise HTTPException(409, 'An account was linked concurrently. Review existing links; no records were merged')
        row.customer_id, row.state = customer.id, 'verified'
        result = {'challenge_id': str(row.id), 'state': 'verified', 'customer_id': str(customer.id)}
    return await record(db, actor, business_id, payload, action, request_hash, result)


async def association_fingerprint(db, business_id, customer_id):
    rows = (await db.scalars(select(Association).where(Association.business_id == business_id,
        Association.customer_id == customer_id).order_by(Association.id).execution_options(populate_existing=True))).all()
    if not rows:
        raise HTTPException(404, 'Customer account link not found')
    return digest([(r.id, r.revoked_at) for r in rows]), rows


async def unlink(db, actor, business_id, customer_id, payload, *, authority=None):
    await access(db, actor, business_id, write=True, authority=authority)
    receipt, request_hash = await begin(db, actor, business_id, 'unlink', payload, customer_id)
    await access(db, actor, business_id, write=True, authority=authority)
    if receipt:
        return receipt.result
    await db.scalars(select(Association).where(Association.business_id == business_id,
        Association.customer_id == customer_id).order_by(Association.id).with_for_update())
    await access(db, actor, business_id, write=True, authority=authority)
    expected, rows = await association_fingerprint(db, business_id, customer_id)
    if not payload.confirmed or expected != payload.expected_fingerprint or len(payload.reason.strip()) < 10:
        not_accepted('Review the current account link and add an unlink reason')
    for row in rows:
        if row.revoked_at is None:
            row.revoked_at = now()
    # The reason is a bounded operator note, not a proof or customer utterance.
    result = {'customer_id': str(customer_id), 'state': 'unlinked', 'reason': REDACT.sub('[link command withheld]', payload.reason.strip())}
    return await record(db, actor, business_id, payload, 'unlink', request_hash, result)


async def capture(db, business_id, channel, account_id, subject_id, mid, provider_at, content, *, attachments=False):
    """Reserved secrets never enter chat/LLM paths, including while disabled."""
    if not isinstance(content, str) or not RESERVED.match(content):
        return False
    match = EXACT.fullmatch(content)
    if not enabled() or not match or attachments or not isinstance(mid, str) or not 0 < len(mid) <= 255 or provider_at is None:
        return True
    received = now()
    row = await db.scalar(select(Challenge).where(Challenge.business_id == business_id,
        Challenge.secret_digest == secret_digest(match.group(1))).with_for_update().execution_options(populate_existing=True))
    if not row or row.state != 'pending' or not row.issued_at <= provider_at <= min(row.expires_at, received + timedelta(seconds=60)) or received >= row.expires_at:
        return True
    expected = (row.instagram_account, row.instagram_subject) if channel == 'instagram' else (row.whatsapp_account, row.whatsapp_subject)
    if (account_id, subject_id) != expected:
        return True
    try:
        current = await binding(db, business_id)
    except HTTPException:
        return True
    if current['hash'] != row.binding_hash:
        return True
    await db.execute(insert(Proof).values(id=uuid4(), business_id=business_id, challenge_id=row.id,
        channel=channel, account_id=account_id, subject_id=subject_id, provider_message_id=mid,
        provider_at=provider_at, received_at=received).on_conflict_do_nothing())
    return True


async def ingest_instagram_command(db, event):
    message = event.get('message') or {}
    content = message.get('text')
    if not isinstance(content, str) or not RESERVED.match(content):
        return False
    if message.get('is_echo') or not enabled():
        return True
    account = (event.get('recipient') or {}).get('id')
    subject = (event.get('sender') or {}).get('id')
    sellers = (await db.scalars(select(Seller.id).where(Seller.instagram_page_id == account,
        Seller.is_active.is_(True)).limit(2))).all()
    if len(sellers) != 1:
        return True
    from app.services.instagram_ingress import provider_event_time
    return await capture(db, sellers[0], 'instagram', account, subject, message.get('mid'),
        provider_event_time(event.get('timestamp')), content, attachments=bool(message.get('attachments')))


async def ingest_whatsapp_command(db, account, event, provider_at):
    # The caller has validated signature, account, provider mid/from/time. Never
    # use contacts[].profile or a browser tenant/phone assertion as evidence.
    body = event.get('text')
    content = body.get('body') if isinstance(body, dict) else None
    if event.get('type') != 'text':
        kind = event.get('type')
        media = event.get(kind) if isinstance(kind, str) else None
        caption = media.get('caption') if isinstance(media, dict) else None
        return any(isinstance(value, str) and RESERVED.match(value) is not None for value in (content, caption))
    return await capture(db, account.seller_id, 'whatsapp', account.phone_number_id,
        event.get('from'), event.get('id'), provider_at, content)


async def verified_customer_id(db, business_id, channel, account_id, subject_id):
    """Only an opaque current canonical ID; no history/consent personalization."""
    if not enabled() or channel not in {'instagram', 'whatsapp'}:
        return None
    try:
        current = await binding(db, business_id)
    except HTTPException:
        return None
    facts = current['facts']
    controls = facts['controls']
    matching_controls = [and_(ChannelConnectionState.channel == c, ChannelConnectionState.version == version,
        ChannelConnectionState.check_status == status, ChannelConnectionState.provider_account_id == provider)
        for c, version, status, provider in controls]
    # Compare the complete current configuration snapshot in the final SQL too;
    # no old association, source, credential or connection generation can escape
    # after an unlink/reconnect during any preceding await.
    control_checks = [~exists(select(ChannelConnectionState.business_id).where(
        ChannelConnectionState.business_id == business_id, ~or_(*matching_controls))) if controls else
        ~exists(select(ChannelConnectionState.business_id).where(ChannelConnectionState.business_id == business_id))]
    control_checks += [exists(select(ChannelConnectionState.business_id).where(
        ChannelConnectionState.business_id == business_id, item)) for item in matching_controls]
    other_seller, partner = aliased(Seller), aliased(Association)
    query = select(Association.customer_id).join(Challenge,
        (Challenge.id == Association.challenge_id) & (Challenge.business_id == Association.business_id))
    query = query.join(Seller, Seller.id == Association.business_id).join(Business, Business.id == Seller.id)
    query = query.join(WhatsAppAccount, WhatsAppAccount.seller_id == Seller.id)
    query = query.join(Conversation, (Conversation.id == Challenge.conversation_id) & (Conversation.seller_id == Seller.id))
    query = query.join(WhatsAppContact, (WhatsAppContact.id == Challenge.contact_id) & (WhatsAppContact.seller_id == Seller.id))
    query = query.where(Association.business_id == business_id, Association.channel == channel,
        Association.account_id == account_id, Association.subject_id == subject_id, Association.revoked_at.is_(None),
        Challenge.state == 'verified', Challenge.binding_hash == current['hash'],
        Conversation.customer_instagram_id == Challenge.instagram_subject, WhatsAppContact.phone == Challenge.whatsapp_subject,
        Seller.is_active.is_(True), Business.is_active.is_(True), Seller.instagram_page_id == facts['ig'],
        Seller.instagram_token == facts['ig_token'], Seller.instagram_token_expires_at == facts['ig_expiry'],
        or_(Seller.instagram_token_expires_at.is_(None), Seller.instagram_token_expires_at > func.clock_timestamp()),
        WhatsAppAccount.phone_number_id == facts['wa'], WhatsAppAccount.waba_id == facts['waba'],
        WhatsAppAccount.access_token == facts['wa_token'], WhatsAppAccount.connected_at == facts['wa_connected'],
        ~exists(select(other_seller.id).where(other_seller.id != business_id,
            other_seller.is_active.is_(True), other_seller.instagram_page_id == facts['ig'])),
        exists(select(partner.id).where(partner.business_id == business_id, partner.customer_id == Association.customer_id,
            partner.challenge_id == Challenge.id, partner.channel != channel, partner.revoked_at.is_(None))),
        *control_checks).execution_options(autoflush=False)
    result = await db.scalar(query)
    return result if enabled() else None
