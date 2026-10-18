"""Frozen measurement inputs must never carry identity, paid or test assertions."""
import json
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.activity_v1 import ActivityRead,ContextWrite,Conversion,EventWrite,PolicyWrite


@pytest.mark.parametrize('extra',[{'business_id':str(uuid4())},{'is_test':False},{'classification':'live'},{'user_id':str(uuid4())},{'ip':'127.0.0.1'},{'url':'https://example.com/customer?phone=private'}])
def test_public_context_rejects_identity_or_classification_assertions(extra):
    with pytest.raises(ValidationError):ContextWrite(idempotency_key=uuid4(),**extra)


@pytest.mark.parametrize('body',[{'event_kind':'paid'},{'event_kind':'enquiry_message'},{'event_kind':'checkout_opened','product_id':str(uuid4())},{'event_kind':'product_view'},{'event_kind':'product_view','product_id':str(uuid4()),'message':'private'},{'event_kind':'product_view','product_id':str(uuid4()),'created_at':'2026-01-01T00:00:00Z'}])
def test_public_event_allowlist_cannot_manufacture_commercial_facts(body):
    with pytest.raises(ValidationError):EventWrite.model_validate(body)


@pytest.mark.parametrize('ack',[False,1,'true',None])
def test_collection_requires_strict_owner_notice_acknowledgement(ack):
    with pytest.raises(ValidationError):PolicyWrite(expected_revision=0,idempotency_key=uuid4(),mode='live',first_party_measurement_acknowledged=ack)


def test_unavailable_fixture_remains_null_not_zero():
    root=Path(__file__).resolve().parents[2]
    report=ActivityRead.model_validate_json((root/'docs/contracts/activity-v1/unavailable-report.json').read_text())
    assert report.counts.visits is None and report.conversion.percentage is None
    assert report.production_orders.excluded_unclassified==3 and report.production_orders.placed is None
    assert report.attribution is None and report.channel_activity.enquiry_messages is None


def test_conversion_is_exact_bounded_and_never_zero_denominator_percentage():
    assert Conversion(numerator=1,denominator=3,percentage='33.33',unavailable_reason=None).percentage=='33.33'
    assert Conversion(numerator=0,denominator=0,percentage=None,unavailable_reason='no_observed_contexts').percentage is None
    for n,d,p,reason in [(2,1,'100.00',None),(1,3,'33.34',None),(0,0,'0.00',None),(None,None,None,None),(1,3,'33.33','partial_coverage')]:
        with pytest.raises(ValidationError):Conversion(numerator=n,denominator=d,percentage=p,unavailable_reason=reason)
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from jose import jwt
from app.config import settings
from app.services import activity_v1 as domain


@pytest.mark.parametrize('change',['role','purpose','audience','extra','boolean_time','long_window','future'])
def test_activity_capability_is_distinct_strict_and_bounded(change):
    now=datetime.now(timezone.utc)
    row=SimpleNamespace(id=uuid4(),business_id=uuid4(),started_at=now,expires_at=now+timedelta(minutes=30))
    token=domain.issue_capability(row);claims=domain.decode_capability('Bearer '+token)
    if change=='role':claims['role']='v1_user'
    elif change=='purpose':claims['purpose']='v1_public_checkout'
    elif change=='audience':claims['aud']='munimjee.checkout-session.v1'
    elif change=='extra':claims['paid']=True
    elif change=='boolean_time':claims['iat']=True
    elif change=='long_window':claims['exp']+=1
    else:claims['iat']+=60;claims['exp']+=60
    changed=jwt.encode(claims,settings.SECRET_KEY,algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as error:domain.decode_capability('Bearer '+changed)
    assert error.value.status_code==401 and error.value.detail=='Measurement context is invalid or expired'
