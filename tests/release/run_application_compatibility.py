"""Opt-in packaged HTTP compatibility probe on the owned restored PG16 target.

No restore/reset/downgrade and no old-package writes. Current package creates a
real native COD order; old/current packages read it while full DB hashes stay
unchanged. This does not authorize old writers or production rollback.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import v1_release_rehearsal as rehearsal
from smoke_v1_runtime import cleanup_created_container

GUEST = r'''
import json,logging,os,socket
logging.disable(logging.CRITICAL)
assert os.getuid()==10001
original_connect,original_connect_ex,original_dns=socket.socket.connect,socket.socket.connect_ex,socket.getaddrinfo
blocked=[]
def connect(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6) and (not isinstance(address,tuple) or address[:2]!=('127.0.0.1',5432)):
        blocked.append('connect');raise AssertionError('Only allocated PG socket permitted')
    return original_connect(self,address)
def dns(host,port,*args,**kwargs):
    if host!='127.0.0.1' or int(port)!=5432:
        blocked.append('dns');raise AssertionError('Only allocated PG resolution permitted')
    return original_dns(host,port,*args,**kwargs)
def connect_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6) and (not isinstance(address,tuple) or address[:2]!=('127.0.0.1',5432)):
        blocked.append('connect_ex');raise AssertionError('Only allocated PG socket permitted')
    return original_connect_ex(self,address)
socket.socket.connect,socket.socket.connect_ex,socket.getaddrinfo=connect,connect_ex,dns
from pydantic_settings.sources import DotEnvSettingsSource
DotEnvSettingsSource._read_env_files=lambda self:{}
DotEnvSettingsSource.__call__=lambda self:{}
from app.main import app
from fastapi.testclient import TestClient
origin='http://127.0.0.1:8166'
with TestClient(app,base_url=origin) as client:
    if MODE=='create':
        def request(path,method='GET',body=None,headers=None):
            result=client.request(method,path,json=body,headers=headers or {})
            assert result.status_code in (200,201),('HTTP status',result.status_code,path)
            return result.json()
        request('/api/v1/auth/signup','POST',{'email':'packaged-compatibility@example.com','password':'synthetic-package-password','business_name':'Synthetic Package Compatibility'},{'Origin':origin})
        session=request('/api/v1/auth/session');bid=session['businesses'][0]['id']
        headers={'Origin':origin,'X-CSRF-Token':session['csrf_token']}
        base='/api/v1/businesses/'+bid+'/catalogue';slug='synthetic-package-compatibility'
        request(base+'/storefront','PUT',{'name':'Synthetic Package Compatibility','slug':slug,'shipping_fee':50,'published':True,'cod_enabled':True},headers)
        draft=request(base+'/products','POST',{'idempotency_key':'bb444444-4444-4444-8444-444444444441','seller_reviewed':True,'name':'Synthetic Compatibility Product','description':'Human-reviewed test facts','photo_urls':[],'skus':[{'options':{},'price_minor':1250,'currency':'INR','stock_available':5,'active':True}]},headers)
        pid=draft['product']['product_id'];sku=draft['skus'][0]['sku_id']
        request(base+'/products/'+pid+'/activate','POST',{'seller_reviewed':True,'expected_mapping_revision':draft['mapping_revision'],'expected_legacy_fingerprint':draft['legacy_fingerprint']},headers)
        request(base+'/checkout-policy','PUT',{'checkout_enabled':True},headers)
        body={'idempotency_key':'bb444444-4444-4444-8444-444444444442','customer':{'name':'Synthetic Package Buyer','phone':'+919000000001'},'address':{'line1':'Synthetic test lane','city':'Bengaluru','state':'Karnataka','postal_code':'560001','country':'IN'},'items':[{'sku_id':sku,'quantity':1}],'payment_method':'cod','whatsapp_updates_opt_in':False}
        order=request('/api/v1/storefronts/'+slug+'/checkout','POST',body)
        assert order['payment_status']=='pending' and order['total']==1300
        result={'business_id':bid,'product_id':pid,'sku_id':sku,'slug':slug,'order_id':order['id'],'order_token':order['access_token'],'cookies':dict(client.cookies.items())}
    else:
        client.cookies.update(CONTEXT['cookies'])
        session=client.get('/api/v1/auth/session');assert session.status_code==200
        assert any(b['id']==CONTEXT['business_id'] for b in session.json()['businesses'])
        orders=client.get('/api/v1/businesses/'+CONTEXT['business_id']+'/orders');assert orders.status_code==200
        assert any(row['id']==CONTEXT['order_id'] for row in orders.json()['items'])
        order=client.get('/api/v1/storefronts/'+CONTEXT['slug']+'/orders/'+CONTEXT['order_id'],headers={'Authorization':'Bearer '+CONTEXT['order_token']})
        assert order.status_code==200 and order.json()['payment_status']=='pending' and order.json()['total']==1300
        product=client.get('/api/v1/storefronts/'+CONTEXT['slug']+'/products/'+CONTEXT['product_id'])
        assert product.status_code==200 and product.json()['skus'][0]['stock_available']==4
        result={'native_session':True,'order_read':True,'post_cutover_order_preserved':True,'sku_stock_available':4,'payment_status':'pending','no_old_write':True}
assert blocked==[]
result['runtime_manifest_source']=json.load(open('/opt/munimjee/runtime-manifest.json'))['source_revision']
print(json.dumps(result))
'''


def guest(image, pg_container, target, mode, context=None):
    rehearsal.require(re.fullmatch(r'sha256:[a-f0-9]{64}',image), 'Immutable image ID required')
    inspection=json.loads(subprocess.check_output(['docker','image','inspect',image],timeout=10))[0]
    rehearsal.require(inspection['Id']==image and inspection['Architecture']=='arm64'
                      and inspection['Config']['User']=='10001:10001','Reviewed nonroot native image required')
    parsed=urlsplit(target.url)
    database=f'postgresql+asyncpg://{parsed.username}:{parsed.password}@127.0.0.1:5432/{target.database}'
    with tempfile.TemporaryDirectory(prefix='munimjee-package-probe-') as temporary:
        cid=Path(temporary)/'container.cid'
        command=['docker','run','--rm','--cidfile',str(cid),'--network','container:'+pg_container,
                 '--cpus','1','--memory','768m','--pids-limit','256','--read-only','--cap-drop','ALL',
                 '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=16m',
                 '--tmpfs','/app/uploads:rw,noexec,nosuid,size=1m,uid=10001,gid=10001']
        environment={'APP_ENV':'test','DATABASE_URL':database,'SECRET_KEY':'synthetic-package-compatibility-key',
                     'META_VERIFY_TOKEN':'synthetic-only','ANTHROPIC_API_KEY':'sk-ant-synthetic-not-real',
                     'REDIS_URL':'redis://127.0.0.1:1/0','AWS_EC2_METADATA_DISABLED':'true',
                     'V1_AUTH_ENABLED':'true','V1_ENFORCE_LEGACY_ACCESS':'true',
                     'V1_STOREFRONT_ENABLED':'false','PUBLIC_BASE_URL':'http://127.0.0.1:8166'}
        # Child secrets/configuration stay in private stdin, never Docker argv.
        code='import os\nos.environ.update('+repr(environment)+')\nMODE='+repr(mode)+'\nCONTEXT='+repr(context)+'\n'+GUEST
        command+=['--entrypoint','python','-i',image,'-']
        try:
            result=subprocess.run(command,input=code,text=True,capture_output=True,timeout=90,check=True)
            return json.loads(result.stdout)
        finally:
            cleanup_created_container(cid)


async def run(args):
    source,target=rehearsal.targets(args.source_lane,args.target_lane,os.environ)
    rehearsal.ownership(args.attestation,source,target)
    rehearsal.require(args.pg_container=='munimjee-v1-wave2-pg16','Only dedicated local PG container allowed')
    info=json.loads(subprocess.check_output(['docker','inspect',args.pg_container],timeout=10))[0]
    ports=info['NetworkSettings']['Ports'].get('5432/tcp') or []
    rehearsal.require(any(str(target.port)==port['HostPort'] for port in ports),'PG namespace must match allocated port')
    rehearsal.no_symlinks(args.output)
    rehearsal.require(args.output.parent.is_dir() and not args.output.exists(),'New private result file required')
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    _,acquire=rehearsal.p01()
    engines=[create_async_engine(item.url,poolclass=NullPool) for item in (source,target)]
    try:
        async with AsyncExitStack() as stack:
            connections=[await stack.enter_async_context(engine.connect())for engine in engines]
            for connection,item in zip(connections,(source,target)):
                await acquire(connection,item);await connection.commit();await rehearsal.pg16(connection)
            src,dst=connections
            original_source=await rehearsal.snapshot(src);original_target=await rehearsal.snapshot(dst)
            rehearsal.require(original_source['totals']['orders']==2 and original_target['totals']['orders']==3,
                              'Exact fresh restored fixture required; do not reuse partially written target')
            await src.commit();await dst.commit()
            context=await rehearsal.owned_call(guest,args.current_image,args.pg_container,target,'create')
            after_creation=await rehearsal.snapshot(dst);await dst.commit()
            rehearsal.require(after_creation['totals']['orders']==4,'Current HTTP writer must create one post-cutover order')
            old_result=await rehearsal.owned_call(guest,args.old_image,args.pg_container,target,'read',context)
            rehearsal.require(await rehearsal.snapshot(dst)==after_creation,'Old read-only package changed persisted facts')
            await dst.commit()
            current_result=await rehearsal.owned_call(guest,args.current_image,args.pg_container,target,'read',context)
            rehearsal.require(await rehearsal.snapshot(dst)==after_creation,'Forward current read changed persisted facts')
            rehearsal.require(await rehearsal.snapshot(src)==original_source,'Source fixture changed')
            evidence={'kind':'actual-packaged-ASGI-HTTP-read-compatibility','head':rehearsal.repo_head(),
                      'old_image':args.old_image,'current_image':args.current_image,'old_result':old_result,
                      'current_result':current_result,'after_creation':after_creation,'new_order_created_by':'Actual current native signup/catalogue activation/COD checkout APIs',
                      'provider_network':'Only exact allocated PG socket permitted inside each child',
                      'old_writers_approved':False,'browser_or_production_routing_proof':False,'schema_downgrade':False}
            # Secret context stays memory-only; only aggregate/hashes/projections persist.
            with os.fdopen(os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as out:
                json.dump(evidence,out,indent=2);out.write('\n')
            print('PASS actual packaged current-create -> old-read -> current-read; all post-create hashes unchanged')
    finally:
        for engine in engines:await engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-lane','target-lane','old-image','current-image','pg-container'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--attestation',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    try:
        asyncio.run(run(parser.parse_args()))
    except (Exception,KeyboardInterrupt):
        print('Packaged compatibility probe failed; private inputs and child output withheld',file=sys.stderr)
        raise SystemExit(1) from None
