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
           'backend/static/v1_client.js','deploy/v1/Dockerfile']
    names += ['frontend/storefront/src/'+name for name in package.STOREFRONT]
    for name in names:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic runtime\n')
    (root/'backend/requirements.txt').write_text('fastapi==0.111.0\npytest==8.2.0\npytest-asyncio==0.23.6\nvcrpy==6.0.1\n')
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
    assert len(list((output/'storefront-src').iterdir()))==11
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

@pytest.mark.parametrize('bad',['--extra-index-url https://secret.example','private @ https://secret.example/private.whl','-r runtime.env','./private.whl'])
def test_dependency_paths_urls_and_options_never_enter_context(source,tmp_path,bad):
    (source/'backend/requirements.txt').write_text(bad+'\n')
    with pytest.raises(ValueError,match='pinned index'):package.create_context(source,tmp_path/'context')


def test_requirements_symlink_cannot_read_outside_the_source(source,tmp_path):
    external=tmp_path/'outside.txt';external.write_text('private-package==1.0.0\n')
    requirements=source/'backend/requirements.txt';requirements.unlink();requirements.symlink_to(external);stage(source)
    with pytest.raises(ValueError,match='symlinks'):package.create_context(source,tmp_path/'context')
