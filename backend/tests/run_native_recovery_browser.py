"""Exclusive actual-0049 P01 lease spans server, Chromium and cleanup."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio,os,sys
from pathlib import Path
from tests.isolated_database import migrated_database
async def main():
    root=Path(__file__).resolve().parents[2]
    async with migrated_database():
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.native_recovery_server',cwd=root/'backend',env=dict(os.environ))
        try:
            browser=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/native-recovery.mjs'),*sys.argv[1:],cwd=root)
            code=await browser.wait()
            if code:raise SystemExit(code)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()
if __name__=='__main__':asyncio.run(main())
