"""Hold the actual P01/0053 lease for the entire real native owned-original browser journey."""
import os
_browser_env={k:os.environ[k] for k in ('PLAYWRIGHT_MODULE','PLAYWRIGHT_CHROMIUM_EXECUTABLE') if k in os.environ}
from tests.safety import install_test_safety
install_test_safety()
os.environ.update(_browser_env)
import asyncio
from pathlib import Path
import sys
import hashlib,json,subprocess
from sqlalchemy import text
from tests.isolated_database import migrated_database


async def main():
    root=Path(__file__).resolve().parents[2]
    paths=sorted({*root.glob('backend/app/**/*.py'),*root.glob('backend/alembic/versions/*.py'),*root.glob('backend/static/import_workspace.*'),root/'backend/tests/instagram_import_server.py',root/'backend/tests/run_instagram_import_browser.py',root/'backend/tests/browser/instagram-import.mjs'})
    def hashes():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=hashes()
    async with migrated_database() as engine:
        async with engine.connect() as db:head=await db.scalar(text('SELECT version_num FROM alembic_version'))
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.instagram_import_server',cwd=root/'backend',env=dict(os.environ))
        try:
            browser=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/instagram-import.mjs'),cwd=root,env=dict(os.environ))
            if await browser.wait():raise SystemExit(browser.returncode)
            after=hashes();assert before==after,'Source changed during mounted acceptance'
            output=root/'artifacts/v1/instagram-owned-integration/source-manifest.json'
            output.write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'actual_migration':head,'before':before,'after':after,'source_unchanged':True},indent=2)+'\n')
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()


if __name__=='__main__':asyncio.run(main())
