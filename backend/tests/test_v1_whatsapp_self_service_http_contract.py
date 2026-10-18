"""No-DB request boundary checks; HTTP effects/authority use actual PG later."""
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.whatsapp_self_service import command
from app.schemas.whatsapp_self_service import ExchangeSignup, StartSignup, TestChallengeView, RecipientReview
from app.services.whatsapp_test_protocol import SessionBinding, challenge_command


def request(data,content_type='application/json'):
    async def receive(): return {'type':'http.request','body':data,'more_body':False}
    return Request({'type':'http','method':'POST','path':'/','headers':[(b'content-type',content_type.encode())]},receive)


@pytest.mark.asyncio
@pytest.mark.parametrize('body',[
    b'{"idempotency_key":"secret-do-not-echo","code":"private-code","signed_state":"private-state"}',
    b'{"idempotency_key":null,"idempotency_key":"duplicate","code":"private-code"}',
    b'['*2000+b'0'+b']'*2000,
    b'x'*16385,
    b'\xff',
])
async def test_secret_bearing_invalid_json_never_uses_input_echo_validation(body):
    with pytest.raises(HTTPException) as error:
        await command(request(body),ExchangeSignup)
    assert error.value.status_code==422
    assert error.value.detail=='Review the connection details and try again'
    assert 'private-code' not in repr(error.value) and 'secret-do-not-echo' not in repr(error.value)


@pytest.mark.asyncio
async def test_body_requires_json_and_strict_real_consent():
    payload={'idempotency_key':str(uuid4()),'expected_connection_version':0,'notice_reviewed':1}
    with pytest.raises(HTTPException): await command(request(json.dumps(payload).encode()),StartSignup)
    payload['notice_reviewed']=True
    with pytest.raises(HTTPException): await command(request(json.dumps(payload).encode(),'text/plain'),StartSignup)
    assert (await command(request(json.dumps(payload).encode()),StartSignup)).notice_reviewed is True


def test_private_challenge_response_does_not_repr_raw_command():
    binding=SessionBinding(uuid4(),uuid4(),uuid4(),0)
    private_command=challenge_command('synthetic-only',uuid4(),binding)
    view={'contract_version':'whatsapp-test.v1','business_id':str(binding.business_id),'test_id':str(uuid4()),
        'connection_version':0,'status':'awaiting_recipient','recipient_hint':None,'inbound_observed_at':None,
        'message_id':None,'provider_delivery_observed_at':None,'delivery_confirmed':False,'recorded_effect_status':None,'can_prepare_new_test':False,
        'is_current_generation':True,'proof_source':'not_recorded','message':'Waiting for intended recipient'}
    result=TestChallengeView(contract_version='whatsapp-test-challenge.v1',test=view,command=private_command,receipt={
        'business_id':binding.business_id,'idempotency_key':uuid4(),'action':'test_start','expected_connection_version':0,
        'resource_id':view['test_id'],'selected_choice_id':None})
    assert private_command not in repr(result)


def test_owner_recipient_projection_has_no_duplicate_pii_fields_or_repr_echo():
    from pathlib import Path
    fixture=json.loads((Path(__file__).resolve().parents[2]/'docs/contracts/whatsapp-self-service/proposal.v1.json').read_text())['recipient_review_example']
    result=RecipientReview.model_validate(fixture)
    assert fixture['phone'] not in repr(result)
    assert set(result.model_dump())==set(fixture)
