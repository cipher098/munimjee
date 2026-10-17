"""Guard/reset/migrate/lease a disposable lane for a real local browser journey.

TEST_DATABASE_URL, TEST_LANE and TEST_DB_RESET=1 are mandatory. Install the
storefront's locked npm dependencies first. No server reuse or live services.
"""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
from pathlib import Path
import sys
from tests.isolated_database import migrated_database

async def main():
    root = Path(__file__).resolve().parents[2]
    async with migrated_database():
        server = await asyncio.create_subprocess_exec(sys.executable, "-m", "tests.v1_browser_server",
            cwd=root / "backend", env=dict(os.environ))
        try:
            node = await asyncio.create_subprocess_exec("node", str(root / "backend/tests/browser/onboarding.mjs"),
                cwd=root, env=dict(os.environ))
            result = await node.wait()
            if result:
                raise SystemExit(result)
        finally:
            if server.returncode is None:
                server.terminate()
            await server.wait()

if __name__ == "__main__":
    asyncio.run(main())
