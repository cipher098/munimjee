"""Release safety invariants: pure and synthetic; no Docker/database/network calls."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[2]


def workflow():
    return yaml.load((ROOT/'.github/workflows/tests.yml').read_text(),Loader=yaml.BaseLoader)


def test_workflow_limits_execution_to_hosted_readonly_no_secret_jobs():
    config=workflow()
    assert config['permissions']=={'contents':'read'}
    assert set(config['on'])=={'pull_request','push','workflow_dispatch'}
    for job in config['jobs'].values():
        assert 0<int(job['timeout-minutes'])<=40
        runners=job.get('strategy',{}).get('matrix',{}).get('runner',[job['runs-on']])
        assert all(runner in {'ubuntu-24.04','ubuntu-24.04-arm'} for runner in runners)
        for step in job['steps']:
            if 'uses' in step:
                assert re.fullmatch(r'actions/(checkout|setup-python|setup-node|upload-artifact)@[0-9a-f]{40}',step['uses'])
                if step['uses'].startswith('actions/checkout@'):
                    assert step['with']['persist-credentials']=='false'
    text=(ROOT/'.github/workflows/tests.yml').read_text()
    for forbidden in ('secrets.','pull_request_target','self-hosted','id-token:','git push','docker push','--privileged'):
        assert forbidden not in text
    postgres=config['jobs']['migrated-postgres']['services']['postgres']
    assert re.fullmatch(r'postgres:16-bookworm@sha256:[a-f0-9]{64}',postgres['image'])
    assert postgres['env']['POSTGRES_DB']=='munimjee_test_ci'
    env=config['jobs']['migrated-postgres']['env']
    assert env['TEST_LANE']=='ci' and env['TEST_DB_RESET']=='1'
    for step in config['jobs']['migrated-postgres']['steps']:
        if step.get('name','') in {'Required actual Alembic and held P01 lease proof','Full backend regression using actual migrations and guarded resets','Actual mounted native review, persisted themes and COD journey'}:
            url=step['env']['TEST_DATABASE_URL']
            assert url.endswith('/munimjee_test_ci') and '@127.0.0.1:' in url
            assert "${{ job.services.postgres.ports['5432'] }}" in url


@pytest.mark.parametrize('result',['pass','skipped','failure','error','missing','duplicate'])
def test_ci_junit_guard_rejects_skipped_missing_or_failed_actual_migration(tmp_path,result):
    step=next(step for step in workflow()['jobs']['migrated-postgres']['steps'] if 'Required actual' in step.get('name',''))
    command=shlex.split(step['run'].splitlines()[1])
    assert command[:2]==['python','-c']
    case='<testcase name="test_actual_migrated_schema_and_database_lease">'+('' if result in ('pass','duplicate') else '<'+result+'/>')+'</testcase>'
    if result=='missing':case=''
    if result=='duplicate':case+=case
    (tmp_path/'p01-required.xml').write_text('<testsuites><testsuite>'+case+'</testsuite></testsuites>')
    process=subprocess.run([sys.executable,*command[1:]],env={**os.environ,'RUNNER_TEMP':str(tmp_path)},capture_output=True,text=True)
    assert (process.returncode==0)==(result=='pass')


def test_runtime_recipe_uses_immutable_base_and_hash_checked_binary_closure():
    recipe=(ROOT/'deploy/v1/Dockerfile').read_text()
    assert re.search(r'^FROM python:3\.11-slim-bookworm@sha256:[a-f0-9]{64}$',recipe,re.M)
    assert '--require-hashes -r runtime.lock' in recipe and '--only-binary=:all:' in recipe
    assert 'python -m pip check' in recipe
    assert '\nUSER 10001:10001\n' in recipe
    assert 'V1_STOREFRONT_ENABLED=' not in recipe


def test_runtime_pin_hashes_are_backed_by_saved_primary_registry_metadata():
    metadata=json.loads((ROOT/'artifacts/v1/release-ci/pypi-runtime-hashes.json').read_text())
    lock=(ROOT/'deploy/v1/runtime.lock').read_text()
    for block in re.split(r'\n(?=[a-zA-Z])',lock):
        name,version=block.split('==',1)
        version=version.split()[0].rstrip('\\')
        record=metadata[name.split('[')[0]]
        assert record['version']==version
        hashes=set(re.findall(r'--hash=sha256:([a-f0-9]{64})',block))
        assert hashes and hashes.issubset(record['hashes'])


def test_mounted_native_journey_runs_sequentially_inside_required_pg_job():
    steps=workflow()['jobs']['migrated-postgres']['steps']
    runs=[step.get('run','') for step in steps]
    full=next(index for index,command in enumerate(runs) if 'pytest tests -q' in command)
    mounted=next(index for index,command in enumerate(runs) if 'python -m tests.run_wave4_native_browser' in command)
    assert mounted>full
    runner=(ROOT/'backend/tests/run_wave4_native_browser.py').read_text()
    assert 'async with migrated_database()' in runner
    assert 'tests.wave4_native_browser_server' in runner
    browser=(ROOT/'backend/tests/wave4_native_browser.mjs').read_text()
    assert "return route.abort()" in browser
    assert "assert.deepEqual(external,[])" in browser
