"""Literal file facts and explicit document identity, without external adapters."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.imports_v1 import ImportJobCreate
from app.services.imports_v1 import JobClaim, collect_claim
from app.v1.imports.csv_source import CSVSourceError, parse_csv


def test_csv_literal_quotes_bom_unknown_zero_and_currency():
    rows = parse_csv(b'\xef\xbb\xbfproduct_ref,title,description,price,currency,stock,options_state\r\n A ,"=SUM(1,2)","line 1\r\nline ""2""",12.50,USD,0,none\r\nB,,,,,,unknown\r\n')
    assert rows[0].product_ref == 'A' and rows[0].line == 2
    assert rows[0].facts.title == '=SUM(1,2)'
    assert rows[0].facts.description == 'line 1\nline "2"'
    assert rows[0].facts.price.currency == 'USD' and rows[0].facts.stock == 0
    assert rows[0].facts.options == ()
    assert all(value is None for value in rows[1].facts.model_dump().values())
    assert rows[1].line == 4


@pytest.mark.parametrize('body,code', [
    (b'', 'size'), (b'product_ref\nx\n'+b' '*256000, 'size'),
    (b'product_ref\n\xff', 'encoding'), (b'\xff\xfep\x00', 'encoding'),
    (b'product_ref\nx\x00', 'control'), (b'product_ref\rx', 'control'),
    ('product_ref\nx\ufeff'.encode(), 'control'),
    (b'product_ref,title\nx,a"b', 'quoting'), (b'product_ref,title\nx,"a"z', 'quoting'),
    (b'product_ref,title\nx,"a', 'quoting'),
    (b'title\nx', 'headers'), (b'product_ref,unknown\nx,y', 'headers'),
    (b'product_ref,title,title\nx,a,b', 'headers'), (b'product_ref,\nx,a', 'headers'),
    (b'product_ref,title\nx', 'column_count'), (b'product_ref\nx\n x ', 'duplicate_ref'),
    (b'product_ref,title\n,hello', 'invalid_fact'), (b'product_ref\n', 'no_products'),
    (b'product_ref,price\nx,12', 'price_currency_pair'),
    (b'product_ref,currency\nx,INR', 'price_currency_pair'),
    (b'product_ref,price,currency\nx,12,inr', 'invalid_fact'),
    (b'product_ref,price,currency\nx,0,INR', 'invalid_fact'),
    (b'product_ref,price,currency\nx,1.001,INR', 'invalid_fact'),
    (b'product_ref,price,currency\nx,1e2,INR', 'invalid_fact'),
    (b'product_ref,stock\nx,-1', 'invalid_fact'), (b'product_ref,stock\nx,true', 'invalid_fact'),
    (b'product_ref,stock\nx,1000001', 'invalid_fact'), (b'product_ref,stock\nx,1.0', 'invalid_fact'),
    (b'product_ref,options_state\nx,yes', 'invalid_fact'),
    (b'product_ref,title\nx,'+b'a'*201, 'field_limit'),
])
def test_csv_fail_closed_without_echoing_values(body, code):
    with pytest.raises(CSVSourceError) as caught:
        parse_csv(body)
    assert caught.value.code.startswith('csv_'+code+':line_')
    assert len(caught.value.code) <= 80 and 'hello' not in caught.value.code


def test_csv_record_and_text_limits_and_case_sensitive_references():
    assert len(parse_csv(('product_ref\n'+'\n'.join(str(i) for i in range(200))).encode())) == 200
    with pytest.raises(CSVSourceError, match='row_limit'):
        parse_csv(('product_ref\n'+'\n'.join(str(i) for i in range(201))).encode())
    assert len(parse_csv(b'\nproduct_ref\n\nx\nX\n')) == 2
    assert len(parse_csv(('product_ref,description\nx,'+'a'*4000).encode())[0].facts.description) == 4000
    with pytest.raises(CSVSourceError, match='field_limit'):
        parse_csv(('product_ref,description\nx,'+'a'*4001).encode())


@pytest.mark.asyncio
async def test_csv_document_not_file_row_or_title_is_candidate_identity():
    business, document = uuid4(), uuid4()
    claim = JobClaim(uuid4(), business, uuid4(), uuid4(),
        {'kind':'csv','document_id':str(document),'document_label':'Literal source','media_id':f'csv-document:{document}','upload_sha256':'a'*64},
        datetime.now(timezone.utc), b'product_ref,title\nA,First\nB,Second', 'text/csv')
    class NoNetwork:
        async def fetch(self, *a, **kw):
            pytest.fail('CSV must not fetch any source')
    first = await collect_claim(claim, fetcher=NoNetwork())
    second = await collect_claim(replace(claim, job_id=uuid4(), upload_content=b'product_ref,title\nB,Changed\nA,Other'), fetcher=NoNetwork())
    assert first[0].id == second[1].id and first[1].id == second[0].id
    assert first[0].state.value == 'review_required' and first[0].extracted.stock is None
    assert 'source line 2' in first[0].provenance.evidence and 'First' not in first[0].provenance.evidence
    other_business = await collect_claim(replace(claim, business_id=uuid4()), fetcher=NoNetwork())
    other_document = await collect_claim(replace(claim, source={**claim.source,'media_id':f'csv-document:{uuid4()}'}), fetcher=NoNetwork())
    assert first[0].id != other_business[0].id != other_document[0].id


def test_csv_transport_shape_and_document_label_are_explicit():
    base = dict(idempotency_key=uuid4(),source_authorized=True,source_kind='csv',asset_id=uuid4(),document_id=uuid4(),document_label=' Source ')
    assert ImportJobCreate(**base).document_label == 'Source'
    for changes in ({'document_id':None},{'document_label':' '},{'source_url':'https://example.com'},{'source_kind':'uploaded_media'}):
        with pytest.raises(ValidationError):
            ImportJobCreate(**(base|changes))
