"""Signed exact-origin machine transport. Browser input never selects an origin/key."""
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4
import httpx
from fastapi import HTTPException
from app.config import settings

COURIERS={'tirupati':'Tirupati','aakash_ganga':'Aakash Ganga','skyking':'Skyking','shree_maruti':'Shree Maruti','dhl':'DHL Express','fedex':'FedEx','ups':'UPS'}

class ConnectorUnavailable(RuntimeError):
    pass


def normalize(courier,awb):
    import re
    if courier not in COURIERS or not isinstance(awb,str):
        raise HTTPException(422,'Select the courier printed on the parcel label')
    value=''.join(awb.split()).upper()
    if not re.fullmatch('[A-Z0-9-]{6,35}',value):
        raise HTTPException(422,'Enter the tracking number as printed on the label')
    return value


def configuration(connector):
    try:
        registry=json.loads(settings.V1_PARCEL_CONNECTORS_JSON or '{}')
        allowed=settings.V1_PARCEL_ALLOWED_ORIGINS
        if not settings.V1_PARCEL_ENABLED:raise ValueError()
        value=registry[connector.credential_ref]
        origin=connector.origin
        parsed=urlsplit(origin)
        local=settings.APP_ENV=='test' and parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port==8155
        if (not connector.enabled or value.get('enabled') is not True or value['origin']!=origin or
            value['business_id']!=str(connector.business_id) or value['instance_id']!=str(connector.instance_id) or
            origin not in allowed or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or
            (parsed.scheme!='https' and not local) or (not local and parsed.port not in (None,443)) or
            not isinstance(value['secret'],str) or len(value['secret'])<32):
            raise ValueError()
        import re
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',value['key_id']):raise ValueError()
        return value
    except (KeyError,ValueError,TypeError,AttributeError):
        raise ConnectorUnavailable('connector_unconfigured') from None


def timestamp(value):
    from datetime import datetime,timezone
    if value is None:return None
    if not isinstance(value,str) or len(value)>100:return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except ValueError:return None


def validate_snapshot(value,connector,*,remote_id=None,courier=None,awb=None):
    try:
        if value['contract_version']!='parcel.integration.v1' or value['tenant_id']!=str(connector.business_id) or value['instance_id']!=str(connector.instance_id):raise ValueError()
        if type(value['revision']) is not int or value['revision']<1:raise ValueError()
        shipment=value['shipment']
        if str(UUID(shipment['id']))!=shipment['id'] or (remote_id and shipment['id']!=str(remote_id)):raise ValueError()
        if shipment['courier_id'] not in COURIERS or normalize(shipment['courier_id'],shipment['awb'])!=shipment['awb']:raise ValueError()
        if (courier and courier!=shipment['courier_id']) or (awb and awb!=shipment['awb']):raise ValueError()
        if type(shipment['revoked']) is not bool or not isinstance(shipment['status'],str) or len(shipment['status'])>120 or not isinstance(shipment['events'],list) or len(shipment['events'])>200:raise ValueError()
        if shipment['error_code'] not in (None,'courier_update_unavailable'):raise ValueError()
        # Only documented public fields cross into local observations; contacts,
        # staff tokens, free-text references and public capabilities are ignored.
        return {'revision':value['revision'],'shipment':{k:shipment.get(k) for k in ('id','courier_id','awb','status','events','eta','checked_at','attempted_at','error_code','revoked')}}
    except (KeyError,ValueError,TypeError,HTTPException):
        raise ConnectorUnavailable('invalid_snapshot') from None


class ParcelAdapter:
    def __init__(self,connector,*,transport=None):
        self.connector=connector;self.credentials=configuration(connector);self.transport=transport

    async def request(self,method,path,body=None):
        encoded='' if body is None else json.dumps(body,sort_keys=True,separators=(',',':'))
        stamp=str(int(time.time()));request_id=str(uuid4())
        signing='\n'.join((method,path,hashlib.sha256(encoded.encode()).hexdigest(),stamp,request_id))
        headers={'X-Parcel-Key-Id':self.credentials['key_id'],'X-Parcel-Timestamp':stamp,'X-Parcel-Request-Id':request_id,
            'X-Parcel-Signature':hmac.new(self.credentials['secret'].encode(),signing.encode(),hashlib.sha256).hexdigest(),
            'Content-Type':'application/json','Accept':'application/json'}
        try:
            async with httpx.AsyncClient(transport=self.transport,trust_env=False,follow_redirects=False,timeout=25) as client:
                async with client.stream(method,self.connector.origin+path,headers=headers,content=encoded) as response:
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>256000:raise ConnectorUnavailable('invalid_snapshot')
                    if response.status_code not in (200,201):raise ConnectorUnavailable('connector_request_unconfirmed')
                    return json.loads(content)
        except (httpx.HTTPError,ValueError):
            raise ConnectorUnavailable('connector_request_unconfirmed') from None

    async def resolve(self,courier,awb):
        result=await self.request('GET','/integration/v1/shipments:resolve?'+urlencode({'awb':awb,'courier_id':courier}))
        if not isinstance(result,dict) or result.get('state') not in {'existing','not_found','manual_review'}:raise ConnectorUnavailable('invalid_snapshot')
        if result['state']=='existing':result['snapshot']=validate_snapshot(result.get('snapshot'),self.connector,courier=courier,awb=awb)
        return result

    async def ensure(self,key,courier,awb):
        return validate_snapshot(await self.request('POST','/integration/v1/shipments:ensure',{'command_id':str(key),'courier_id':courier,'awb':awb}),self.connector,courier=courier,awb=awb)

    async def read(self,remote_id,*,refresh=False):
        path='/integration/v1/shipments/'+str(remote_id)+(':refresh' if refresh else '')
        return validate_snapshot(await self.request('POST' if refresh else 'GET',path,{} if refresh else None),self.connector,remote_id=remote_id)
