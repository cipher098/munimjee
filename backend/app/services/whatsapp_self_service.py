"""Owner-bound native WA setup; claimed external effects are never blindly retried.

Every entry receives a server-created Authority. Internal commits are explicit
claim boundaries only; final staged credentials/audit require a fresh exact sid
and owner check. Provider codes/PINs/tokens never become durable command bodies.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import func, select

from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.whatsapp import WhatsAppAccount
from app.models.whatsapp_self_service import WhatsAppSignupAttempt, WhatsAppSignupChoice
from app.schemas.whatsapp_self_service import SDKConfiguration, SignupStartView, SignupView
from app.services.channel_credentials import decrypt, encrypt
from app.services.channel_operator import lock_tenant_rows
from app.services.whatsapp_signup_provider import SignupProvider
from app.services.whatsapp_test_authority import current_owner_session, owner_session_statement
from app.services.whatsapp_test_protocol import (
    ProtocolError, SessionBinding, bound_nonce, canonical_digest, embedded_configuration,
)


def now():
    return datetime.now(timezone.utc)


def problem(code, message, status=409):
    raise HTTPException(status,{'code':code,'message':message})


@dataclass(frozen=True)
class Authority:
    binding: SessionBinding
    check_request: Callable[[],Awaitable[None]]

    async def check(self,db):
        await self.check_request()
        await current_owner_session(db,self.binding)

    async def finalize(self,db):
        await db.flush()
        await self.check(db)


async def locked_configuration(db,authority):
    await authority.check(db)
    await lock_tenant_rows(db,authority.binding.business_id)
    control=await db.scalar(select(ChannelConnectionState).where(
        ChannelConnectionState.business_id==authority.binding.business_id,
        ChannelConnectionState.channel=='whatsapp').with_for_update().execution_options(populate_existing=True))
    if control is None:
        control=ChannelConnectionState(business_id=authority.binding.business_id,channel='whatsapp',version=0,
            automation_enabled=False,check_status='not_checked')
        db.add(control); await db.flush()
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==authority.binding.business_id)
        .with_for_update().execution_options(populate_existing=True))
    await authority.check(db)
    return control,account


def same_actor(row,binding):
    return (row.business_id,row.actor_user_id,row.actor_session_id,row.actor_auth_version)==(
        binding.business_id,binding.user_id,binding.session_id,binding.auth_version)


async def owned_attempt(db,authority,attempt_id,*,lock=False):
    query=select(WhatsAppSignupAttempt).where(WhatsAppSignupAttempt.id==attempt_id,
        WhatsAppSignupAttempt.business_id==authority.binding.business_id)
    if lock: query=query.with_for_update()
    row=await db.scalar(query.execution_options(populate_existing=True))
    if row is None or not same_actor(row,authority.binding):
        raise HTTPException(404,'Signup attempt not found for this native session')
    return row


async def signup_view(db,row):
    choices=(await db.scalars(select(WhatsAppSignupChoice).where(WhatsAppSignupChoice.attempt_id==row.id,
        WhatsAppSignupChoice.business_id==row.business_id).order_by(WhatsAppSignupChoice.id).limit(100))).all()
    state=row.state
    if state=='pending' and row.expires_at<=now(): state='expired'
    return SignupView(contract_version='whatsapp-signup.v1',business_id=row.business_id,attempt_id=row.id,
        status=state,connection_version=row.connection_version,expires_at=row.expires_at,
        choices=tuple({'choice_id':c.id,'display_name':c.display_name,'phone_hint':'••'+c.phone_number_id[-6:]} for c in choices),
        setup={'subscription':row.subscription_state,'registration':row.registration_state,'billing':'external_action_required'},
        provider_approval='not_evaluated')


def start_state(row,binding):
    return jwt.encode({'purpose':'wa-native-signup.v1','attempt':str(row.id),**dict(zip(
        ('business','user','sid','auth_version'),binding.values())), 'generation':row.connection_version,
        'nonce_digest':row.nonce_digest,'exp':row.expires_at},settings.SECRET_KEY,algorithm=settings.JWT_ALGORITHM)


async def start_signup(db,authority,payload,*,provider=None):
    sdk=embedded_configuration(settings)
    control,_=await locked_configuration(db,authority)
    digest=canonical_digest(settings.SECRET_KEY,'wa-start.v1',payload.model_dump(mode='json'))
    row=await db.scalar(select(WhatsAppSignupAttempt).where(WhatsAppSignupAttempt.business_id==authority.binding.business_id,
        WhatsAppSignupAttempt.idempotency_key==payload.idempotency_key).with_for_update().execution_options(populate_existing=True))
    if row:
        if not same_actor(row,authority.binding) or not hmac.compare_digest(row.request_hash,digest):
            problem('signup_intent_conflict','This action key already belongs to another signup intent')
    else:
        if payload.expected_connection_version!=control.version:
            problem('channel_generation_stale','The connection changed; review its current state')
        timestamp=now()
        count=await db.scalar(select(func.count()).select_from(WhatsAppSignupAttempt).where(
            WhatsAppSignupAttempt.business_id==authority.binding.business_id,
            WhatsAppSignupAttempt.actor_user_id==authority.binding.user_id,
            WhatsAppSignupAttempt.created_at>timestamp-timedelta(hours=1)))
        if count>=5: problem('signup_rate_limit','Wait before starting another signup',429)
        active=await db.scalar(select(WhatsAppSignupAttempt.id).where(
            WhatsAppSignupAttempt.business_id==authority.binding.business_id,
            WhatsAppSignupAttempt.actor_session_id==authority.binding.session_id,
            WhatsAppSignupAttempt.state.in_(('pending','exchanging','awaiting_assets','awaiting_selection','setting_up')),
            WhatsAppSignupAttempt.expires_at>timestamp).limit(1))
        if active: problem('signup_already_active','Review the existing signup before starting another')
        attempt_id=uuid4(); nonce=bound_nonce(settings.SECRET_KEY,attempt_id,authority.binding)
        evidence_kind=(provider or SignupProvider(settings)).evidence_kind
        if evidence_kind not in ('provider','synthetic_fixture'):
            raise ProtocolError('provider_response_invalid')
        row=WhatsAppSignupAttempt(id=attempt_id,business_id=authority.binding.business_id,
            actor_user_id=authority.binding.user_id,actor_session_id=authority.binding.session_id,
            actor_auth_version=authority.binding.auth_version,idempotency_key=payload.idempotency_key,
            request_hash=digest,connection_version=control.version,nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(),
            state='pending',created_at=timestamp,expires_at=timestamp+timedelta(minutes=10),
            token_delete_after=timestamp+timedelta(minutes=15),token_expiry_kind='unknown',
            subscription_state='not_started',registration_state='not_started',evidence_kind=evidence_kind,updated_at=timestamp)
        db.add(row)
    await authority.finalize(db)
    result=SignupStartView(contract_version='whatsapp-signup-start.v1',attempt=await signup_view(db,row),
        signed_state=start_state(row,authority.binding),sdk=SDKConfiguration(**sdk))
    await authority.check(db)
    return result,bound_nonce(settings.SECRET_KEY,row.id,authority.binding)


def verify_browser(row,binding,payload,nonce):
    try:
        claims=jwt.decode(payload.signed_state,settings.SECRET_KEY,algorithms=[settings.JWT_ALGORITHM],options={'require_exp':True})
        expected={'purpose':'wa-native-signup.v1','attempt':str(row.id),'business':str(binding.business_id),
            'user':str(binding.user_id),'sid':str(binding.session_id),'auth_version':binding.auth_version,
            'generation':row.connection_version,'nonce_digest':row.nonce_digest}
        if any(claims.get(k)!=v for k,v in expected.items()) or type(claims.get('auth_version')) is not int or type(claims.get('generation')) is not int:
            raise ValueError()
        if type(nonce) is not str or not hmac.compare_digest(hashlib.sha256(nonce.encode()).hexdigest(),row.nonce_digest):
            raise ValueError()
    except (JWTError,ValueError,TypeError,AttributeError):
        problem('signup_browser_mismatch','Restart from the original signed-in browser',403)


async def effect_unknown(db,attempt_id,*,stage):
    # Called only after a committed claim. Roll back staged credentials first;
    # retain minimal unknown effect even when native authority was revoked. No
    # reverse Business/Account wait and no provisional token/PIN attachment.
    await db.rollback()
    row=await db.scalar(select(WhatsAppSignupAttempt).where(WhatsAppSignupAttempt.id==attempt_id).with_for_update())
    if row:
        if stage=='exchange' and row.state=='exchanging': row.state='exchange_unknown'
        elif stage in ('subscription','registration') and row.state=='setting_up':
            row.state='setup_unknown'
            attribute=stage+'_state'
            if getattr(row,attribute)=='requesting': setattr(row,attribute,'unknown')
        row.provisional_token_ciphertext=None
        row.updated_at=now()
        await db.commit()


async def exchange_signup(db,authority,attempt_id,payload,nonce,*,provider=None):
    embedded_configuration(settings)
    control,_=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if payload.idempotency_key!=row.idempotency_key:
        problem('signup_intent_conflict','Use the original signup action key')
    verify_browser(row,authority.binding,payload,nonce)
    if row.state!='pending':
        await authority.finalize(db)
        return await signup_view(db,row)
    if row.expires_at<=now() or row.connection_version!=control.version:
        problem('channel_generation_stale','The signup expired or connection changed')
    client=provider or SignupProvider(settings)
    row.state='exchanging'; row.exchange_consumed_at=now(); row.updated_at=now()
    await authority.finalize(db); await db.commit()
    try:
        await post_claim_authority(db,authority,attempt_id,stage='exchange')
        embedded_configuration(settings)
        verified=await client.exchange(payload.code,now=now())
        embedded_configuration(settings)
        control,_=await locked_configuration(db,authority)
        row=await owned_attempt(db,authority,attempt_id,lock=True)
        if row.state!='exchanging' or row.connection_version!=control.version or row.expires_at<=now():
            raise HTTPException(409,'The signup changed or expired during provider authorization')
        if client.evidence_kind not in ('provider','synthetic_fixture'):
            raise ProtocolError('provider_response_invalid')
        # Evidence classification was fixed before exchange. Synthetic transport
        # must be installed through the server-only test dependency at start.
        if row.evidence_kind!=client.evidence_kind:
            raise ProtocolError('provider_response_invalid')
        row.provisional_token_ciphertext=encrypt(verified.token)
        row.token_expiry_kind='at'; row.token_expires_at=verified.expires_at
        row.verified_app_id=verified.app_id; row.state='awaiting_assets'; row.updated_at=now()
        await authority.finalize(db)
        result=await signup_view(db,row)
        await authority.check(db)
        return result
    except (Exception,asyncio.CancelledError) as error:
        await asyncio.shield(effect_unknown(db,attempt_id,stage='exchange'))
        if isinstance(error,HTTPException) and error.status_code in (401,403):
            raise error from None
        raise HTTPException(409,{'code':'signup_exchange_unknown','message':'Authorization could not be confirmed. It will not be retried automatically.'}) from None


async def discover_assets(db,authority,attempt_id,payload,*,provider=None):
    embedded_configuration(settings)
    control,_=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if payload.idempotency_key!=row.idempotency_key:
        problem('signup_intent_conflict','Use the original signup action key')
    if row.state=='awaiting_selection':
        selected=await db.scalar(select(WhatsAppSignupChoice.id).where(WhatsAppSignupChoice.attempt_id==row.id,
            WhatsAppSignupChoice.waba_id==payload.waba_id,WhatsAppSignupChoice.phone_number_id==payload.phone_number_id))
        if selected is None: problem('signup_intent_conflict','The reviewed signup assets already differ')
        await authority.finalize(db)
        return await signup_view(db,row)
    if row.state!='awaiting_assets' or row.expires_at<=now() or row.connection_version!=control.version or not row.provisional_token_ciphertext:
        problem('signup_assets_unavailable','Current authorization and account review are required')
    token=decrypt(row.provisional_token_ciphertext)
    await authority.finalize(db); await db.commit()
    client=provider or SignupProvider(settings)
    try:
        verified=await client.inspect(token,now=now())
        choices=await client.choices(verified,payload.waba_id)
    except Exception:
        problem('signup_assets_unverified','Account membership could not be verified. No account was attached.')
    control,_=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if row.state!='awaiting_assets' or row.connection_version!=control.version or row.expires_at<=now() or not row.provisional_token_ciphertext:
        problem('channel_generation_stale','The signup changed during account discovery')
    if verified.app_id!=row.verified_app_id or verified.expires_at!=row.token_expires_at or client.evidence_kind!=row.evidence_kind:
        problem('signup_assets_unverified','Provider authorization changed during account discovery')
    if not choices or not any(c.phone_number_id==payload.phone_number_id for c in choices):
        problem('signup_assets_unverified','The signup phone is not a verified member of this account')
    timestamp=now()
    for choice in choices:
        choice_id=uuid4()
        fingerprint=canonical_digest(settings.SECRET_KEY,'wa-choice.v1',[str(row.id),str(choice_id),choice.waba_id,
            choice.phone_number_id,choice.display_name,choice.display_phone_number,choice.provider_registration_status,timestamp.isoformat()])
        db.add(WhatsAppSignupChoice(id=choice_id,attempt_id=row.id,business_id=row.business_id,
            waba_id=choice.waba_id,phone_number_id=choice.phone_number_id,display_name=choice.display_name,
            display_phone_number=choice.display_phone_number,fingerprint=fingerprint,verified_at=timestamp,
            provider_registration_status=choice.provider_registration_status))
    # Choice insertion guard observes awaiting_assets before the state advance.
    await db.flush(); row.state='awaiting_selection'; row.updated_at=timestamp
    await authority.finalize(db)
    result=await signup_view(db,row)
    await authority.check(db)
    return result


async def select_account(db,authority,attempt_id,payload,*,provider=None):
    from sqlalchemy.exc import IntegrityError
    embedded_configuration(settings)
    client=provider or SignupProvider(settings)
    control,account=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    digest=canonical_digest(settings.SECRET_KEY,'wa-selection.v1',payload.model_dump(mode='json'))
    if row.selected_key is not None:
        if row.selected_key!=payload.idempotency_key or not hmac.compare_digest(row.selected_hash,digest):
            problem('signup_intent_conflict','This signup already has a different selection command')
        await authority.finalize(db)
        return await signup_view(db,row)
    if row.state!='awaiting_selection' or row.expires_at<=now() or row.connection_version!=control.version or payload.expected_connection_version!=control.version:
        problem('channel_generation_stale','Review the current connection before account selection')
    choice=await db.scalar(select(WhatsAppSignupChoice).where(WhatsAppSignupChoice.id==payload.choice_id,
        WhatsAppSignupChoice.attempt_id==row.id,WhatsAppSignupChoice.business_id==row.business_id))
    if choice is None or choice.waba_id!=payload.waba_id or choice.phone_number_id!=payload.phone_number_id or not hmac.compare_digest(choice.fingerprint,payload.expected_choice_fingerprint):
        problem('signup_choice_stale','Choose the exact server-verified account again')
    if account is not None and account.phone_number_id!=choice.phone_number_id:
        problem('signup_phone_change_unsupported','A different phone cannot replace this existing inbox')
    if not payload.request_registration:
        problem('registration_required','This supported flow requires explicit Cloud API registration; existing registration reconciliation is not verified')
    if not row.provisional_token_ciphertext or row.token_expiry_kind!='at' or not row.token_expires_at or row.token_expires_at<=now():
        problem('expired_authorization','Restart consent because current token expiry could not be established')
    token=decrypt(row.provisional_token_ciphertext)
    await authority.finalize(db); await db.commit()
    try:
        verified=await client.inspect(token,now=now())
        current_choices=await client.choices(verified,payload.waba_id)
        if not any(c.phone_number_id==payload.phone_number_id for c in current_choices):
            raise ProtocolError('provider_account_unverified')
    except Exception:
        problem('signup_choice_unverified','Current provider account membership could not be verified')
    control,account=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if row.selected_key is not None:
        if row.selected_key!=payload.idempotency_key or not hmac.compare_digest(row.selected_hash,digest):
            problem('signup_intent_conflict','A different account selection was already recorded')
        await authority.finalize(db)
        return await signup_view(db,row)
    if row.state!='awaiting_selection' or row.connection_version!=control.version or row.expires_at<=now() or payload.expected_connection_version!=control.version:
        problem('channel_generation_stale','The connection changed during account review')
    if verified.app_id!=row.verified_app_id or verified.expires_at!=row.token_expires_at or client.evidence_kind!=row.evidence_kind:
        problem('signup_choice_unverified','Provider authorization changed during account review')
    if account is not None and account.phone_number_id!=payload.phone_number_id:
        problem('signup_phone_change_unsupported','A different phone cannot replace this existing inbox')
    row.selected_choice_id=payload.choice_id; row.selected_phone_number_id=payload.phone_number_id
    row.selected_key=payload.idempotency_key; row.selected_hash=digest
    row.state='setting_up'; row.updated_at=now()
    try:
        # This may wait for another business's transient phone claim. No
        # provider step has been dispatched by this command yet.
        await db.flush()
    except IntegrityError:
        await db.rollback(); await authority.check(db)
        problem('signup_phone_claimed','This phone already has setup awaiting a confirmed result')
    foreign=await db.scalar(select(WhatsAppAccount.seller_id).where(
        WhatsAppAccount.phone_number_id==payload.phone_number_id,
        WhatsAppAccount.seller_id!=authority.binding.business_id).execution_options(autoflush=False))
    if foreign is not None:
        problem('signup_phone_unavailable','This phone cannot be attached to this business')
    # Fresh checks AFTER the unique-index wait, BEFORE committing its claim.
    await authority.finalize(db)
    current_version=await db.scalar(select(ChannelConnectionState.version).where(
        ChannelConnectionState.business_id==authority.binding.business_id,ChannelConnectionState.channel=='whatsapp'))
    if current_version!=payload.expected_connection_version:
        problem('channel_generation_stale','The connection changed before setup was claimed')
    await db.commit()
    await provider_step(db,authority,attempt_id,payload,client,stage='subscription',token=token)
    await provider_step(db,authority,attempt_id,payload,client,stage='registration',token=token)
    try:
        return await attach_account(db,authority,attempt_id,payload,token=token)
    except (Exception,asyncio.CancelledError) as error:
        await asyncio.shield(effect_unknown(db,attempt_id,stage='registration'))
        if isinstance(error,HTTPException) and error.status_code in (401,403): raise error from None
        problem('signup_setup_unknown','Provider setup needs review. No credentials were attached and no step will be repeated automatically.')


async def provider_step(db,authority,attempt_id,payload,client,*,stage,token):
    attribute=stage+'_state'
    try:
        embedded_configuration(settings)
        control,_=await locked_configuration(db,authority)
        row=await owned_attempt(db,authority,attempt_id,lock=True)
        if row.state!='setting_up' or row.selected_key!=payload.idempotency_key or row.connection_version!=control.version or row.expires_at<=now() or not row.provisional_token_ciphertext or not row.token_expires_at or row.token_expires_at<=now():
            raise HTTPException(409,'The claimed setup is no longer current')
        state=getattr(row,attribute)
        if state=='confirmed': return
        if state!='not_started':
            raise HTTPException(409,'A provider step is already claimed or unknown')
        setattr(row,attribute,'requesting'); row.updated_at=now()
        await authority.finalize(db); await db.commit()
        await post_claim_authority(db,authority,attempt_id,stage=stage)
        embedded_configuration(settings)
        if stage=='subscription': await client.subscribe(token,payload.waba_id)
        else: await client.register(token,payload.phone_number_id,payload.registration_pin)
        embedded_configuration(settings)
        control,_=await locked_configuration(db,authority)
        row=await owned_attempt(db,authority,attempt_id,lock=True)
        if row.state!='setting_up' or getattr(row,attribute)!='requesting' or row.connection_version!=control.version or row.expires_at<=now():
            raise HTTPException(409,'The connection changed during provider setup')
        setattr(row,attribute,'confirmed'); row.updated_at=now()
        await authority.finalize(db); await db.commit()
    except (Exception,asyncio.CancelledError) as error:
        # Even a local failure after claim must not free its cross-tenant phone
        # reservation or imply that an external effect did not happen.
        await asyncio.shield(effect_unknown(db,attempt_id,stage=stage))
        if isinstance(error,HTTPException) and error.status_code in (401,403): raise error from None
        problem('signup_setup_unknown','The provider result is uncertain. Review it in Meta; this step will not be retried automatically.')


async def attach_account(db,authority,attempt_id,payload,*,token):
    from app.models.whatsapp_self_service import WhatsAppAuthorizationProvenance
    embedded_configuration(settings)
    control,account=await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if row.state!='setting_up' or row.selected_key!=payload.idempotency_key or row.connection_version!=control.version or row.expires_at<=now() or row.subscription_state!='confirmed' or row.registration_state!='confirmed' or not row.token_expires_at or row.token_expires_at<=now():
        problem('signup_attachment_unavailable','Current confirmed setup is required before saving the account')
    choice=await db.scalar(select(WhatsAppSignupChoice).where(WhatsAppSignupChoice.id==row.selected_choice_id,
        WhatsAppSignupChoice.attempt_id==row.id,WhatsAppSignupChoice.business_id==row.business_id))
    if not choice or choice.phone_number_id!=payload.phone_number_id or choice.waba_id!=payload.waba_id:
        problem('signup_choice_stale','The selected account no longer matches this setup')
    foreign=await db.scalar(select(WhatsAppAccount.seller_id).where(WhatsAppAccount.phone_number_id==choice.phone_number_id,
        WhatsAppAccount.seller_id!=row.business_id))
    if foreign is not None or account is not None and account.phone_number_id!=choice.phone_number_id:
        problem('signup_phone_unavailable','The selected phone cannot be attached to this inbox')
    if account is None:
        account=WhatsAppAccount(seller_id=row.business_id,phone_number_id=choice.phone_number_id,waba_id=choice.waba_id,
            display_phone_number=choice.display_phone_number,access_token=encrypt(token),enabled=False,automation_enabled=False)
        db.add(account)
    else:
        account.waba_id=choice.waba_id; account.display_phone_number=choice.display_phone_number
        account.access_token=encrypt(token); account.enabled=False; account.automation_enabled=False
    timestamp=now(); control.version+=1; control.provider_account_id=choice.phone_number_id
    control.automation_enabled=False; control.check_status='verified'; control.checked_at=timestamp; control.error_code=None
    # Provenance insertion observes the exact paused incumbent account/current
    # generation while Attempt is still setting_up, all in the same txn.
    await db.flush()
    db.add(WhatsAppAuthorizationProvenance(business_id=row.business_id,connection_version=control.version,
        attempt_id=row.id,actor_user_id=row.actor_user_id,actor_session_id=row.actor_session_id,
        actor_auth_version=row.actor_auth_version,phone_number_id=choice.phone_number_id,waba_id=choice.waba_id,
        verified_app_id=row.verified_app_id,credential_fingerprint=hashlib.sha256(account.access_token.encode()).hexdigest(),grants=['whatsapp_business_management','whatsapp_business_messaging'],
        token_expiry_kind=row.token_expiry_kind,token_expires_at=row.token_expires_at,verified_at=timestamp,evidence_kind=row.evidence_kind))
    await db.flush()
    row.state='attached'; row.provisional_token_ciphertext=None; row.updated_at=timestamp
    await authority.finalize(db)
    result=await signup_view(db,row)
    await authority.check(db)
    return result


async def cleanup_provisional(db,*,at=None,limit=100):
    """Ungated secret expiry. Never releases a provider claim or locks Business.

    Scheduler/deployment installation is an integrator-owned operational gate;
    this helper's existence does not assert that physical deletion is deployed.
    """
    timestamp=at or now()
    rows=(await db.scalars(select(WhatsAppSignupAttempt).where(
        WhatsAppSignupAttempt.provisional_token_ciphertext.is_not(None),
        WhatsAppSignupAttempt.token_delete_after<=timestamp).order_by(WhatsAppSignupAttempt.token_delete_after)
        .limit(max(1,min(int(limit),500))).with_for_update(skip_locked=True))).all()
    for row in rows:
        row.provisional_token_ciphertext=None
        if row.state in ('pending','awaiting_assets','awaiting_selection'): row.state='expired'
        elif row.state=='setting_up':
            row.state='setup_unknown'
            if row.subscription_state=='requesting': row.subscription_state='unknown'
            if row.registration_state=='requesting': row.registration_state='unknown'
        elif row.state=='exchanging': row.state='exchange_unknown'
        row.updated_at=timestamp
    await db.flush()
    return len(rows)


async def post_claim_authority(db,authority,attempt_id,*,stage):
    """Fresh, nonlocking authority after claim commit and before provider I/O.

    A durable consumed claim does not authorize a new operation after a session,
    owner, generation, configuration or expiry change during commit. Unknown
    effect history is retained even when this last boundary withholds dispatch.
    """
    from app.models.identity import Membership
    await authority.check(db)
    attempt=WhatsAppSignupAttempt
    query=owner_session_statement(authority.binding).join(attempt,
        (attempt.business_id==Membership.business_id)&(attempt.actor_user_id==Membership.user_id)).join(
        ChannelConnectionState,(ChannelConnectionState.business_id==attempt.business_id)&(ChannelConnectionState.channel=='whatsapp')).where(
        attempt.id==attempt_id,attempt.actor_session_id==authority.binding.session_id,
        attempt.actor_auth_version==authority.binding.auth_version,attempt.expires_at>func.clock_timestamp(),
        ChannelConnectionState.version==attempt.connection_version)
    if stage=='exchange':
        query=query.where(attempt.state=='exchanging',attempt.exchange_consumed_at.is_not(None))
    else:
        query=query.where(attempt.state=='setting_up',getattr(attempt,stage+'_state')=='requesting',
            attempt.provisional_token_ciphertext.is_not(None),attempt.token_expiry_kind=='at',
            attempt.token_expires_at>func.clock_timestamp(),~select(WhatsAppAccount.seller_id).where(
                WhatsAppAccount.phone_number_id==attempt.selected_phone_number_id,
                WhatsAppAccount.seller_id!=attempt.business_id).exists())
    if await db.scalar(query.execution_options(autoflush=False)) is None:
        problem('signup_authority_changed','Current native owner, connection and setup claim are required before provider dispatch')


async def cancel_signup(db,authority,attempt_id,payload):
    await locked_configuration(db,authority)
    row=await owned_attempt(db,authority,attempt_id,lock=True)
    if payload.idempotency_key!=row.idempotency_key:
        problem('signup_intent_conflict','Use the original signup action key')
    if row.state in ('cancelled','expired'):
        await authority.finalize(db)
        return await signup_view(db,row)
    if row.state not in ('pending','awaiting_assets','awaiting_selection'):
        problem('signup_effect_review_required','A provider-claimed or uncertain setup cannot be cancelled here. Review it without repeating its steps.')
    row.state='cancelled'; row.provisional_token_ciphertext=None; row.updated_at=now()
    await authority.finalize(db)
    result=await signup_view(db,row)
    await authority.check(db)
    return result
