"""Explicit owner/recipient-bound test intents over the canonical WA outbox.

No provider calls. General messaging stays paused; only an immutable exact message
FK can authorize the worker exception. Raw challenges are deterministic, ephemeral
owner responses and never stored in command bodies/audits/transcripts.
"""
import hmac
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.models.whatsapp_self_service import WhatsAppConnectionTest, WhatsAppTestAuthorization
from app.schemas.whatsapp_self_service import TestView
from app.services.whatsapp_self_service import locked_configuration, now, problem, same_actor
from app.services.whatsapp_test_authority import current_provenance
from app.services.whatsapp_test_protocol import (
    FIXED_REPLY, FIXED_TEXT_VERSION, canonical_digest, challenge_command, command_digest,
)


def enabled():
    if not settings.V1_CHANNEL_TESTS_ENABLED:
        problem('channel_test_disabled','Authorized WhatsApp tests are not enabled',404)


async def own_test(db,authority,test_id,*,lock=False):
    query=select(WhatsAppConnectionTest).where(WhatsAppConnectionTest.id==test_id,
        WhatsAppConnectionTest.business_id==authority.binding.business_id)
    if lock: query=query.with_for_update()
    row=await db.scalar(query.execution_options(populate_existing=True))
    if row is None or not same_actor(row,authority.binding):
        raise HTTPException(404,'Test not found for this native session')
    return row


async def test_view(db,row):
    control=await db.scalar(select(ChannelConnectionState.version).where(
        ChannelConnectionState.business_id==row.business_id,ChannelConnectionState.channel=='whatsapp'))
    current=control==row.connection_version
    auth=await db.scalar(select(WhatsAppTestAuthorization).where(WhatsAppTestAuthorization.test_id==row.id))
    message=await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.id==auth.outbound_message_id,
        WhatsAppMessage.seller_id==row.business_id)) if auth else None
    contact=await db.scalar(select(WhatsAppContact.phone).where(WhatsAppContact.id==row.recipient_contact_id,
        WhatsAppContact.seller_id==row.business_id)) if row.recipient_contact_id else None
    state='recipient_verified' if row.inbound_message_id else 'awaiting_recipient'
    if message: state=message.status if message.status in ('queued','sending','accepted','sent','delivered','read','failed','unknown') else 'unknown'
    elif row.expires_at<=now() or row.cancelled_at is not None: state='expired'
    if not current: state='stale_connection'
    confirmed=bool(current and row.evidence_kind=='provider' and row.inbound_message_id and message and
        message.status in ('delivered','read') and message.provider_message_id)
    return TestView(contract_version='whatsapp-test.v1',business_id=row.business_id,test_id=row.id,
        connection_version=row.connection_version,status=state,recipient_hint='••'+contact[-4:] if contact else None,
        inbound_observed_at=row.received_at,message_id=message.id if message else None,
        provider_delivery_observed_at=message.updated_at if confirmed else None,delivery_confirmed=confirmed,
        is_current_generation=current,proof_source=('synthetic_fixture' if row.evidence_kind=='synthetic_fixture'
            else 'signed_provider_webhook' if row.inbound_message_id else 'not_recorded'),
        message=('Provider acceptance is not delivery. A failed or unknown test is never automatically resent.'
            if message else 'Ask the intended authorized recipient to send the private command, then explicitly review one fixed reply.'))


async def start_test(db,authority,payload):
    enabled()
    control,account=await locked_configuration(db,authority)
    digest=canonical_digest(settings.SECRET_KEY,'wa-test-start.v1',payload.model_dump(mode='json'))
    row=await db.scalar(select(WhatsAppConnectionTest).where(WhatsAppConnectionTest.business_id==authority.binding.business_id,
        WhatsAppConnectionTest.idempotency_key==payload.idempotency_key).with_for_update().execution_options(populate_existing=True))
    if row:
        if not same_actor(row,authority.binding) or not hmac.compare_digest(row.request_hash,digest):
            problem('channel_test_intent_conflict','This key belongs to a different test intent')
    else:
        if account is None or control.version!=payload.expected_connection_version:
            problem('channel_generation_stale','Review the current WhatsApp connection first')
        provenance=await current_provenance(db,account,control.version)
        timestamp=now().replace(microsecond=0)
        midnight=timestamp.replace(hour=0,minute=0,second=0)
        count=await db.scalar(select(func.count()).select_from(WhatsAppConnectionTest).where(
            WhatsAppConnectionTest.business_id==authority.binding.business_id,WhatsAppConnectionTest.issued_at>=midnight))
        if count>=3: problem('channel_test_rate_limit','The daily connection-test limit was reached',429)
        recent=await db.scalar(select(WhatsAppConnectionTest.id).where(WhatsAppConnectionTest.business_id==authority.binding.business_id,
            WhatsAppConnectionTest.issued_at>timestamp-timedelta(seconds=60)).limit(1))
        if recent: problem('channel_test_cooldown','Wait at least one minute before another test',429)
        active=await db.scalar(select(WhatsAppConnectionTest.id).outerjoin(WhatsAppTestAuthorization,
            WhatsAppTestAuthorization.test_id==WhatsAppConnectionTest.id).where(
            WhatsAppConnectionTest.business_id==authority.binding.business_id,WhatsAppConnectionTest.connection_version==control.version,
            WhatsAppConnectionTest.expires_at>timestamp,WhatsAppConnectionTest.cancelled_at.is_(None),
            WhatsAppTestAuthorization.test_id.is_(None)).limit(1))
        if active: problem('channel_test_already_active','Review or cancel the current recipient challenge')
        test_id=uuid4(); command=challenge_command(settings.SECRET_KEY,test_id,authority.binding)
        row=WhatsAppConnectionTest(id=test_id,business_id=authority.binding.business_id,
            actor_user_id=authority.binding.user_id,actor_session_id=authority.binding.session_id,
            actor_auth_version=authority.binding.auth_version,idempotency_key=payload.idempotency_key,
            request_hash=digest,connection_version=control.version,phone_number_id=account.phone_number_id,waba_id=account.waba_id,
            challenge_digest=command_digest(settings.SECRET_KEY,command),evidence_kind=provenance.evidence_kind,
            issued_at=timestamp,expires_at=timestamp+timedelta(minutes=10))
        db.add(row)
    await authority.finalize(db)
    view=await test_view(db,row)
    await authority.check(db)
    # Caller uses a repr-hidden response field; never log this tuple or persist
    # command into browser recovery storage. Exact start replay restores it.
    return view,challenge_command(settings.SECRET_KEY,row.id,authority.binding)


async def queue_fixed_reply(db,authority,test_id,payload):
    enabled(); await authority.check(db)
    # IDs are a scoped, unlocked hint. Acquire canonical Account→Contact before
    # Test/authorization; no subsequent Business/control row lock is allowed.
    hint=(await db.execute(select(WhatsAppConnectionTest.recipient_contact_id).where(
        WhatsAppConnectionTest.id==test_id,WhatsAppConnectionTest.business_id==authority.binding.business_id))).one_or_none()
    if hint is None or hint.recipient_contact_id is None:
        problem('test_recipient_required','A current signed inbound from the intended recipient is required')
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==authority.binding.business_id)
        .with_for_update().execution_options(populate_existing=True))
    contact=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.id==hint.recipient_contact_id,
        WhatsAppContact.seller_id==authority.binding.business_id).with_for_update().execution_options(populate_existing=True))
    row=await own_test(db,authority,test_id,lock=True)
    digest=canonical_digest(settings.SECRET_KEY,'wa-test-send.v1',payload.model_dump(mode='json'))
    existing=await db.scalar(select(WhatsAppTestAuthorization).where(WhatsAppTestAuthorization.business_id==row.business_id,
        WhatsAppTestAuthorization.idempotency_key==payload.idempotency_key))
    if existing:
        if existing.test_id!=row.id or not hmac.compare_digest(existing.request_hash,digest):
            problem('channel_test_intent_conflict','This action key belongs to another fixed reply')
        await authority.finalize(db)
        return await test_view(db,row)
    if await db.scalar(select(WhatsAppTestAuthorization.test_id).where(WhatsAppTestAuthorization.test_id==row.id)):
        problem('channel_test_already_queued','This test already has its one fixed reply; it cannot be resent')
    timestamp=now()
    if account is None or contact is None or row.cancelled_at is not None or row.expires_at<=timestamp:
        problem('channel_test_expired','The recipient challenge expired or was cancelled')
    if payload.expected_connection_version!=row.connection_version or payload.recipient_contact_id!=row.recipient_contact_id or payload.inbound_message_id!=row.inbound_message_id:
        problem('channel_test_intent_conflict','Review the exact verified recipient and current connection')
    if contact.opted_out or contact.last_inbound_at is None or not 0<=(timestamp-contact.last_inbound_at).total_seconds()<86400:
        problem('test_window_closed','The intended recipient must have an open reply window and must not be opted out')
    provenance=await current_provenance(db,account,row.connection_version,at=timestamp)
    expiry=min(timestamp+timedelta(seconds=120),row.inbound_provider_at+timedelta(hours=24))
    if provenance.token_expiry_kind=='at': expiry=min(expiry,provenance.token_expires_at)
    if expiry<=timestamp: problem('expired_authorization','The fixed reply authorization has expired')
    await authority.check(db)
    message=WhatsAppMessage(id=uuid4(),seller_id=row.business_id,contact_id=contact.id,
        phone_number_id=row.phone_number_id,idempotency_key='connection-test:'+str(row.id),direction='outbound',kind='text',
        text=FIXED_REPLY,payload={},status='queued',created_at=timestamp,updated_at=timestamp)
    db.add(message); await db.flush()
    db.add(WhatsAppTestAuthorization(test_id=row.id,business_id=row.business_id,
        actor_user_id=authority.binding.user_id,actor_session_id=authority.binding.session_id,actor_auth_version=authority.binding.auth_version,
        connection_version=row.connection_version,phone_number_id=row.phone_number_id,recipient_contact_id=contact.id,
        inbound_message_id=row.inbound_message_id,outbound_message_id=message.id,idempotency_key=payload.idempotency_key,
        request_hash=digest,fixed_text_version=FIXED_TEXT_VERSION,authorized_at=timestamp,expires_at=expiry))
    # No activity producer, new consent flags, provider send or alternate engine.
    await authority.finalize(db)
    result=await test_view(db,row)
    await authority.check(db)
    return result


async def cancel_test(db,authority,test_id):
    await authority.check(db)
    # Account first matches inbound/queue and cannot form Test→Account waits.
    await db.scalar(select(WhatsAppAccount.seller_id).where(WhatsAppAccount.seller_id==authority.binding.business_id).with_for_update())
    row=await own_test(db,authority,test_id,lock=True)
    if await db.scalar(select(WhatsAppTestAuthorization.test_id).where(WhatsAppTestAuthorization.test_id==row.id)):
        problem('channel_test_already_queued','A claimed reply cannot be cancelled or resent; inspect its result')
    if row.cancelled_at is None: row.cancelled_at=now()
    await authority.finalize(db)
    result=await test_view(db,row)
    await authority.check(db)
    return result
