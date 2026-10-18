"""Server-only fixed-test ingress/worker seams, with no provider I/O or commits.

Caller contract: ingress has verified the webhook signature and already locked
Account; queue locks Account→Contact→Test; worker holds Account→Contact→Message.
Worker reads immutable authorization only and never locks/updates the Test row.
"""
from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Business, Membership, User
from app.models.identity_auth import UserSession
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage
from app.models.whatsapp_self_service import (
    WhatsAppAuthorizationProvenance, WhatsAppConnectionTest, WhatsAppTestAuthorization,
)
from app.services.whatsapp_test_protocol import (
    FIXED_REPLY, REDACTED_COMMAND, SessionBinding, command_digest, reserved_command,
)


def now():
    return datetime.now(timezone.utc)


async def current_owner_session(db, binding: SessionBinding):
    valid=await db.scalar(select(UserSession.id).join(User,User.id==UserSession.user_id).where(
        UserSession.id==binding.session_id,UserSession.user_id==binding.user_id,
        UserSession.auth_version==binding.auth_version,User.auth_version==binding.auth_version,
        UserSession.revoked_at.is_(None),UserSession.expires_at>now(),User.is_active.is_(True),User.revoked_at.is_(None)
    ).execution_options(autoflush=False))
    if valid is None:
        raise HTTPException(401,'The authorizing native session ended')
    role=await db.scalar(select(Membership.role).join(Business,Business.id==Membership.business_id).join(
        Seller,Seller.id==Business.id).where(Membership.business_id==binding.business_id,
        Membership.user_id==binding.user_id,Membership.is_active.is_(True),Membership.revoked_at.is_(None),
        Business.is_active.is_(True),Seller.is_active.is_(True)).execution_options(autoflush=False))
    if role!='owner':
        raise HTTPException(403,'Current business owner authorization required')


async def current_provenance(db, account, version, *, at=None):
    at=at or now()
    row=(await db.execute(select(WhatsAppAuthorizationProvenance.phone_number_id,
        WhatsAppAuthorizationProvenance.waba_id,WhatsAppAuthorizationProvenance.token_expiry_kind,
        WhatsAppAuthorizationProvenance.token_expires_at,WhatsAppAuthorizationProvenance.evidence_kind
    ).join(ChannelConnectionState,(ChannelConnectionState.business_id==WhatsAppAuthorizationProvenance.business_id)
        &(ChannelConnectionState.version==WhatsAppAuthorizationProvenance.connection_version)
        &(ChannelConnectionState.channel=='whatsapp')).where(
        WhatsAppAuthorizationProvenance.business_id==account.seller_id,
        WhatsAppAuthorizationProvenance.connection_version==version).execution_options(autoflush=False))).one_or_none()
    if row is None or row.phone_number_id!=account.phone_number_id or row.waba_id!=account.waba_id or not account.access_token:
        raise HTTPException(409,'Current verified WhatsApp authorization is required')
    if row.token_expiry_kind!='permanent' and (row.token_expiry_kind!='at' or not row.token_expires_at or row.token_expires_at<=at):
        raise HTTPException(409,'WhatsApp authorization has expired or is unknown')
    return row


def reserved_packet(event):
    # Scan every string in this bounded signed packet, including captions and
    # interactive fallbacks. Even malformed namespace use cannot reach an LLM.
    pending=[event]
    while pending:
        item=pending.pop()
        if reserved_command(item):
            return True
        if type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return False


async def intercept_reserved(db, account, event, *, received_at=None):
    """True always suppresses ordinary ingress, independently of feature flags.

    Never logs/returns/persists the raw packet, challenge or provider payload.
    Invalid metadata is withheld without creating a transcript row.
    """
    if not reserved_packet(event):
        return False
    received_at=received_at or now()
    if type(event) is not dict:
        return True
    mid,phone,stamp=event.get('id'),event.get('from'),event.get('timestamp')
    if type(mid) is not str or not 1<=len(mid)<=255 or type(phone) is not str or not re.fullmatch(r'[1-9][0-9]{7,14}',phone) or type(stamp) is not str or not re.fullmatch(r'[0-9]{1,12}',stamp):
        return True
    try:
        provider_at=datetime.fromtimestamp(int(stamp),timezone.utc)
    except (ValueError,OSError,OverflowError):
        return True
    if provider_at.timestamp()>received_at.timestamp()+30:
        return True
    existing=await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==account.seller_id,
        WhatsAppMessage.provider_message_id==mid))
    if existing:
        return True
    contact=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.seller_id==account.seller_id,
        WhatsAppContact.phone==phone).with_for_update().execution_options(populate_existing=True))
    if contact is None:
        contact=WhatsAppContact(id=uuid4(),seller_id=account.seller_id,phone=phone,name='')
        db.add(contact); await db.flush()
    inbound=WhatsAppMessage(id=uuid4(),seller_id=account.seller_id,contact_id=contact.id,
        phone_number_id=account.phone_number_id,provider_message_id=mid,idempotency_key='in:'+mid,
        direction='inbound',kind='text',text=REDACTED_COMMAND,payload={},status='received',created_at=provider_at)
    db.add(inbound)
    # A test command opens the real inbound reply window but grants no template,
    # marketing, utility or automation consent and never reverses opt-out.
    if contact.last_inbound_at is None or provider_at>contact.last_inbound_at:
        contact.last_inbound_at=provider_at
    await db.flush()
    text=event.get('text')
    body=text.get('body') if type(text) is dict and event.get('type')=='text' else None
    digest=command_digest(settings.SECRET_KEY,body)
    if not settings.V1_CHANNEL_TESTS_ENABLED or digest is None:
        return True
    test=await db.scalar(select(WhatsAppConnectionTest).where(WhatsAppConnectionTest.business_id==account.seller_id,
        WhatsAppConnectionTest.challenge_digest==digest).with_for_update().execution_options(populate_existing=True))
    if test is None or test.cancelled_at is not None or test.inbound_message_id is not None or test.phone_number_id!=account.phone_number_id or test.waba_id!=account.waba_id:
        return True
    if not (test.issued_at<=provider_at<=test.expires_at and provider_at.timestamp()-30<=received_at.timestamp()<=test.expires_at.timestamp()+30):
        return True
    binding=SessionBinding(test.business_id,test.actor_user_id,test.actor_session_id,test.actor_auth_version)
    try:
        await current_owner_session(db,binding)
        await current_provenance(db,account,test.connection_version,at=received_at)
    except HTTPException:
        return True
    test.recipient_contact_id,test.inbound_message_id=contact.id,inbound.id
    test.inbound_provider_at,test.received_at=provider_at,received_at
    await db.flush()
    return True


async def exact_test_authority(db, account, contact, message, *, at=None):
    """None means an ordinary message; a bound but invalid test raises/denies.

    This must be checked before the worker's account.enabled guard. It permits
    only this one fixed text despite paused automation, never a disconnected
    account, expired grant, changed generation/session, opt-out or closed window.
    """
    auth=await db.scalar(select(WhatsAppTestAuthorization).where(
        WhatsAppTestAuthorization.outbound_message_id==message.id).execution_options(autoflush=False))
    if auth is None:
        return None
    at=at or now()
    if not settings.V1_CHANNEL_TESTS_ENABLED or auth.expires_at<=at or auth.authorized_at>at:
        raise HTTPException(409,'Connection-test authorization is unavailable or expired')
    if (auth.business_id!=account.seller_id or message.seller_id!=account.seller_id
        or auth.phone_number_id!=account.phone_number_id or message.phone_number_id!=account.phone_number_id
        or auth.recipient_contact_id!=contact.id or message.contact_id!=contact.id
        or message.direction!='outbound' or message.kind!='text' or message.text!=FIXED_REPLY or message.payload!={}
        or contact.opted_out or not contact.last_inbound_at
        or not 0<=(at-contact.last_inbound_at).total_seconds()<86400):
        raise HTTPException(409,'The exact recipient, reply window or account changed')
    await current_owner_session(db,SessionBinding(auth.business_id,auth.actor_user_id,auth.actor_session_id,auth.actor_auth_version))
    await current_provenance(db,account,auth.connection_version,at=at)
    return auth
