"""Frozen analytics examples preserve exact money and reject unsupported claims/PII."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.schemas.analytics_v1 import AnalyticsRead

ROOT=Path(__file__).resolve().parents[2]/'docs/contracts/analytics-v1'


@pytest.mark.parametrize('name',['empty-read.json','mixed-read.json'])
def test_frozen_fixtures(name):
    data=json.loads((ROOT/name).read_text())
    assert AnalyticsRead.model_validate(data).model_dump(mode='json')==data


@pytest.mark.parametrize('mutation',['private','refund_zero','numeric_money','boolean_count','missing_zone'])
def test_no_private_extra_fields_invented_refunds_or_inexact_money(mutation):
    data=json.loads((ROOT/'mixed-read.json').read_text())
    if mutation=='private':data['orders'][0]['gateway_credentials']={'key_secret':'not-a-real-secret'}
    elif mutation=='refund_zero':data['unavailable']['completed_refunds_minor']=0
    elif mutation=='numeric_money':data['currency_totals'][0]['online_paid_minor']=9007199254740993
    elif mutation=='boolean_count':data['counts']['placed']=True
    else:data['generated_at']='2026-10-19T00:00:00'
    with pytest.raises(ValidationError):AnalyticsRead.model_validate(data)


def test_large_minor_units_remain_exact_decimal_strings():
    data=json.loads((ROOT/'mixed-read.json').read_text());data['currency_totals'][0]['online_paid_minor']='9007199254740993'
    assert AnalyticsRead.model_validate(data).currency_totals[0].online_paid_minor=='9007199254740993'
