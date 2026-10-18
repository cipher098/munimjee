"""Pure contract checks; migrated assignment/HTTP tests use the actual0050 chain."""
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.assistance import AssignmentWrite,AssistanceOpenWrite,AssistanceCommandRead
from app.services.assistance import action,hash_request,native
from app.services.identity import Actor
from fastapi import HTTPException


@pytest.mark.parametrize('change',[
    {'reviewed':False},{'reviewed':1},{'reviewed':'true'},
    {'expected_version':True},{'expected_version':'0'},{'expected_version':-1},
    {'expected_version':2000000001},{'business_id':str(uuid4())},
    {'role':'owner'},{'support_grant':True},{'assignee_user_id':'not-a-user'},
])
def test_assignment_never_accepts_coerced_or_unowned_authority(change):
    body=dict(idempotency_key=uuid4(),expected_version=0,assignee_user_id=None,reviewed=True)
    with pytest.raises(ValidationError):AssignmentWrite.model_validate({**body,**change})


def test_assignment_explicit_clear_is_valid_and_open_has_no_grant_fields():
    command=AssignmentWrite(idempotency_key=uuid4(),expected_version=0,assignee_user_id=None,reviewed=True)
    assert command.assignee_user_id is None
    with pytest.raises(ValidationError):AssistanceOpenWrite.model_validate({'idempotency_key':str(uuid4()),'impersonate':True})


def test_only_mounted_exact_business_routes_become_actions():
    bid=uuid4()
    assert action({'/v1/businesses/{business_id}/catalogue'},bid,'/v1/businesses/{business_id}/catalogue')==f'/v1/businesses/{bid}/catalogue'
    assert action({'/v1'},bid,'/v1?business={business_id}#profile')==f'/v1?business={bid}#profile'
    assert action(set(),bid,'/v1/businesses/{business_id}/payments') is None


def test_hash_binds_operation_version_assignee_and_key_without_ordering_noise():
    original={'idempotency_key':str(uuid4()),'expected_version':0,'assignee_user_id':None,'reviewed':True}
    value=hash_request('assignment',original)
    assert value==hash_request('assignment',dict(reversed(list(original.items()))))
    assert value!=hash_request('open',original)
    for field,replacement in [('expected_version',1),('assignee_user_id',str(uuid4())),('idempotency_key',str(uuid4()))]:
        assert value!=hash_request('assignment',{**original,field:replacement})


@pytest.mark.parametrize('method',['legacy_owner','admin','support','public_checkout_session'])
def test_assistance_cannot_adapt_legacy_or_support_authority(method):
    with pytest.raises(HTTPException) as error:native(Actor(uuid4(),method))
    assert error.value.status_code==401
    native(Actor(uuid4(),'v1_user'))


def test_receipt_does_not_expose_private_configuration_or_a_grant():
    value=dict(business_id=uuid4(),idempotency_key=uuid4(),operation='open',version=None,
        assignee_user_id=None,workspace_url='/v1/businesses/synthetic/assistance',replayed=False)
    record=AssistanceCommandRead(**value)
    assert record.operation=='open'
    for key in ('seller_token','support_grant','key_secret','provider_account_id'):
        with pytest.raises(ValidationError):AssistanceCommandRead(**{**value,key:'private'})
