"""One P01 actual migration/reset lease spans mounted server and Chromium."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
from pathlib import Path
import sys
from tests.isolated_database import migrated_database


async def main():
    root=Path(__file__).resolve().parents[2]
    async with migrated_database():
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.analytics_v1_server',cwd=root/'backend',env=dict(os.environ))
        try:
            child=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/analytics_v1.mjs'),cwd=root,env=dict(os.environ))
            if await child.wait():raise SystemExit(child.returncode)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()


if __name__=='__main__':asyncio.run(main())
