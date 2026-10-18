"""Synthetic transport proof only; no Meta traffic, credentials or sends."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import whatsapp_signup_provider as provider
from app.services.whatsapp_test_protocol import ProtocolError, VerifiedToken

NOW=datetime(2026,10,18,tzinfo=timezone.utc)
TOKEN=VerifiedToken('synthetic-not-a-real-token','123',NOW+timedelta(hours=1),frozenset({'456'}))


class FakeTransport:
    def __init__(self,responses): self.responses=list(responses); self.requests=[]
    async def request(self,request):
        provider.validate_request(request)
        self.requests.append(request)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_pagination_uses_our_graph_route_not_untrusted_next_url():
    transport=FakeTransport([
        {'data':[{'id':'1','verified_name':'Synthetic1','display_phone_number':'+910000000001'}],
         'paging':{'next':'https://attacker.invalid/token','cursors':{'after':'cursor1'}}},
        {'data':[{'id':'2','verified_name':'Synthetic2','display_phone_number':'+910000000002'}]},
    ])
    client=provider.SignupProvider(SimpleNamespace(),transport)
    choices=await client.choices(TOKEN,'456')
    assert [c.phone_number_id for c in choices]==['1','2']
    assert [r.path for r in transport.requests]==['/v26.0/456/phone_numbers']*2
    assert dict(transport.requests[1].query)['after']=='cursor1'
    assert 'attacker' not in repr(transport.requests)


@pytest.mark.asyncio
async def test_foreign_waba_never_dispatches_and_repeated_cursor_is_not_followed():
    transport=FakeTransport([{'data':[],'paging':{'next':'ignored','cursors':{'after':'repeat'}}}]*2)
    client=provider.SignupProvider(SimpleNamespace(),transport)
    with pytest.raises(ProtocolError): await client.choices(TOKEN,'999')
    assert not transport.requests
    with pytest.raises(ProtocolError): await client.choices(TOKEN,'456')
    assert len(transport.requests)==2


@pytest.mark.asyncio
async def test_fifth_page_is_never_requested():
    transport=FakeTransport([{'data':[],'paging':{'next':'ignored','cursors':{'after':str(i)}}} for i in range(4)])
    with pytest.raises(ProtocolError,match='provider_page_limit'):
        await provider.SignupProvider(SimpleNamespace(),transport).choices(TOKEN,'456')
    assert len(transport.requests)==4


@pytest.mark.asyncio
@pytest.mark.parametrize('response',[{'success':1},{'success':True,'unexpected':'value'},{'success':False},{'error':{'secret':'not-echoed'}}])
async def test_provider_mutation_requires_exact_boolean_success_without_retry(response):
    transport=FakeTransport([response])
    client=provider.SignupProvider(SimpleNamespace(),transport)
    with pytest.raises(ProtocolError) as error: await client.subscribe(TOKEN.token,'456')
    assert len(transport.requests)==1
    assert 'not-echoed' not in repr(error.value)


@pytest.mark.parametrize('graph_request',[
    provider.GraphRequest('DELETE','/v26.0/456/subscribed_apps',token='synthetic',body={}),
    provider.GraphRequest('GET','https://attacker.invalid/token'),
    provider.GraphRequest('GET','/v23.0/456/phone_numbers',token='synthetic'),
    provider.GraphRequest('POST','/v26.0/456/register',token='synthetic',body={'messaging_product':'whatsapp','pin':'123456','to':'recipient'}),
    provider.GraphRequest('GET','/v26.0/oauth/access_token',query=(('client_id','123'),('client_secret','secret'),('code','code'),('code','other'))),
])
def test_arbitrary_routes_versions_methods_and_query_duplicates_deny(graph_request):
    with pytest.raises(ProtocolError): provider.validate_request(graph_request)


def test_secret_bearing_request_repr_is_private():
    request=provider.GraphRequest('POST','/v26.0/456/register',token='do-not-echo',body={'messaging_product':'whatsapp','pin':'123456'})
    assert 'do-not-echo' not in repr(request) and '123456' not in repr(request)


def test_actual_socket_transport_never_sends_to_private_dns(monkeypatch):
    monkeypatch.setattr(provider.socket,'getaddrinfo',lambda *a,**kw:[(None,None,None,None,('127.0.0.1',443))])
    monkeypatch.setattr(provider,'PinnedHTTPSConnection',lambda *a,**kw:pytest.fail('must not create connection'))
    request=provider.GraphRequest('GET','/v26.0/123/phone_numbers',token='synthetic',query=(('fields','id'),('limit','25')))
    with pytest.raises(provider.SignupProviderError): provider.PinnedGraphTransport._request(request)


def test_actual_socket_transport_does_not_log_or_parse_error_body(monkeypatch):
    class Response:
        status=302
        def getheaders(self): return [('location','https://attacker.invalid')]
        def read1(self,*a): pytest.fail('must not read error/redirect body')
    class Socket:
        def settimeout(self,value): pass
    class Connection:
        sock=Socket()
        def __init__(self,*a): self.requests=[]
        def connect(self): pass
        def request(self,*a,**kw): self.requests.append((a,kw))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(provider.socket,'getaddrinfo',lambda *a,**kw:[(None,None,None,None,('8.8.8.8',443))])
    monkeypatch.setattr(provider,'PinnedHTTPSConnection',Connection)
    request=provider.GraphRequest('GET','/v26.0/oauth/access_token',query=(('client_id','123'),('client_secret','do-not-echo'),('code','one-use-secret')))
    with pytest.raises(provider.SignupProviderError) as error: provider.PinnedGraphTransport._request(request)
    assert str(error.value)=='provider_result_unknown'
    assert 'do-not-echo' not in repr(error.value) and error.value.__cause__ is None


def test_json_duplicate_authority_fields_are_rejected():
    with pytest.raises(ValueError): provider._unique_object([('is_valid',True),('is_valid',False)])
