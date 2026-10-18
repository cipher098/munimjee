"""Hold the actual P01/0053 lease for the entire real native browser journey."""
import os
_browser_env={k:os.environ[k] for k in ('PLAYWRIGHT_MODULE','PLAYWRIGHT_CHROMIUM_EXECUTABLE') if k in os.environ}
from tests.safety import install_test_safety
install_test_safety()
os.environ.update(_browser_env)
import asyncio
from pathlib import Path
import sys
from tests.isolated_database import migrated_database


async def main():
    root=Path(__file__).resolve().parents[2]
    async with migrated_database():
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.csv_import_server',cwd=root/'backend',env=dict(os.environ))
        try:
            browser=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/csv-import.mjs'),cwd=root,env=dict(os.environ))
            if await browser.wait():raise SystemExit(browser.returncode)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()


if __name__=='__main__':asyncio.run(main())
