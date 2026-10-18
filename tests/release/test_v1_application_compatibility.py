"""Pure refusal/isolation checks; actual package journey is separately opt-in."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest

path=Path(__file__).with_name('run_application_compatibility.py')
spec=importlib.util.spec_from_file_location('application_compatibility',path)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
IMAGE='sha256:'+'a'*64


def test_mutable_image_tags_refused_before_docker(monkeypatch):
    monkeypatch.setattr(probe.subprocess,'check_output',lambda *a,**k:pytest.fail('Docker called'))
    with pytest.raises(probe.rehearsal.RehearsalError):probe.guest('latest','owned',SimpleNamespace(url='unused'),'read')


@pytest.mark.parametrize('field,value',[('Architecture','amd64'),('Id','sha256:'+'b'*64),('Config',{'User':'root'})])
def test_unreviewed_image_identity_or_privilege_refused(monkeypatch,field,value):
    info={'Id':IMAGE,'Architecture':'arm64','Config':{'User':'10001:10001'}};info[field]=value
    monkeypatch.setattr(probe.subprocess,'check_output',lambda *a,**k:json.dumps([info]).encode())
    monkeypatch.setattr(probe.subprocess,'run',lambda *a,**k:pytest.fail('Container created'))
    with pytest.raises(probe.rehearsal.RehearsalError):probe.guest(IMAGE,'owned',SimpleNamespace(url='unused'),'read')


@pytest.mark.parametrize('timeout',[False,True])
def test_guest_fences_network_resources_and_private_context_and_always_cleans(monkeypatch,timeout):
    monkeypatch.setattr(probe.subprocess,'check_output',lambda *a,**k:json.dumps([{'Id':IMAGE,'Architecture':'arm64','Config':{'User':'10001:10001'}}]).encode())
    cleanup=[];monkeypatch.setattr(probe,'cleanup_created_container',lambda cid:cleanup.append(cid))
    secret='SYNTHETIC-PRIVATE-NATIVE-COOKIE'
    def run(argv,**kwargs):
        assert secret not in str(argv) and secret in kwargs['input']
        assert '--env' not in argv and 'postgresql+' not in str(argv)
        assert 'socket.socket.connect_ex' in kwargs['input']
        assert argv[argv.index('--network')+1]=='container:owned'
        assert argv[argv.index('--memory')+1]=='768m' and '--read-only' in argv
        assert '--cidfile' in argv and '--cap-drop' in argv
        assert kwargs['timeout']==90 and kwargs['check'] is True
        if timeout:raise subprocess.TimeoutExpired(argv,90)
        return SimpleNamespace(stdout='{"checked":true}')
    monkeypatch.setattr(probe.subprocess,'run',run)
    args=(IMAGE,'owned',SimpleNamespace(url='postgresql+asyncpg://test:synthetic@127.0.0.1:55442/munimjee_test_owned',database='munimjee_test_owned'),'read',{'cookie':secret})
    if timeout:
        with pytest.raises(subprocess.TimeoutExpired):probe.guest(*args)
    else:assert probe.guest(*args)=={'checked':True}
    assert len(cleanup)==1
