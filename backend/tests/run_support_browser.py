"""One guarded actual-chain lease covers native browser proof and cleanup."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio,os,secrets,sys
from pathlib import Path
from tests.isolated_database import migrated_database
async def main():
    root=Path(__file__).resolve().parents[2]
    async with migrated_database():
        nonce=secrets.token_urlsafe(32)
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.support_browser_server',nonce,cwd=root/'backend',env=dict(os.environ))
        try:
            child=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/support-grants.mjs'),nonce,cwd=root,env={**os.environ,'BROWSER_PYTHON':sys.executable})
            if await child.wait():raise SystemExit(child.returncode)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()
if __name__=='__main__':asyncio.run(main())
