"""Pure allowlisted context checks; never Docker, DB or provider operations."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=spec_from_file_location('v1_runtime_package',ROOT/'scripts/v1_runtime_package.py')
package=module_from_spec(spec);spec.loader.exec_module(package)

@pytest.fixture
def source(tmp_path):
    root=tmp_path/'source';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
    names=['backend/requirements.txt','backend/alembic.ini','backend/app/main.py',
           'backend/alembic/env.py','backend/alembic/versions/0046.py',
           'backend/static/v1_client.js','deploy/v1/Dockerfile','deploy/v1/runtime.in','deploy/v1/runtime.lock']
    names += ['backend/static/'+name for name in package.STATIC]
    names += ['frontend/storefront/src/'+name for name in package.STOREFRONT]
    for name in names:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic runtime\n')
    (root/'backend/requirements.txt').write_text('fastapi==0.111.0\npytest==8.2.0\npytest-asyncio==0.23.6\nvcrpy==6.0.1\n')
    (root/'deploy/v1/runtime.in').write_text('fastapi==0.111.0\n')
    (root/'deploy/v1/runtime.lock').write_text('fastapi==0.111.0 --hash=sha256:'+'a'*64+'\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Synthetic','-c','user.email=test@example.invalid','commit','-qm','Synthetic fixture'],check=True)
    return root


def stage(root):subprocess.run(['git','-C',str(root),'add','.'],check=True)


def test_context_excludes_tracked_and_untracked_sensitive_sentinels(source,tmp_path):
    forbidden=['backend/.env','backend/.env.production','backend/uploads/customer.jpg',
       'backend/tests/secret.py','backend/app/keys/credential.py','backend/app/config.py.bak',
       'backend/app/scripts/capture.py','backend/static/design.html','backend/static/private.js','backend/static/secret.pem','frontend/storefront/src/fixtures.js',
       'frontend/storefront/src/app.js','frontend/storefront/src/tests/sentinel.js',
       'frontend/storefront/node_modules/secret.js','artifacts/private.txt','design/private.html']
    for name in forbidden:
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('SYNTHETIC-DO-NOT-PACKAGE-SENTINEL')
    stage(source)
    output=tmp_path/'context';manifest=package.create_context(source,output)
    assert len(list((output/'storefront-src').iterdir()))==13
    assert (output/'storefront-src/published-design.js').is_file()
    assert (output/'storefront-src/payment-handoff.js').is_file()
    for prefix in ('import_workspace','theme_settings','assistance','payment_settings','support_grants','analytics_v1','customer_links'):
        for suffix in ('html','css','js'):
            assert (output/f'backend/static/{prefix}.{suffix}').is_file()
    assert (output/'backend/alembic/versions/0046.py').is_file()
    assert manifest['excluded_dev_requirements']==['pytest','pytest-asyncio','vcrpy']
    assert (output/'requirements.txt').read_text()=='fastapi==0.111.0\n'
    assert all('SYNTHETIC-DO-NOT-PACKAGE-SENTINEL' not in path.read_text() for path in output.rglob('*') if path.is_file())
    assert json.loads((output/'runtime-manifest.json').read_text())==manifest


def test_context_rejects_symlink_reads_and_preserves_existing_destination(source,tmp_path):
    external=tmp_path/'secret.py';external.write_text('SYNTHETIC-SYMLINK-SENTINEL')
    (source/'backend/app/escape.py').symlink_to(external);stage(source)
    with pytest.raises(ValueError,match='symlinks'):package.create_context(source,tmp_path/'context')
    existing=tmp_path/'existing';existing.mkdir();sentinel=existing/'keep';sentinel.write_text('keep')
    with pytest.raises(ValueError,match='already exist'):package.create_context(source,existing)
    assert sentinel.read_text()=='keep'


@pytest.mark.parametrize('missing',['import_workspace.js','theme_settings.html','assistance.js','payment_settings.html','support_grants.js','analytics_v1.html','customer_links.js'])
def test_missing_native_runtime_assets_refuse_packaging(source,tmp_path,missing):
    (source/'backend/static'/missing).unlink()
    subprocess.run(['git','-C',str(source),'add','-u'],check=True)
    with pytest.raises(ValueError,match='Required tracked runtime files'):
        package.create_context(source,tmp_path/'context')

@pytest.mark.parametrize('bad',['--extra-index-url https://secret.example','private @ https://secret.example/private.whl','-r runtime.env','./private.whl'])
def test_dependency_paths_urls_and_options_never_enter_context(source,tmp_path,bad):
    (source/'backend/requirements.txt').write_text(bad+'\n')
    with pytest.raises(ValueError,match='pinned index'):package.create_context(source,tmp_path/'context')


def test_requirements_symlink_cannot_read_outside_the_source(source,tmp_path):
    external=tmp_path/'outside.txt';external.write_text('private-package==1.0.0\n')
    requirements=source/'backend/requirements.txt';requirements.unlink();requirements.symlink_to(external);stage(source)
    with pytest.raises(ValueError,match='symlinks'):package.create_context(source,tmp_path/'context')


def test_smoke_cleanup_only_uses_docker_created_cid_not_a_reused_name(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec=spec_from_file_location('smoke_v1_runtime',ROOT/'scripts/smoke_v1_runtime.py')
    smoke=module_from_spec(spec);spec.loader.exec_module(smoke)
    calls=[]
    def command(args,**kwargs):
        calls.append(args);return subprocess.CompletedProcess(args,0,stdout='')
    monkeypatch.setattr(smoke.subprocess,'run',command)
    cidfile=tmp_path/'container.cid'
    smoke.cleanup_created_container(cidfile);assert calls==[]
    cidfile.write_text('pre-existing-container-name')
    with pytest.raises(RuntimeError,match='Invalid smoke container'):smoke.cleanup_created_container(cidfile)
    assert calls==[]
    cid='a'*64;cidfile.write_text(cid)
    smoke.cleanup_created_container(cidfile)
    assert calls[0]==['docker','rm','--force',cid]
    assert calls[1][calls[1].index('--filter')+1]=='id='+cid

@pytest.mark.parametrize('failure',['daemon_unavailable','container_still_present'])
def test_smoke_never_claims_verified_cleanup_when_docker_fails_or_container_remains(tmp_path,monkeypatch,failure):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec=spec_from_file_location('smoke_v1_runtime',ROOT/'scripts/smoke_v1_runtime.py')
    smoke=module_from_spec(spec);spec.loader.exec_module(smoke)
    cidfile=tmp_path/'container.cid';cidfile.write_text('a'*64)
    def command(args,**kwargs):
        if args[1]=='ps':
            if failure=='daemon_unavailable':raise subprocess.CalledProcessError(1,args)
            return subprocess.CompletedProcess(args,0,stdout='a'*64+'\n')
        return subprocess.CompletedProcess(args,0,stdout='')
    monkeypatch.setattr(smoke.subprocess,'run',command)
    with pytest.raises((RuntimeError,subprocess.CalledProcessError)):
        smoke.cleanup_created_container(cidfile)


def test_context_and_archive_are_deterministic_across_mtime_umask(source,tmp_path):
    import os
    import tarfile
    first=tmp_path/'first';second=tmp_path/'second'
    one=package.create_context(source,first)
    for path in source.rglob('*'):
        if path.is_file() and '.git' not in path.parts:os.utime(path,(1700000000,1700000000))
    prior=os.umask(0o077)
    try:two=package.create_context(source,second)
    finally:os.umask(prior)
    assert one==two
    left=tmp_path/'first.tar';right=tmp_path/'second.tar'
    assert package.write_archive(first,left)==package.write_archive(second,right)
    assert left.read_bytes()==right.read_bytes()
    with tarfile.open(left) as archive:
        for info in archive.getmembers():
            assert (info.uid,info.gid,info.mtime,info.uname,info.gname)==(0,0,0,'','')
            assert info.mode==(0o755 if info.isdir() else 0o644)
    with pytest.raises(FileExistsError):package.write_archive(first,left)


def test_source_revision_alone_does_not_hide_dirty_bytes(source,tmp_path):
    one=package.create_context(source,tmp_path/'first')
    (source/'backend/app/main.py').write_text('# changed tracked source\n')
    two=package.create_context(source,tmp_path/'second')
    assert one['source_revision']==two['source_revision']
    assert one['content_sha256']!=two['content_sha256']
    assert one['source_files']!=two['source_files']


@pytest.mark.parametrize('bad',[
    'fastapi==0.111.0',
    'fastapi==0.112.0 --hash=sha256:'+'a'*64,
    'fastapi @ https://example.test/pkg.whl --hash=sha256:'+'a'*64,
    '--extra-index-url https://example.test/simple',
    'pytest==8.2.0 --hash=sha256:'+'a'*64,
    'fastapi==0.111.0 --hash=sha256:short',
    'fastapi==0.111.0 --hash=sha256:'+'a'*64+' \\',
])
def test_runtime_lock_refuses_unhashed_unpinned_or_development_input(source,tmp_path,bad):
    (source/'deploy/v1/runtime.lock').write_text(bad+'\n')
    with pytest.raises(ValueError,match='lock'):package.create_context(source,tmp_path/'context')
    assert not (tmp_path/'context').exists()


def test_direct_runtime_manifest_must_match_incumbent_backend_pins(source,tmp_path):
    (source/'deploy/v1/runtime.in').write_text('fastapi==0.112.0\n')
    with pytest.raises(ValueError,match='direct dependencies'):package.create_context(source,tmp_path/'context')


@pytest.mark.parametrize('missing',['parcel_zxing_reader.wasm','parcel_scanner_LICENSE.txt','onboarding.html'])
def test_all_allowlisted_native_assets_are_required(source,tmp_path,missing):
    (source/'backend/static'/missing).unlink();stage(source)
    with pytest.raises(ValueError,match='Required tracked runtime'):package.create_context(source,tmp_path/'context')


def test_release_archives_and_builds_refuse_dirty_runtime_while_context_marks_it(source,tmp_path):
    package.require_clean_runtime(source)
    (source/'backend/app/main.py').write_text('# dirty release input\n')
    with pytest.raises(ValueError,match='clean tracked runtime'):
        package.require_clean_runtime(source)
    assert package.create_context(source,tmp_path/'context')['source_dirty'] is True
    stage(source)
    with pytest.raises(ValueError,match='clean tracked runtime'):
        package.require_clean_runtime(source)
