"""Real app.main shared storefront hooks, native APIs, canonical order and PG16."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from sqlalchemy import text
from tests.isolated_database import migrated_database

async def main():
    root=Path(__file__).resolve().parents[2];nonce=secrets.token_hex(24)
    paths=sorted({*root.glob('backend/app/**/*.py'),*root.glob('backend/alembic/versions/*.py'),
        *root.glob('frontend/storefront/src/*.js'),Path(__file__),root/'backend/tests/activity_v1_server.py',
        root/'backend/tests/browser/activity-shell.mjs'})
    def hashes():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=hashes()
    async with migrated_database() as engine:
        async with engine.connect() as db:head=await db.scalar(text('select version_num from alembic_version'))
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.activity_v1_server',nonce,cwd=root/'backend',env=dict(os.environ))
        try:
            child=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/activity-shell.mjs'),cwd=root,env={**os.environ,'ACTIVITY_FIXTURE_NONCE':nonce})
            try:result=await asyncio.wait_for(child.wait(),180)
            except BaseException:
                if child.returncode is None:child.terminate();await child.wait()
                raise
            if result:raise SystemExit(result)
            after=hashes()
            if before!=after:raise RuntimeError('Source changed during actual mounted acceptance')
            output=root/'artifacts/v1/integration/wave7/activity-shell';output.mkdir(parents=True,exist_ok=True)
            (output/'source-manifest.json').write_text(json.dumps({'actual_head':head,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'before':before,'after':after,'source_unchanged':True,'shared_hooks':True,'classification_fixture':'Explicit local production-shaped policy for synthetic browser traffic; no live traffic or provider'},indent=2)+'\n')
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()

if __name__=='__main__':asyncio.run(main())
