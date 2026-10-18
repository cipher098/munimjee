#!/usr/bin/env python3
"""Run one disposable, network-disabled container; no DB or provider calls."""
import argparse
import json
import re
import subprocess
import uuid
import tempfile
from pathlib import Path
from v1_runtime_package import create_context, ROOT

CHILD = r'''
import os, socket
mode = os.environ['SMOKE_MODE']
original_connect = socket.socket.connect
attempts = []
def no_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        attempts.append('connect'); raise AssertionError('Network I/O forbidden in image smoke')
    return original_connect(self, address)
def no_dns(*a, **k):
    attempts.append('dns'); raise AssertionError('DNS forbidden in image smoke')
socket.socket.connect = no_connect
socket.getaddrinfo = no_dns
if mode == 'missing':
    os.environ['V1_STOREFRONT_ENABLED']='true'
    os.environ['V1_STOREFRONT_ASSETS_DIR']='/missing-storefront-runtime'
    try:
        import app.main
    except RuntimeError as error:
        assert 'runtime assets are missing' in str(error)
    else: raise AssertionError('Missing runtime did not fail closed')
    assert attempts == []
    print('PASS missing assets refuse startup'); raise SystemExit(0)
if mode=='off':
    os.environ.pop('V1_STOREFRONT_ENABLED',None)
    os.environ.pop('PUBLIC_BASE_URL',None)
    os.environ['V1_STOREFRONT_ASSETS_DIR']='/missing-ignored-while-disabled'
else:
    os.environ['V1_STOREFRONT_ENABLED']='true'
from app.main import app
from fastapi.testclient import TestClient
from pathlib import Path
assert not Path('/app/.env').exists()
for forbidden in ('tests','node_modules','artifacts','design','keys'):
    assert not Path('/app',forbidden).exists()
# Existing route imports create empty upload subdirectories; no source data
# may be packaged or appear during these static-only checks.
assert not any(path.is_file() for path in Path('/app/uploads').rglob('*'))
import hashlib, json
manifest=json.loads(Path('/opt/munimjee/runtime-manifest.json').read_text())
assert manifest['format']=='munimjee.v1.runtime-package.v1'
for name,digest in manifest['files'].items():
    parts=Path(name).parts
    assert not any(part in ('tests','uploads','node_modules','artifacts','design','keys') or part.startswith('.env') for part in parts)
    if name=='Dockerfile': continue  # recipe is hashed, never copied into runtime
    target=Path('/opt/munimjee')/name if name.startswith('storefront-src/') else Path('/app')/(name[8:] if name.startswith('backend/') else name)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
assert len(list(Path('/opt/munimjee/storefront-src').iterdir()))==13
assert not any(line.startswith(('pytest','vcrpy')) for line in Path('/app/requirements.txt').read_text().splitlines())
paths={route.path for route in app.routes}
with TestClient(app, base_url='https://configured.example') as client:
    assert client.get('/health').json()=={'status':'ok'}
    if mode == 'off':
        assert not any(path.startswith(('/stores','/storefront-assets')) for path in paths)
        assert client.get('/storefront-assets/src/live-entry.js').status_code==404
    else:
        assert '/stores/{slug}' in paths and '/stores/{slug}/orders/{order_id}' in paths
        for asset in ('live-entry.js','canonical-contract.js','order-status.js','payment-handoff.js','styles.css','live.css'):
            response=client.get('/storefront-assets/src/'+asset)
            assert response.status_code==200 and len(response.content)>10
        for path in ('/storefront-assets/tests/fixtures.js','/storefront-assets/node_modules/package.json',
                     '/storefront-assets/package.json','/storefront-assets/src/fixtures.js',
                     '/storefront-assets/src/app.js','/storefront-assets/src/../requirements.txt',
                     '/storefront-assets/src/.env','/static/.env','/static/keys/private.pem'):
            assert client.get(path).status_code==404, path
        for asset in ('parcel_tracking.js','parcel_scanner.js','parcel_barcode_reader.js','parcel_zxing_reader.wasm','parcel_scanner_LICENSE.txt',
                      'import_workspace.html','import_workspace.js','import_workspace.css',
                      'theme_settings.html','theme_settings.js','theme_settings.css',
                      'assistance.html','assistance.js','assistance.css',
                      'payment_settings.html','payment_settings.js','payment_settings.css'):
            response=client.get('/static/'+asset)
            assert response.status_code==200 and len(response.content)>10
        # Private shell requires no DB, contains no order facts or capability.
        response=client.get('/stores/synthetic/orders/66666666-6666-4666-8666-666666666601')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert response.headers['x-robots-tag']=='noindex, nofollow'
        assert 'access_token' not in response.text
assert attempts == []
print('PASS '+mode+' startup/static/private paths; zero DNS/network attempts')
'''
RUNNER = 'import os,subprocess,sys\n' + '\n'.join(
    f"subprocess.run([sys.executable,'-c',{CHILD!r}],check=True,env={{**os.environ,'SMOKE_MODE':{mode!r}}})"
    for mode in ('off','enabled','missing'))



def cleanup_created_container(cidfile):
    # No cleanup by name: a failed create/name collision must never target a
    # pre-existing container. Docker alone writes this invocation's CID file.
    if not cidfile.exists():
        return
    cid=cidfile.read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{64}',cid):
        raise RuntimeError('Invalid smoke container identity; cleanup withheld')
    subprocess.run(['docker','rm','--force',cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    remaining=subprocess.run(['docker','ps','-a','--no-trunc','--filter','id='+cid,'--format','{{.ID}}'],
                             capture_output=True,text=True,check=True)
    if remaining.stdout.strip():
        raise RuntimeError('Smoke container cleanup could not be verified')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'munimjee-v1-runtime:[a-z0-9][a-z0-9_.-]{0,100}',args.image):
        parser.error('Expected the dedicated local V1 image tag')
    name='munimjee-v1-smoke-'+uuid.uuid4().hex[:12]
    command=['docker','run','--rm','--name',name,'--network','none','--cpus','1','--memory','768m',
             '--pids-limit','256','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--tmpfs','/tmp:rw,noexec,nosuid,size=16m',
             '--tmpfs','/app/uploads:rw,noexec,nosuid,size=1m,uid=10001,gid=10001',
             '--env','SECRET_KEY=v1-package-synthetic-only','--env','META_VERIFY_TOKEN=synthetic-only',
             '--env','ANTHROPIC_API_KEY=sk-ant-synthetic-not-real',
             '--env','DATABASE_URL=postgresql+asyncpg://unused:unused@127.0.0.1:1/unused',
             '--env','REDIS_URL=redis://127.0.0.1:1/0','--env','AWS_EC2_METADATA_DISABLED=true',
             '--env','APP_ENV=test','--env','PUBLIC_BASE_URL=https://configured.example',
             '--entrypoint','python','-i',args.image,'-']
    with tempfile.TemporaryDirectory(prefix='munimjee-v1-smoke-context-') as temporary:
        expected=create_context(ROOT,Path(temporary)/'context')['files']
        cidfile=Path(temporary)/'container.cid'
        command[2:2]=['--cidfile',str(cidfile)]
        manifest_check="import json; assert json.load(open('/opt/munimjee/runtime-manifest.json'))['files']=="+repr(expected)+"\n"
        try:
            subprocess.run(command,input=manifest_check+RUNNER,text=True,check=True,timeout=90)
        finally:
            cleanup_created_container(cidfile)
    info=json.loads(subprocess.run(['docker','image','inspect',args.image],capture_output=True,text=True,check=True).stdout)[0]
    print(json.dumps({'image_id':info['Id'],'size_bytes':info['Size'],'checks':'off/enabled/missing; no network or DB',
                      'container_removed':True}))
if __name__=='__main__':main()
