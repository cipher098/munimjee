"""Synthetic documentary compatibility fixtures; no provider calls or DB."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.whatsapp_test_protocol import (
    MESSAGE_ORIGIN, ProtocolError, SessionBinding, bound_nonce, challenge_command,
    command_digest, embedded_configuration, phone_page, reserved_command, verified_token,
)

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
SECRET = 'synthetic-test-only'
BINDING = SessionBinding(UUID(int=1), UUID(int=2), UUID(int=3), 0)


def documentary_debug():
    return {'data': {'is_valid': True, 'app_id': '123', 'expires_at': int((NOW+timedelta(hours=1)).timestamp()),
        'scopes': ['whatsapp_business_management','whatsapp_business_messaging'],
        'granular_scopes': [{'scope': scope, 'target_ids': ['456']} for scope in
                           ('whatsapp_business_management','whatsapp_business_messaging')]}}


def config(**kwargs):
    return SimpleNamespace(**{
        'V1_WHATSAPP_ONBOARDING_ENABLED': True, 'WHATSAPP_EMBEDDED_APP_ID': '123',
        'WHATSAPP_EMBEDDED_CONFIG_ID': '789', 'WHATSAPP_EMBEDDED_APP_SECRET': SECRET,
        'WHATSAPP_APP_SECRET': SECRET, 'WHATSAPP_EMBEDDED_GRAPH_VERSION': 'v26.0',
        'CHANNEL_ENCRYPTION_KEY': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=', 'WHATSAPP_WEBHOOK_VERIFY_TOKEN': 'synthetic-verify-only', 'PUBLIC_BASE_URL': 'https://example.invalid', **kwargs})


def token():
    return verified_token({'access_token':'synthetic-never-sent'}, documentary_debug(), app_id='123', now=NOW)


def test_nonce_exact_start_replay_and_every_principal_dimension():
    attempt = UUID(int=4)
    value = bound_nonce(SECRET, attempt, BINDING)
    assert value == bound_nonce(SECRET, attempt, BINDING)
    assert len(value)==43
    for binding in (replace(BINDING,business_id=uuid4()), replace(BINDING,user_id=uuid4()),
                    replace(BINDING,session_id=uuid4()),replace(BINDING,auth_version=1)):
        assert bound_nonce(SECRET, attempt, binding) != value
    assert bound_nonce(SECRET, uuid4(), BINDING) != value
    assert bound_nonce('other', attempt, BINDING) != value


def test_challenge_is_deterministic_and_purpose_separated():
    challenge = challenge_command(SECRET, UUID(int=4), BINDING)
    assert challenge == challenge_command(SECRET, UUID(int=4), BINDING)
    assert reserved_command(challenge) and command_digest(SECRET, challenge)
    assert challenge.split(':')[1] not in bound_nonce(SECRET, UUID(int=4), BINDING)
    assert command_digest(SECRET, challenge) != command_digest('other', challenge)


@pytest.mark.parametrize('text', ['munimjee-wa-test:bad', 'prefix MUNIMJEE-WA-TEST suffix',
    'MUNIMJEE-WA-TEST:', 'MUNIMJEE-WA-TEST:AAAAAAAAAAAAAAAAAAAAAB', 'MUNIMJEE-WA-TEST:AAAAAAAAAAAAAAAAAAAAAA\n'])
def test_all_reserved_malformed_commands_are_withheld_but_cannot_prove(text):
    assert reserved_command(text)
    assert command_digest(SECRET, text) is None


@pytest.mark.parametrize('text', [None, 12, {'text':'MUNIMJEE-WA-TEST'}, 'hello'])
def test_noncommands_never_prove(text):
    assert not reserved_command(text)
    assert command_digest(SECRET,text) is None


def test_sdk_configuration_has_no_implicit_measurement_or_secret():
    result = embedded_configuration(config())
    assert result['allowed_message_origin']==MESSAGE_ORIGIN
    assert not result['auto_log_app_events'] and not result['xfbml']
    assert SECRET not in repr(result)


@pytest.mark.parametrize('override,code', [({'V1_WHATSAPP_ONBOARDING_ENABLED':False},'configuration_unavailable'),
    ({'WHATSAPP_EMBEDDED_APP_SECRET':'other'},'configuration_mismatch'),
    ({'WHATSAPP_APP_SECRET':''},'configuration_unavailable'),
    ({'WHATSAPP_EMBEDDED_APP_SECRET':'invalid-unicode-☃'},'configuration_unavailable'),
    ({'WHATSAPP_EMBEDDED_APP_SECRET':'invalid\nline'},'configuration_unavailable'),
    ({'CHANNEL_ENCRYPTION_KEY':'malformed'},'configuration_unavailable'),
    ({'WHATSAPP_WEBHOOK_VERIFY_TOKEN':''},'configuration_unavailable'),
    ({'WHATSAPP_EMBEDDED_GRAPH_VERSION':'v23.0'},'configuration_unavailable'),
    ({'PUBLIC_BASE_URL':'http://example.invalid'},'configuration_unavailable'),
    ({'PUBLIC_BASE_URL':'https://user:password@example.invalid'},'configuration_unavailable')])
def test_sdk_gate_is_independent_and_mismatch_does_not_change_webhook_authority(override,code):
    settings=config(**override)
    original=settings.WHATSAPP_APP_SECRET
    with pytest.raises(ProtocolError,match=code):
        embedded_configuration(settings)
    assert settings.WHATSAPP_APP_SECRET==original


def test_documentary_token_fixture_is_not_in_repr_and_expires():
    result=token()
    assert 'synthetic-never-sent' not in repr(result)
    assert result.waba_ids==frozenset({'456'}) and result.expires_at>NOW


@pytest.mark.parametrize('expiry',[None,0,False,'123',-1])
def test_unknown_expiry_is_never_permanent(expiry):
    debug=documentary_debug()
    debug['data']['expires_at']=expiry
    with pytest.raises(ProtocolError,match='provider_expiry_unknown'):
        verified_token({'access_token':'synthetic-secret'},debug,app_id='123',now=NOW)


def test_data_access_expiry_shortens_grant_and_unknown_is_not_permanent():
    debug=documentary_debug()
    expiry=int((NOW+timedelta(minutes=5)).timestamp())
    debug['data']['data_access_expires_at']=expiry
    assert verified_token({'access_token':'synthetic'},debug,app_id='123',now=NOW).expires_at.timestamp()==expiry
    debug['data']['data_access_expires_at']=0
    with pytest.raises(ProtocolError,match='provider_expiry_unknown'):
        verified_token({'access_token':'synthetic'},debug,app_id='123',now=NOW)


@pytest.mark.parametrize('mutation', ['wrong_app','invalid','missing_grant','different_targets','missing_targets','duplicate_scope','numeric_target'])
def test_unverified_or_ambiguous_grants_fail_closed(mutation):
    debug=documentary_debug(); data=debug['data']
    if mutation=='wrong_app': data['app_id']='999'
    if mutation=='invalid': data['is_valid']=1
    if mutation=='missing_grant': data['scopes'].pop()
    if mutation=='different_targets': data['granular_scopes'][1]['target_ids']=['999']
    if mutation=='missing_targets': data['granular_scopes'][1].pop('target_ids')
    if mutation=='duplicate_scope': data['granular_scopes'].append(data['granular_scopes'][0])
    if mutation=='numeric_target': data['granular_scopes'][0]['target_ids']=[456]
    with pytest.raises(ProtocolError):
        verified_token({'access_token':'synthetic'},debug,app_id='123',now=NOW)


def test_provider_errors_never_retain_credentials_or_raw_objects():
    with pytest.raises(ProtocolError) as error:
        verified_token({'access_token':{'secret':'do-not-echo'}},documentary_debug(),app_id='123',now=NOW)
    assert str(error.value)=='provider_response_invalid'
    assert 'do-not-echo' not in repr(error.value)
    assert error.value.__cause__ is None


def test_membership_is_server_verified_not_sdk_phone_assertion():
    page={'data':[{'id':'789','verified_name':'Synthetic business','display_phone_number':'+910000000000',
                    'code_verification_status':'VERIFIED'}]}
    choices,after=phone_page(page,waba_id='456',verified=token())
    assert after is None and choices[0].provider_registration_status=='unknown'
    with pytest.raises(ProtocolError,match='provider_account_unverified'):
        phone_page(page,waba_id='999',verified=token())


def test_paging_never_follows_provider_url_and_requires_bounded_cursor():
    page={'data':[],'paging':{'next':'https://attacker.invalid/secret','cursors':{'after':'opaque-cursor'}}}
    assert phone_page(page,waba_id='456',verified=token())==((), 'opaque-cursor')
    page['paging'].pop('cursors')
    with pytest.raises(ProtocolError): phone_page(page,waba_id='456',verified=token())


def test_duplicate_phone_ids_and_oversize_page_fail_closed():
    item={'id':'789','verified_name':'Synthetic','display_phone_number':'+910000000000'}
    for rows in ([item,item],[dict(item,id=str(i)) for i in range(26)]):
        with pytest.raises(ProtocolError): phone_page({'data':rows},waba_id='456',verified=token())
