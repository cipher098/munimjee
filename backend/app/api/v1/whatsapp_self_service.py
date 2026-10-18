"""Native owner WhatsApp consent/account selection and fixed test operations.

Provider secrets/codes/PINs use bounded manual JSON parsing, never FastAPI's
input-echoing validation. No customer JWT, legacy seller token or support grant
can impersonate the exact authorizing native user session.
"""
import asyncio
import json
from pathlib import Path
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.models.channel_operator import ChannelConnectionState
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact
from app.models.whatsapp_self_service import WhatsAppAuthorizationProvenance, WhatsAppConnectionTest, WhatsAppSignupChoice, WhatsAppTestAuthorization
from app.schemas.whatsapp_self_service import (
    Command, ExchangeSignup, InvalidWhatsAppCommand, ReadinessView, RecipientReview, ReviewedChoicesView,
    SelectSignup, SendTest, SignupAssets, StartSignup, StartTest, TestChallengeView, SignupCommandView, TestCommandView, parse_command,
)
from app.services.auth_sessions import native_session, request_auth_token
from app.services.identity import require_business_access
from app.services import whatsapp_connection_tests as tests, whatsapp_self_service as service
from app.services.whatsapp_signup_provider import SignupProvider
from app.services.whatsapp_test_authority import current_owner_session, current_provenance
from app.services.whatsapp_test_protocol import ProtocolError, SessionBinding, embedded_configuration

PRIVATE={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'}
STATIC=Path(__file__).resolve().parents[3]/'static'
BASE='/api/v1/businesses/{business_id}/channels/whatsapp'
COOKIE='wa_signup_nonce'


def private(response:Response): response.headers.update(PRIVATE)
router=APIRouter(tags=['v1-whatsapp-self-service'],dependencies=[Depends(private)])


def provider_dependency():
    # Tests may replace this server dependency. No body/header selects a fake
    # provider or asserts evidence classification.
    return SignupProvider(settings)


async def read_actor(request,db,business_id):
    if not settings.V1_AUTH_ENABLED: raise HTTPException(404,'Native sign-in is unavailable')
    actor=await current_actor(request,db)
    if actor.auth_method!='v1_user': raise HTTPException(401,'Sign in with your own V1 account')
    await require_business_access(db,actor,business_id,'inbox.read')
    return actor


async def read_final(request,db,business_id,actor):
    current=await read_actor(request,db,business_id)
    if current!=actor: raise HTTPException(401,'The native session changed')
    return await require_business_access(db,current,business_id,'inbox.read')


async def authority(request,db,business_id,*,mutation=True,bind_app=False):
    actor=await (require_v1_mutation(request,db) if mutation else read_actor(request,db,business_id))
    if actor.auth_method!='v1_user': raise HTTPException(401,'Sign in with your own V1 account')
    context=await native_session(db,request_auth_token(request))
    binding=SessionBinding(business_id,actor.user_id,context.session.id,context.session.auth_version)
    async def check():
        current=await (require_v1_mutation(request,db) if mutation else read_actor(request,db,business_id))
        active=await native_session(db,request_auth_token(request))
        if current!=actor or active.session.id!=binding.session_id or active.session.auth_version!=binding.auth_version:
            raise HTTPException(401,'The authorizing native session changed')
    result=service.Authority(binding,check,settings.WHATSAPP_EMBEDDED_APP_ID if bind_app else None)
    await result.check(db)
    return result


async def command(request,model):
    async def bounded():
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>16384: raise ValueError()
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result: raise ValueError()
                result[k]=v
            return result
        return json.loads(data.decode('utf-8'),object_pairs_hook=unique)
    try:
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json': raise ValueError()
        document=await asyncio.wait_for(bounded(),5)
        return parse_command(model,document)
    except (ValueError,TypeError,UnicodeError,RecursionError,asyncio.TimeoutError,InvalidWhatsAppCommand):
        raise HTTPException(422,'Review the connection details and try again') from None


def protocol_error(error):
    raise HTTPException(409,{'code':str(error),'message':'Provider configuration or authorization is not ready. No live readiness is implied.'}) from None


@router.get('/v1/businesses/{business_id}/channels/whatsapp/setup',include_in_schema=False)
async def page(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
    actor=await read_actor(request,db,business_id)
    await read_final(request,db,business_id,actor)
    return FileResponse(STATIC/'whatsapp_self_service.html',headers={**PRIVATE,
        'Content-Security-Policy':"default-src 'self'; script-src 'self' https://connect.facebook.net; frame-src https://www.facebook.com; connect-src 'self' https://www.facebook.com; img-src 'self' data:; style-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"})


@router.get(BASE+'/self-service')
async def readiness(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
    actor=await read_actor(request,db,business_id)
    control=await db.scalar(select(ChannelConnectionState.version).where(
        ChannelConnectionState.business_id==business_id,ChannelConnectionState.channel=='whatsapp'))
    version=control if control is not None else 0
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==business_id))
    blockers=[]; available=False
    try: embedded_configuration(settings); available=True
    except ProtocolError as error:
        blockers.append('configuration_mismatch' if str(error)=='configuration_mismatch' else 'signup_disabled' if not settings.V1_WHATSAPP_ONBOARDING_ENABLED else 'operator_configuration_missing')
    if not settings.V1_CHANNEL_TESTS_ENABLED: blockers.append('test_disabled')
    status='not_connected'
    if account and account.access_token:
        try:
            await current_provenance(db,account,version)
            status='local_access_verified' if account.enabled and account.automation_enabled else 'paused'
        except HTTPException as error:
            expired=error.detail=='WhatsApp authorization has expired or is unknown'
            status='needs_reconnect' if expired else 'setup_required'
            blockers.append('expired_authorization' if expired else 'verification_unknown')
        blockers.append('billing_external')
    else: blockers.append('account_not_selected')
    access=await read_final(request,db,business_id,actor)
    current_test=None
    if access.role=='owner':
        row=await db.scalar(select(WhatsAppConnectionTest).where(WhatsAppConnectionTest.business_id==business_id,
            WhatsAppConnectionTest.connection_version==version).order_by(WhatsAppConnectionTest.issued_at.desc()).limit(1))
        if row: current_test=await tests.test_view(db,row)
    access=await read_final(request,db,business_id,actor)
    if access.role!='owner': current_test=None
    return ReadinessView(contract_version='whatsapp-self-service.v1',business_id=business_id,
        onboarding_available=available,connection_version=version,local_status=status,blockers=tuple(blockers),
        provider_approval='not_evaluated',current_generation_test=current_test)


@router.post(BASE+'/signup')
async def start(request:Request,response:Response,business_id:UUID,db:AsyncSession=Depends(get_db),provider=Depends(provider_dependency)):
    auth=await authority(request,db,business_id,bind_app=True)
    payload=await command(request,StartSignup)
    try: result,nonce=await service.start_signup(db,auth,payload,provider=provider)
    except ProtocolError as error: protocol_error(error)
    response.set_cookie(COOKIE,nonce,httponly=True,secure=settings.PUBLIC_BASE_URL.startswith('https://') or request.url.scheme=='https',
        samesite='strict',max_age=600,path=f'/api/v1/businesses/{business_id}/channels/whatsapp/signup')
    await auth.finalize(db)
    return result


@router.get(BASE+'/signup/{attempt_id}')
async def signup(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id,mutation=False)
    result=await service.signup_view(db,await service.owned_attempt(db,auth,attempt_id))
    await auth.check(db)
    return result


@router.get(BASE+'/signup/{attempt_id}/choices')
async def choices(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id,mutation=False)
    row=await service.owned_attempt(db,auth,attempt_id)
    rows=(await db.scalars(select(WhatsAppSignupChoice).where(WhatsAppSignupChoice.attempt_id==row.id,
        WhatsAppSignupChoice.business_id==business_id).order_by(WhatsAppSignupChoice.id).limit(100))).all()
    result=ReviewedChoicesView(contract_version='whatsapp-signup-choices.v1',business_id=business_id,attempt_id=row.id,
        choices=tuple({'choice_id':c.id,'display_name':c.display_name,'phone_hint':'••'+c.phone_number_id[-6:],
            'waba_id':c.waba_id,'phone_number_id':c.phone_number_id,'display_phone_number':c.display_phone_number,
            'fingerprint':c.fingerprint,'registration_status':c.provider_registration_status} for c in rows))
    await auth.check(db)
    return result


@router.post(BASE+'/signup/{attempt_id}/exchange')
async def exchange(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db),provider=Depends(provider_dependency)):
    auth=await authority(request,db,business_id,bind_app=True)
    payload=await command(request,ExchangeSignup)
    try: result=await service.exchange_signup(db,auth,attempt_id,payload,request.cookies.get(COOKIE),provider=provider)
    except ProtocolError as error: protocol_error(error)
    try: await auth.finalize(db)
    except HTTPException:
        await service.effect_unknown(db,attempt_id,stage='exchange')
        raise
    return signup_ack(result,payload,'signup_exchange')


@router.post(BASE+'/signup/{attempt_id}/assets')
async def assets(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db),provider=Depends(provider_dependency)):
    auth=await authority(request,db,business_id,bind_app=True)
    payload=await command(request,SignupAssets)
    try: result=await service.discover_assets(db,auth,attempt_id,payload,provider=provider)
    except ProtocolError as error: protocol_error(error)
    await auth.finalize(db)
    return signup_ack(result,payload,'signup_assets')


@router.post(BASE+'/signup/{attempt_id}/select')
async def select_account(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db),provider=Depends(provider_dependency)):
    auth=await authority(request,db,business_id,bind_app=True)
    payload=await command(request,SelectSignup)
    try: result=await service.select_account(db,auth,attempt_id,payload,provider=provider)
    except ProtocolError as error: protocol_error(error)
    try: await auth.finalize(db)
    except HTTPException:
        await service.effect_unknown(db,attempt_id,stage='registration')
        raise
    return signup_ack(result,payload,'signup_select',choice_id=payload.choice_id)


@router.post(BASE+'/tests')
async def start_test(request:Request,business_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id)
    payload=await command(request,StartTest)
    view,private_command=await tests.start_test(db,auth,payload)
    result=TestChallengeView(contract_version='whatsapp-test-challenge.v1',test=view,command=private_command,receipt={
        'business_id':view.business_id,'idempotency_key':payload.idempotency_key,'action':'test_start',
        'expected_connection_version':view.connection_version,'resource_id':view.test_id,'selected_choice_id':None})
    await auth.finalize(db)
    return result


@router.get(BASE+'/tests/{test_id}')
async def test(request:Request,business_id:UUID,test_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id,mutation=False)
    result=await tests.test_view(db,await tests.own_test(db,auth,test_id))
    await auth.check(db)
    return result


@router.post(BASE+'/tests/{test_id}/send')
async def send_test(request:Request,business_id:UUID,test_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id)
    payload=await command(request,SendTest)
    result=await tests.queue_fixed_reply(db,auth,test_id,payload)
    await auth.finalize(db)
    return test_ack(result,payload,'test_send')


@router.post(BASE+'/tests/{test_id}/cancel')
async def cancel_test(request:Request,business_id:UUID,test_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id)
    payload=await command(request,Command)
    result=await tests.cancel_test(db,auth,test_id)
    await auth.finalize(db)
    return test_ack(result,payload,'test_cancel')


@router.get(BASE+'/tests/{test_id}/recipient')
async def recipient(request:Request,business_id:UUID,test_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id,mutation=False)
    row=await tests.own_test(db,auth,test_id)
    if row.recipient_contact_id is None or row.inbound_message_id is None or row.received_at is None:
        service.problem('test_recipient_required','No intended recipient has been verified for this test')
    contact=(await db.execute(select(WhatsAppContact.phone,WhatsAppContact.last_inbound_at,WhatsAppContact.opted_out).where(
        WhatsAppContact.id==row.recipient_contact_id,WhatsAppContact.seller_id==business_id))).one_or_none()
    if not contact or not contact.last_inbound_at:
        service.problem('test_recipient_required','The intended recipient has no current inbound window')
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==business_id))
    if account is None: service.problem('channel_generation_stale','The WhatsApp connection changed')
    await current_provenance(db,account,row.connection_version)
    queued=await db.scalar(select(WhatsAppTestAuthorization.test_id).where(WhatsAppTestAuthorization.test_id==row.id))
    timestamp=service.now()
    result=RecipientReview(contract_version='whatsapp-test-recipient.v1',business_id=business_id,test_id=row.id,
        connection_version=row.connection_version,recipient_contact_id=row.recipient_contact_id,
        inbound_message_id=row.inbound_message_id,phone=contact.phone,inbound_observed_at=row.received_at,
        reply_window_expires_at=contact.last_inbound_at+timedelta(hours=24),
        reply_allowed=bool(not queued and row.cancelled_at is None and row.expires_at>timestamp and not contact.opted_out
            and 0<=(timestamp-contact.last_inbound_at).total_seconds()<86400))
    await auth.check_request()
    # Last authority statement joins native sid/current owner/active tenant and
    # current generation/account after every awaited private lookup.
    await current_owner_session(db,auth.binding,generation=row.connection_version,phone_id=row.phone_number_id)
    return result


@router.post(BASE+'/signup/{attempt_id}/cancel')
async def cancel_signup(request:Request,business_id:UUID,attempt_id:UUID,db:AsyncSession=Depends(get_db)):
    auth=await authority(request,db,business_id)
    payload=await command(request,Command)
    result=await service.cancel_signup(db,auth,attempt_id,payload)
    await auth.finalize(db)
    return signup_ack(result,payload,'signup_cancel')


def signup_ack(result,payload,action,*,choice_id=None):
    return SignupCommandView(contract_version='whatsapp-signup-command.v1',result=result,receipt={
        'business_id':result.business_id,'idempotency_key':payload.idempotency_key,'action':action,
        'expected_connection_version':result.connection_version,'resource_id':result.attempt_id,'selected_choice_id':choice_id})


def test_ack(result,payload,action):
    return TestCommandView(contract_version='whatsapp-test-command.v1',result=result,receipt={
        'business_id':result.business_id,'idempotency_key':payload.idempotency_key,'action':action,
        'expected_connection_version':result.connection_version,'resource_id':result.test_id,'selected_choice_id':None})
