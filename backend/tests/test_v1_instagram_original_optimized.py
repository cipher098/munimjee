"""Execute the actual byte reader at both Python optimization levels, no DB/HTTP."""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4,uuid5
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.services import import_originals, imports_v1


@pytest.mark.asyncio
@pytest.mark.parametrize('level',[0,1,2])
async def test_corrupt_original_rejected_even_when_python_assertions_are_removed(monkeypatch,level):
    bid,cid,jid,uid=uuid4(),uuid4(),uuid4(),uuid4()
    content=b'\x89PNG\r\n\x1a\nvalid-original'
    sha=hashlib.sha256(content).hexdigest();aid=uuid5(jid,'instagram-original:123:'+sha)
    manifest={'contract_version':'instagram-owned-manifest.v1','parent_media_id':'123','asset_media_id':'123',
        'asset_id':str(aid),'sha256':sha,'size_bytes':len(content),'content_type':'image/png','connection_version':1}
    audit=SimpleNamespace(details=manifest,actor_id=uid,job_id=jid,request_hash=imports_v1.digest(manifest),
        idempotency_key=uuid5(jid,'instagram-manifest:'+str(cid)+':123:'+sha))
    job=SimpleNamespace(id=jid,creator_id=uid,source={'kind':'instagram','media_id':'123','_connection':{'version':1}})
    asset=SimpleNamespace(id=aid,idempotency_key=aid,creator_id=uid,sha256=sha,size_bytes=len(content),content_type='image/png',content=b'\x89PNG\r\n\x1a\n'+b'x'*(len(content)-8))
    class DB:
        def __init__(self):self.rows=iter([SimpleNamespace(last_job_id=jid),job,asset])
        async def scalar(self,_):return next(self.rows)
        async def scalars(self,_):return SimpleNamespace(all=lambda:[audit])
    monkeypatch.setattr(imports_v1,'_access',AsyncMock())
    source=Path(import_originals.__file__).read_text()
    nodes=[node for node in ast.parse(source).body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'originals','require_integrity'}]
    namespace=dict(vars(import_originals))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(import_originals.__file__),'exec',optimize=level),namespace)
    with pytest.raises(HTTPException) as denied:await namespace['originals'](DB(),object(),bid,cid,asset_id=aid)
    assert denied.value.status_code==409
