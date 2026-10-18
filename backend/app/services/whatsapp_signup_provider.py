"""Narrow logging-free Meta transport for the gated v4 documentary contract.

No redirects, proxy environment, request logging, automatic retries or provider
error bodies. The production wire/grant shape remains an external canary gate.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urlencode

from app.v1.imports.fetching import PinnedHTTPSConnection, public_ip
from app.services.whatsapp_test_protocol import ProtocolError, phone_page, verified_token


class SignupProviderError(ValueError):
    def __init__(self):
        super().__init__('provider_result_unknown')


@dataclass(frozen=True)
class GraphRequest:
    method: str
    path: str = field(repr=False)
    token: str | None = field(default=None, repr=False)
    query: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    body: dict | None = field(default=None, repr=False)


def validate_request(request):
    if request.method not in ('GET','POST') or not re.fullmatch(
        r'/v26\.0/(?:oauth/access_token|debug_token|[0-9]{1,40}/(?:phone_numbers|subscribed_apps|register))',request.path):
        raise ProtocolError('provider_response_invalid')
    if request.token is not None and (type(request.token) is not str or not 1<=len(request.token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in request.token)):
        raise ProtocolError('provider_response_invalid')
    expected = {
        '/v26.0/oauth/access_token': ('GET',frozenset({'client_id','client_secret','code'})),
        '/v26.0/debug_token': ('GET',frozenset({'input_token','access_token'})),
    }.get(request.path)
    keys=[key for key,value in request.query]
    if len(set(keys))!=len(keys) or any(type(k) is not str or type(v) is not str or not 1<=len(v)<=8192 or any(ord(c)<32 or ord(c)>126 for c in v) for k,v in request.query):
        raise ProtocolError('provider_response_invalid')
    if expected:
        if request.method!=expected[0] or frozenset(keys)!=expected[1] or request.token is not None or request.body is not None:
            raise ProtocolError('provider_response_invalid')
    elif request.path.endswith('/phone_numbers'):
        if request.method!='GET' or not request.token or not {'fields','limit'}.issubset(keys) or not set(keys).issubset({'fields','limit','after'}) or request.body is not None or dict(request.query).get('limit')!='25' or dict(request.query).get('fields')!='id,verified_name,display_phone_number':
            raise ProtocolError('provider_response_invalid')
    elif request.path.endswith('/subscribed_apps'):
        if request.method!='POST' or not request.token or keys or request.body!={}:
            raise ProtocolError('provider_response_invalid')
    elif request.path.endswith('/register'):
        if request.method!='POST' or not request.token or keys or type(request.body) is not dict or set(request.body)!={'messaging_product','pin'} or request.body['messaging_product']!='whatsapp' or type(request.body['pin']) is not str or not re.fullmatch(r'[0-9]{6}',request.body['pin']):
            raise ProtocolError('provider_response_invalid')


class PinnedGraphTransport:
    _pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='wa-signup')
    _lock=Lock()
    _inflight=set()

    async def request(self, request: GraphRequest):
        validate_request(request)
        with self._lock:
            type(self)._inflight={future for future in self._inflight if not future.done()}
            if len(self._inflight)>=4:
                raise SignupProviderError()
            future=self._pool.submit(self._request,request)
            self._inflight.add(future)
        wrapped=asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped),20)
        except Exception:
            # The socket may have sent before timeout/cancellation. Its durable
            # step was already claimed; callers must retain unknown, not retry.
            raise SignupProviderError() from None

    @staticmethod
    def _request(request):
        deadline=time.monotonic()+20
        connection=None
        try:
            addresses=socket.getaddrinfo('graph.facebook.com',443,type=socket.SOCK_STREAM)
            ips=tuple(dict.fromkeys(public_ip(row[4][0]) for row in addresses))
            if not ips or time.monotonic()>=deadline:
                raise SignupProviderError()
            connection=PinnedHTTPSConnection('graph.facebook.com',ips[0],max(.01,deadline-time.monotonic()))
            connection.connect()
            def remaining():
                budget=deadline-time.monotonic()
                if budget<=0:
                    raise SignupProviderError()
                if connection.sock:
                    connection.sock.settimeout(budget)
            remaining()
            headers={'Accept':'application/json','Accept-Encoding':'identity','Connection':'close','User-Agent':'Munimjee-WhatsApp-Setup/1'}
            if request.token is not None:
                headers['Authorization']='Bearer '+request.token
            body=None
            if request.body is not None:
                body=json.dumps(request.body,separators=(',',':')).encode()
                headers['Content-Type']='application/json'
            path=request.path+('?' + urlencode(request.query) if request.query else '')
            connection.request(request.method,path,body=body,headers=headers)
            remaining()
            response=connection.getresponse()
            raw_headers=response.getheaders()
            if sum(len(k)+len(v) for k,v in raw_headers)>16384:
                raise SignupProviderError()
            headers={}
            for key,value in raw_headers:
                if key.lower() in headers:
                    raise SignupProviderError()
                headers[key.lower()]=value
            if response.status!=200 or headers.get('content-encoding','identity').lower() not in ('identity',''):
                raise SignupProviderError()
            if headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
                raise SignupProviderError()
            declared=headers.get('content-length')
            if declared is not None and (not re.fullmatch(r'[0-9]{1,10}',declared) or int(declared)>65536):
                raise SignupProviderError()
            result=bytearray()
            while True:
                remaining()
                chunk=response.read1(min(8192,65537-len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result)>65536:
                    raise SignupProviderError()
            decoded=json.loads(result.decode('utf-8'),object_pairs_hook=_unique_object)
            if type(decoded) is not dict or 'error' in decoded:
                raise SignupProviderError()
            return decoded
        except Exception:
            raise SignupProviderError() from None
        finally:
            if connection:
                connection.close()


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError()
        result[key]=value
    return result


class SignupProvider:
    evidence_kind='provider'

    def __init__(self, settings, transport=None):
        self.settings=settings
        self.transport=transport or PinnedGraphTransport()

    async def exchange(self, code, *, now):
        app_id=self.settings.WHATSAPP_EMBEDDED_APP_ID
        secret=self.settings.WHATSAPP_EMBEDDED_APP_SECRET
        body=await self.transport.request(GraphRequest('GET','/v26.0/oauth/access_token',query=(
            ('client_id',app_id),('client_secret',secret),('code',code))))
        # Validate token before placing it in any debug request.
        if type(body) is not dict or set(body)!={'access_token'} or type(body.get('access_token')) is not str or not re.fullmatch(r'[\x21-\x7e]{1,8192}',body['access_token']):
            raise ProtocolError('provider_response_invalid')
        return await self.inspect(body['access_token'],now=now)

    async def inspect(self, token, *, now):
        app_id=self.settings.WHATSAPP_EMBEDDED_APP_ID
        secret=self.settings.WHATSAPP_EMBEDDED_APP_SECRET
        debug=await self.transport.request(GraphRequest('GET','/v26.0/debug_token',query=(
            ('input_token',token),('access_token',app_id+'|'+secret))))
        return verified_token({'access_token':token},debug,app_id=app_id,now=now)

    async def choices(self, verified, waba_id):
        choices=[]; after=None; seen_cursors=set(); seen_phones=set()
        for _ in range(4):
            query=[('fields','id,verified_name,display_phone_number'),('limit','25')]
            if after:
                query.append(('after',after))
            # Verify membership before any user-supplied ID enters a request.
            if waba_id not in verified.waba_ids:
                raise ProtocolError('provider_account_unverified')
            body=await self.transport.request(GraphRequest('GET','/v26.0/'+waba_id+'/phone_numbers',token=verified.token,query=tuple(query)))
            page,after=phone_page(body,waba_id=waba_id,verified=verified)
            for choice in page:
                if choice.phone_number_id in seen_phones:
                    raise ProtocolError('provider_response_invalid')
                seen_phones.add(choice.phone_number_id); choices.append(choice)
            if after is None:
                return tuple(choices)
            if after in seen_cursors:
                raise ProtocolError('provider_response_invalid')
            seen_cursors.add(after)
        raise ProtocolError('provider_page_limit')

    async def subscribe(self, token, waba_id):
        body=await self.transport.request(GraphRequest('POST','/v26.0/'+waba_id+'/subscribed_apps',token=token,body={}))
        if body!={'success':True} or type(body['success']) is not bool:
            raise ProtocolError('provider_response_invalid')

    async def register(self, token, phone_id, pin):
        body=await self.transport.request(GraphRequest('POST','/v26.0/'+phone_id+'/register',token=token,
            body={'messaging_product':'whatsapp','pin':pin}))
        if body!={'success':True} or type(body['success']) is not bool:
            raise ProtocolError('provider_response_invalid')
